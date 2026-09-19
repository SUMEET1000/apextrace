"""Tyre degradation modelling.

The question a race engineer actually asks is "how much slower does this tyre
get per lap, and how confident are we?" - so every fitted rate here is
reported with a confidence interval rather than as a bare slope.

Two things have to be dealt with before a degradation number means anything:

1. **Fuel.** A car gets lighter and therefore faster through a stint, which
   partly cancels the tyre getting slower. Uncorrected, a genuinely degrading
   tyre can look flat. Handled by :func:`pitwall.transforms.fuel_correct`.
2. **Dirty laps.** Traffic, safety cars and pit laps all inflate lap times in
   ways that have nothing to do with the tyre. Handled by
   :func:`pitwall.transforms.clean_laps`, which reports what it removed.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import statsmodels.api as sm

from pitwall.config import (
    COMPOUND_ORDER,
    FUEL_EFFECT_S_PER_KG,
    race_fuel_kg,
)
from pitwall.transforms import clean_laps, fuel_correct

# Below this many laps a stint slope is noise, not a measurement.
MIN_STINT_LAPS = 5


def prepare(
    laps: pd.DataFrame,
    *,
    year: int,
    total_laps: int | None = None,
    fuel_effect_s_per_kg: float = FUEL_EFFECT_S_PER_KG,
    fuel_kg: float | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Clean the lap table and add a fuel-corrected lap time.

    Returns ``(laps, rejections)`` where ``laps`` has an added
    ``LapTime_corrected_s`` column and ``rejections`` is the audit trail from
    :func:`clean_laps`.
    """
    kept, rejections = clean_laps(laps)
    if kept.empty:
        return kept, rejections

    total = int(total_laps or laps["LapNumber"].max())
    fuel = fuel_kg if fuel_kg is not None else race_fuel_kg(year)

    out = kept.copy()
    out["LapTime_s"] = out["LapTime"].dt.total_seconds()
    out["LapTime_corrected_s"] = fuel_correct(
        out, total_laps=total, race_fuel_kg=fuel,
        fuel_effect_s_per_kg=fuel_effect_s_per_kg,
    )
    return out, rejections


def fit_stint(stint: pd.DataFrame) -> dict | None:
    """Fit degradation for a single stint.

    Regresses fuel-corrected lap time on tyre age with HC3 robust standard
    errors - lap-time scatter is not homoscedastic, and the naive standard
    errors would overstate confidence.

    Also fits a quadratic and compares by AIC. A quadratic that wins by a
    clear margin is the "cliff": degradation accelerating rather than holding
    a constant rate, which is the difference between a tyre that can be
    extended and one that must be changed.
    """
    required = {"TyreLife", "LapTime_corrected_s"}
    if not required.issubset(stint.columns):
        # Caller passed raw laps instead of the output of prepare().
        return None
    stint = stint.dropna(subset=["TyreLife", "LapTime_corrected_s"])
    if len(stint) < MIN_STINT_LAPS:
        return None

    age = stint["TyreLife"].to_numpy(dtype="float64")
    lap_time = stint["LapTime_corrected_s"].to_numpy(dtype="float64")
    if np.ptp(age) < 2:
        return None

    linear = sm.OLS(lap_time, sm.add_constant(age)).fit(cov_type="HC3")
    slope = float(linear.params[1])
    ci_low, ci_high = (float(v) for v in linear.conf_int()[1])

    quad_design = sm.add_constant(np.column_stack([age, age ** 2]))
    try:
        quadratic = sm.OLS(lap_time, quad_design).fit(cov_type="HC3")
        curvature = float(quadratic.params[2])
        delta_aic = float(linear.aic - quadratic.aic)
    except Exception:  # noqa: BLE001 - a degenerate stint should not kill the run
        curvature, delta_aic = np.nan, np.nan

    return {
        "Driver": stint["Driver"].iloc[0],
        "Team": stint["Team"].iloc[0] if "Team" in stint.columns else None,
        "Stint": float(stint["Stint"].iloc[0]),
        "Compound": stint["Compound"].iloc[0],
        "n_laps": int(len(stint)),
        "start_lap": int(stint["LapNumber"].min()),
        "end_lap": int(stint["LapNumber"].max()),
        "tyre_age_start": float(age.min()),
        "tyre_age_end": float(age.max()),
        "deg_s_per_lap": slope,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "std_err": float(linear.bse[1]),
        "p_value": float(linear.pvalues[1]),
        "r_squared": float(linear.rsquared),
        "intercept_s": float(linear.params[0]),
        "pace_s": float(np.median(lap_time)),
        # Positive curvature = degradation accelerating.
        "curvature": curvature,
        # > 2 is conventionally meaningful evidence for the quadratic.
        "quad_better_aic": delta_aic,
        "has_cliff": bool(delta_aic > 2 and curvature > 0) if np.isfinite(delta_aic) else False,
    }


def fit_all_stints(laps: pd.DataFrame) -> pd.DataFrame:
    """Degradation fit for every (driver, stint) with enough clean laps."""
    if laps.empty:
        return pd.DataFrame()
    rows = []
    for _, stint in laps.groupby(["Driver", "Stint"], observed=True):
        fit = fit_stint(stint)
        if fit is not None:
            rows.append(fit)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["Driver", "Stint"]).reset_index(drop=True)


def compound_summary(stints: pd.DataFrame) -> pd.DataFrame:
    """Pool stint-level fits into a degradation rate per compound.

    Stints are weighted by inverse variance, so a 25-lap stint counts for more
    than a 6-lap one - the standard way to combine estimates of the same
    quantity measured with different precision.
    """
    if stints.empty:
        return pd.DataFrame()

    rows = []
    for compound, group in stints.groupby("Compound", observed=True):
        group = group[group["std_err"] > 0]
        if group.empty:
            continue
        weights = 1.0 / group["std_err"] ** 2
        pooled = float((group["deg_s_per_lap"] * weights).sum() / weights.sum())
        pooled_se = float(np.sqrt(1.0 / weights.sum()))
        rows.append({
            "Compound": compound,
            "deg_s_per_lap": pooled,
            "ci_low": pooled - 1.96 * pooled_se,
            "ci_high": pooled + 1.96 * pooled_se,
            "std_err": pooled_se,
            "n_stints": int(len(group)),
            "n_laps": int(group["n_laps"].sum()),
            "median_pace_s": float(group["pace_s"].median()),
            # Pooled the same way as the slope, so compound paces can be
            # compared at a common tyre age rather than at whatever age each
            # compound happened to be driven at. See compound_offsets.
            "intercept_s": (float((group["intercept_s"] * weights).sum() / weights.sum())
                            if "intercept_s" in group.columns else np.nan),
            "n_with_cliff": int(group["has_cliff"].sum()),
        })

    if not rows:
        # Every group failed the usable-uncertainty filter. That is an empty
        # answer, not an error, so it returns the same columns as a full one.
        return pd.DataFrame(columns=[
            "Compound", "deg_s_per_lap", "ci_low", "ci_high", "std_err",
            "n_stints", "n_laps", "median_pace_s", "intercept_s", "n_with_cliff",
        ])

    out = pd.DataFrame(rows)
    out["_order"] = out["Compound"].map(
        {c: i for i, c in enumerate(COMPOUND_ORDER)}
    ).fillna(99)
    return out.sort_values("_order").drop(columns="_order").reset_index(drop=True)


def compound_offsets(summary: pd.DataFrame,
                     *, reference_age: float | None = None) -> pd.DataFrame:
    """Pace offset between compounds at a common tyre age.

    This is the number a strategist trades against pit loss: how much lap time
    a softer tyre is worth. The comparison has to be made at the same age,
    because each compound's median pace is measured at whatever age it
    happened to be driven at, and those differ - by up to 23 laps across the
    stored races, which moves an offset by up to 1.15 s in the dry and 2.92 s
    in the wet (measured 19 Sept 2026). That is the size of the offsets
    themselves, so the raw difference can be entirely age.

    ``reference_age`` defaults to the median age the compounds were actually
    observed at, keeping the answer inside the data. Falls back to the raw
    median difference when the summary carries no slope to adjust with.
    """
    if summary.empty or len(summary) < 2:
        return pd.DataFrame()

    out = summary[["Compound", "median_pace_s"]].copy()
    pace = out["median_pace_s"].to_numpy(dtype="float64")

    if {"deg_s_per_lap", "intercept_s"}.issubset(summary.columns):
        deg = summary["deg_s_per_lap"].to_numpy(dtype="float64")
        intercept = summary["intercept_s"].to_numpy(dtype="float64")
        # The age each compound's median pace corresponds to, read off its own
        # fitted line. A flat compound carries no age information, so it is
        # left out of the reference rather than dividing by ~zero.
        with np.errstate(divide="ignore", invalid="ignore"):
            observed_age = np.where(np.abs(deg) > 1e-9,
                                    (pace - intercept) / deg, np.nan)
        age = (float(reference_age) if reference_age is not None
               else float(np.nanmedian(observed_age)) if np.isfinite(observed_age).any()
               else np.nan)
        if np.isfinite(age):
            pace = intercept + deg * age
            out["tyre_age_laps"] = age

    out["pace_at_age_s"] = pace
    out["offset_s"] = pace - pace.max()
    return out.reset_index(drop=True)


def degradation_curve(stints: pd.DataFrame, compound: str,
                      max_age: int = 40) -> pd.DataFrame:
    """Fitted lap-time-vs-tyre-age curve for one compound, for plotting."""
    group = stints[stints["Compound"] == compound]
    if group.empty:
        return pd.DataFrame()
    age = np.arange(0, max_age + 1)
    weights = 1.0 / group["std_err"].clip(lower=1e-6) ** 2
    slope = float((group["deg_s_per_lap"] * weights).sum() / weights.sum())
    intercept = float((group["intercept_s"] * weights).sum() / weights.sum())
    return pd.DataFrame({"TyreLife": age, "fitted_s": intercept + slope * age})
