"""Track evolution: separating a rubbering-in circuit from tyre and fuel.

The identification problem
--------------------------
Within a single stint, tyre age and session time move together - lap 12 of a
stint is both "12 laps of wear" and "12 laps later in the race". From one
stint alone, "the tyre got slower" and "the track got faster" are the same
column of numbers, and no amount of curve fitting can tell them apart.

What breaks the collinearity is that **drivers do not pit at the same time**.
Across the field, a 10-lap-old tyre appears on lap 15 for one driver and on
lap 40 for another. Pooling all drivers therefore decorrelates tyre age from
session time, and both effects become separately estimable:

    corrected_laptime ~ C(Driver) + C(Compound):TyreLife + spline(progress)

- ``C(Driver)``            absorbs raw pace differences between cars
- ``C(Compound):TyreLife`` absorbs degradation, allowed to differ per compound
- ``spline(progress)``     everything left that depends only on *when* in the
                           session it is - that residual curve is the track
                           evolution

Fuel is removed beforehand rather than fitted, because fuel load is an almost
perfect linear function of lap number and would otherwise be absorbed into the
evolution term, inflating it several times over.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from patsy import dmatrix
from scipy import stats

# Degrees of freedom for the natural cubic spline on session progress. Four
# knots can follow the fast early rubbering-in and the later plateau without
# chasing lap-to-lap noise.
SPLINE_DF = 4

MIN_LAPS_FOR_MODEL = 40
MIN_DRIVERS_FOR_MODEL = 4


def fit_evolution(
    laps: pd.DataFrame,
    *,
    total_laps: int | None = None,
    spline_df: int = SPLINE_DF,
) -> dict | None:
    """Fit the pooled model and extract the track-evolution curve.

    ``laps`` must already be cleaned and fuel-corrected (see
    :func:`pitwall.degradation.prepare`).

    Returns a dict with the fitted model, the evolution curve with a
    confidence band, and the per-compound degradation the model implies -
    or None when the session cannot support the model.
    """
    needed = {"Driver", "Compound", "TyreLife", "LapNumber", "LapTime_corrected_s"}
    if laps.empty or not needed.issubset(laps.columns):
        return None

    df = laps.dropna(subset=list(needed)).copy()

    total = int(total_laps or df["LapNumber"].max())
    df["progress"] = df["LapNumber"] / max(total, 1)

    # Compounds with too few laps make the interaction term unstable.
    counts = df["Compound"].value_counts()
    df = df[df["Compound"].isin(counts[counts >= 10].index)]

    # Checked after every filter, not before. Run first, the guard passed a
    # 50-lap four-driver session that the compound filter then cut to 23 laps
    # from one driver.
    if (len(df) < MIN_LAPS_FOR_MODEL
            or df["Driver"].nunique() < MIN_DRIVERS_FOR_MODEL
            or df["Compound"].nunique() == 0):
        return None

    # C(Compound) earns its place: without the main effect a constant pace
    # difference between compounds has nowhere to go but the age slope, and a
    # 2 s soft advantage turned two true 0.100 s/lap slopes into 0.179 and
    # 0.031. With it, the interaction keeps full dummy coding, so each
    # compound's coefficient is still its own absolute slope.
    formula = (
        "LapTime_corrected_s ~ C(Driver) + C(Compound) + C(Compound):TyreLife "
        f"+ cr(progress, df={spline_df})"
    )
    try:
        model = smf.ols(formula, data=df).fit(cov_type="HC3")
    except Exception:  # noqa: BLE001 - degenerate session, fall back to no model
        return None

    if not _degradation_is_estimable(model):
        return None

    curve = _evolution_curve(model, df, spline_df=spline_df)
    return {
        "model": model,
        "curve": curve,
        "degradation": _compound_degradation(model),
        "n_laps": int(len(df)),
        "n_drivers": int(df["Driver"].nunique()),
        "r_squared": float(model.rsquared),
        "total_gain_s": float(curve["evolution_s"].iloc[0] - curve["evolution_s"].iloc[-1]),
    }


def _evolution_curve(model, df: pd.DataFrame, *, spline_df: int) -> pd.DataFrame:
    """Predicted lap time against session progress, holding everything else fixed.

    Driver and tyre are pinned to a single reference (the most common driver,
    a fresh tyre of the most-used compound) so the only thing varying along
    the curve is *when in the session* it is. The curve is then re-based to
    zero at the start, making it read as "seconds gained since the session
    began".
    """
    grid = pd.DataFrame({"progress": np.linspace(
        df["progress"].min(), df["progress"].max(), 100)})
    grid["Driver"] = df["Driver"].mode().iloc[0]
    grid["Compound"] = df["Compound"].mode().iloc[0]
    grid["TyreLife"] = 1.0

    # The plotted quantity is the contrast (x(t) - x(0))'beta, not x(t)'beta,
    # so its variance is the contrast's own: c' Sigma c. Subtracting the
    # baseline from an absolute prediction interval instead ignored the
    # baseline's variance and its covariance with the rest of the curve, and
    # put a +/-0.105 s band on a point that is identically zero.
    design = np.asarray(dmatrix(model.model.data.design_info, grid,
                                return_type="dataframe"), dtype="float64")
    contrast = design - design[0]
    mean = contrast @ model.params.to_numpy()
    variance = np.einsum("ij,jk,ik->i", contrast,
                         model.cov_params().to_numpy(), contrast)
    half_width = (stats.t.ppf(0.975, model.df_resid)
                  * np.sqrt(np.clip(variance, 0.0, None)))

    return pd.DataFrame({
        "progress": grid["progress"],
        # Negative = faster than at the start, so a falling line means the
        # track is improving.
        "evolution_s": mean,
        "ci_low": mean - half_width,
        "ci_high": mean + half_width,
    })


# Below this share of a slope column's variance left after projecting out the
# rest of the design, the coefficient is a pseudoinverse artefact rather than a
# measurement. It is a numerical-zero test, not a tuned threshold: real races
# measure 0.16-0.67 here (VIF 1.5-6.1, 19 Sept 2026) and an aliased design
# measures ~1e-31.
MIN_SLOPE_TOLERANCE = 1e-8


def _degradation_is_estimable(model) -> bool:
    """Whether the compound age slopes are separable from the rest of the fit.

    Tyre age and session progress only come apart because drivers pit at
    different times. Where they do not - a single-stint session, or one whose
    TyreLife tracks LapNumber - the design loses rank, and OLS answers from a
    pseudoinverse rather than failing. That reports a confident arbitrary split
    of one trend into two, with a zero-width confidence interval beside it.
    """
    exog = np.asarray(model.model.exog, dtype="float64")
    for i, name in enumerate(model.params.index):
        if ":TyreLife" not in name:
            continue
        column = exog[:, i]
        others = np.delete(exog, i, axis=1)
        beta, *_ = np.linalg.lstsq(others, column, rcond=None)
        residual = column - others @ beta
        total = float(((column - column.mean()) ** 2).sum())
        if total <= 0 or float(residual @ residual) / total < MIN_SLOPE_TOLERANCE:
            return False
    return True


def _compound_degradation(model) -> pd.DataFrame:
    """Per-compound degradation implied by the pooled model, with CIs."""
    rows = []
    conf = model.conf_int()
    for name in model.params.index:
        if ":TyreLife" not in name:
            continue
        # "C(Compound)[HARD]:TyreLife" under full dummy coding,
        # "C(Compound)[T.HARD]:TyreLife" under treatment coding.
        if "[" not in name:
            continue
        compound = name.split("[")[-1].split("]")[0].removeprefix("T.")
        rows.append({
            "Compound": compound,
            "deg_s_per_lap": float(model.params[name]),
            "ci_low": float(conf.loc[name, 0]),
            "ci_high": float(conf.loc[name, 1]),
            "p_value": float(model.pvalues[name]),
        })
    return pd.DataFrame(rows)


def naive_evolution(laps: pd.DataFrame, *, total_laps: int | None = None) -> pd.DataFrame:
    """The tempting-but-wrong version: lap time against session time alone.

    Shown alongside the pooled model in the app to make the point visible -
    a simple trend through all laps conflates track evolution with tyre and
    fuel effects and typically overstates the gain several times over.
    """
    if laps.empty:
        return pd.DataFrame()
    df = laps.dropna(subset=["LapNumber", "LapTime_corrected_s"]).copy()
    total = int(total_laps or df["LapNumber"].max())
    df["progress"] = df["LapNumber"] / max(total, 1)
    binned = (df.groupby(pd.cut(df["progress"], 20), observed=True)
                .agg(progress=("progress", "mean"),
                     lap_time=("LapTime_corrected_s", "median"))
                .dropna())
    if binned.empty:
        return pd.DataFrame()
    binned["evolution_s"] = binned["lap_time"] - binned["lap_time"].iloc[0]
    return binned.reset_index(drop=True)


def session_best_progression(laps: pd.DataFrame) -> pd.DataFrame:
    """Rolling session best against session time - the qualifying view.

    A race model needs stints; a qualifying session is short and everyone runs
    fresh rubber, so the honest descriptive view is simply how the session
    best improved as the track rubbered in.
    """
    if laps.empty or "LapStartTime" not in laps.columns:
        return pd.DataFrame()
    df = laps.dropna(subset=["LapTime", "LapStartTime"]).copy()
    if "Deleted" in df.columns:
        # clean_laps does not run here - this reads the raw lap table - so the
        # same policy has to be applied again, or a lap the stewards took away
        # becomes the advertised session record.
        df = df[~df["Deleted"].eq(True)]
    if df.empty:
        return pd.DataFrame()

    # A record exists when the lap crosses the line, not when it starts. On
    # start order the chart showed the record up to 137 s early in every one
    # of the 75 stored qualifying sessions (measured 19 Sept 2026).
    df["lap_finish"] = df["LapStartTime"] + df["LapTime"]
    df = df.sort_values("lap_finish")
    df["session_minutes"] = (
        df["lap_finish"] - df["LapStartTime"].min()
    ).dt.total_seconds() / 60.0
    df["lap_time_s"] = df["LapTime"].dt.total_seconds()
    df["session_best_s"] = df["lap_time_s"].cummin()
    return df[["session_minutes", "lap_time_s", "session_best_s", "Driver", "Compound"]]
