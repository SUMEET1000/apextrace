"""Race strategy: stints, race pace, pit loss and the undercut.

The undercut calculator is the part that turns the rest of the analysis into
a decision. It takes the degradation rate measured in
:mod:`pitwall.degradation` and the pit loss measured here, and answers the
question a pit wall actually faces: box now, or stay out?
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def stint_table(laps: pd.DataFrame) -> pd.DataFrame:
    """One row per driver stint: compound, lap range, length and pace.

    Built from the raw lap table rather than the cleaned one, because a stint
    boundary is defined by the pit stop - the very laps pace analysis throws
    away.
    """
    needed = {"Driver", "Stint", "Compound", "LapNumber"}
    if laps.empty or not needed.issubset(laps.columns):
        return pd.DataFrame()

    df = laps.dropna(subset=["Stint", "LapNumber"]).copy()
    if "LapTime" in df.columns:
        df["lap_time_s"] = df["LapTime"].dt.total_seconds()
    elif "LapTime_s" in df.columns:
        df["lap_time_s"] = df["LapTime_s"]
    else:
        df["lap_time_s"] = np.nan

    grouped = df.groupby(["Driver", "Stint"], observed=True).agg(
        Compound=("Compound", "first"),
        start_lap=("LapNumber", "min"),
        end_lap=("LapNumber", "max"),
        laps=("LapNumber", "count"),
        median_pace_s=("lap_time_s", "median"),
        best_lap_s=("lap_time_s", "min"),
    ).reset_index()
    return grouped.sort_values(["Driver", "start_lap"]).reset_index(drop=True)


def pit_loss(laps: pd.DataFrame) -> dict:
    """Estimate time lost to a pit stop, in seconds.

    Measured as the excess of the in-lap and out-lap over that driver's own
    clean-lap pace, so it nets out how quick the car was to begin with. The
    median across the field is more robust than any single stop, which may
    have involved a problem.
    """
    needed = {"Driver", "LapNumber", "PitInTime", "PitOutTime"}
    if laps.empty or not needed.issubset(laps.columns):
        return {}

    df = laps.copy()
    df["lap_time_s"] = (df["LapTime"].dt.total_seconds()
                        if "LapTime" in df.columns else df.get("LapTime_s"))
    df = df.dropna(subset=["lap_time_s"])
    if df.empty:
        return {}

    is_in = df["PitInTime"].notna()
    is_out = df["PitOutTime"].notna()
    clean = df[~is_in & ~is_out]
    if clean.empty:
        return {}

    baseline = clean.groupby("Driver", observed=True)["lap_time_s"].median()

    def _excess(mask: pd.Series) -> np.ndarray:
        """Excess over the driver's own clean pace, outlier-trimmed."""
        affected = df[mask]
        values = [
            row.lap_time_s - baseline[row.Driver]
            for row in affected.itertuples()
            if row.Driver in baseline.index and np.isfinite(baseline[row.Driver])
        ]
        arr = np.array([v for v in values if np.isfinite(v)])
        if len(arr) < 4:
            return arr
        # A stop that went wrong is not a measurement of normal pit loss.
        return arr[arr <= np.percentile(arr, 90)]

    # In-laps and out-laps must be measured separately and summed. They carry
    # very different amounts of the loss - the in-lap only gives up the run to
    # pit entry, while the out-lap absorbs the stationary time and the exit -
    # so pooling them and doubling the median badly understates the total.
    # A short pit visit can put entry and exit on the same lap. That lap holds
    # the whole loss once, so counting it in both medians doubled it: the
    # stored races reach 107.05 s against 58.60 s on 2024/06_Sprint, against a
    # true pit loss near 23 s (measured 19 Sept 2026).
    is_both = is_in & is_out
    in_excess = _excess(is_in & ~is_both)
    out_excess = _excess(is_out & ~is_both)
    both_excess = _excess(is_both)
    if not len(in_excess) and not len(out_excess) and not len(both_excess):
        return {}

    in_median = float(np.median(in_excess)) if len(in_excess) else 0.0
    out_median = float(np.median(out_excess)) if len(out_excess) else 0.0
    both_median = float(np.median(both_excess)) if len(both_excess) else 0.0

    return {
        "pit_loss_s": in_median + out_median + both_median,
        "in_lap_s": in_median,
        "out_lap_s": out_median,
        "n_in_laps": int(len(in_excess)),
        "n_out_laps": int(len(out_excess)),
        "n_same_lap": int(len(both_excess)),
        "n_stops": int(is_in.sum()),
    }


def race_pace(laps: pd.DataFrame) -> pd.DataFrame:
    """Median fuel-corrected clean pace per driver, with spread.

    ``laps`` should already be cleaned and fuel-corrected. Ranking on the
    median rather than the best lap answers "who was quick all race" rather
    than "who got one good lap in".
    """
    if laps.empty or "LapTime_corrected_s" not in laps.columns:
        return pd.DataFrame()

    out = laps.groupby("Driver", observed=True).agg(
        Team=("Team", "first") if "Team" in laps.columns else ("Driver", "first"),
        laps=("LapTime_corrected_s", "count"),
        median_s=("LapTime_corrected_s", "median"),
        best_s=("LapTime_corrected_s", "min"),
        p25_s=("LapTime_corrected_s", lambda s: s.quantile(0.25)),
        p75_s=("LapTime_corrected_s", lambda s: s.quantile(0.75)),
    ).reset_index()

    out = out[out["laps"] >= 5].sort_values("median_s").reset_index(drop=True)
    if not out.empty:
        out["gap_to_best_s"] = out["median_s"] - out["median_s"].iloc[0]
    return out


def head_to_head(laps: pd.DataFrame, driver_a: str, driver_b: str) -> pd.DataFrame:
    """Lap-by-lap comparison of two drivers over a whole session.

    One row per lap number either driver ran. ``delta_s`` is ``driver_b``
    minus ``driver_a`` on that lap, so a positive value means ``driver_b``
    lost time; ``cumulative_s`` is the running total.

    This works from the lap table rather than telemetry deliberately. Only a
    handful of laps per driver keep stored telemetry, but every lap has a
    time, so a head-to-head over the full session is available where a
    corner-level comparison is not.

    Laps only one driver completed keep their own time and score no delta,
    and the running total goes unknown from there. Filling the gap with zero
    instead would state that neither driver gained anything on a lap nobody
    measured, and that claim then rides in every later value.
    """
    if laps.empty or not {"Driver", "LapNumber"}.issubset(laps.columns):
        return pd.DataFrame()
    if "LapTime" not in laps.columns and "LapTime_s" not in laps.columns:
        return pd.DataFrame()

    # Same schema tolerance as gap_evolution below: read_laps restores the
    # timedelta columns, raw parquet and the synthetic fixtures carry seconds.
    df = laps.copy()
    df["lap_time_s"] = (df["LapTime"].dt.total_seconds()
                        if "LapTime" in df.columns else df["LapTime_s"])

    def side(driver: str, suffix: str) -> pd.DataFrame:
        one = (df[df["Driver"] == driver]
               .dropna(subset=["LapNumber"])
               .drop_duplicates(subset="LapNumber")
               .sort_values("LapNumber"))
        if one.empty:
            return pd.DataFrame()

        pit = pd.Series(False, index=one.index)
        for base in ("PitInTime", "PitOutTime"):
            for col in (base, f"{base}_s"):
                if col in one.columns:
                    pit |= one[col].notna()
                    break

        out = pd.DataFrame({
            "LapNumber": one["LapNumber"].to_numpy(),
            f"LapTime_s_{suffix}": one["lap_time_s"].to_numpy(),
            f"pit_{suffix}": pit.to_numpy(),
        })
        for extra in ("Compound", "TyreLife", "Stint", "Position"):
            if extra in one.columns:
                out[f"{extra}_{suffix}"] = one[extra].to_numpy()
        return out

    a, b = side(driver_a, "a"), side(driver_b, "b")
    if a.empty or b.empty:
        return pd.DataFrame()

    out = a.merge(b, on="LapNumber", how="outer").sort_values("LapNumber")
    out["delta_s"] = out["LapTime_s_b"] - out["LapTime_s_a"]
    # An unscored lap makes every later total unknown, so the series stops
    # rather than carrying an invented value forward.
    out["cumulative_s"] = out["delta_s"].cumsum(skipna=False)
    # eq(True) rather than fillna: the outer merge leaves NaN on laps only one
    # driver ran, and fillna on an object column is a deprecated downcast.
    for suffix in ("a", "b"):
        out[f"pit_{suffix}"] = out[f"pit_{suffix}"].eq(True)
    return out.reset_index(drop=True)


def gap_evolution(laps: pd.DataFrame) -> pd.DataFrame:
    """Cumulative time gap to the race leader, lap by lap."""
    needed = {"Driver", "LapNumber"}
    if laps.empty or not needed.issubset(laps.columns):
        return pd.DataFrame()

    df = laps.copy()
    df["lap_time_s"] = (df["LapTime"].dt.total_seconds()
                        if "LapTime" in df.columns else df.get("LapTime_s"))
    df = df.sort_values(["Driver", "LapNumber"])
    # Untimed laps are kept and the NaN is allowed to propagate. Dropping them
    # and summing the rest treated a driver's remaining laps as consecutive,
    # so one missing lap understated their elapsed time by a whole lap - and
    # could hand them the lead. 2024/05_R understates VER, PER and LEC by
    # about 300 s each (measured 19 Sept 2026). A driver whose elapsed time is
    # unknown also drops out of the leader minimum, which skipna does for free.
    df["elapsed_s"] = df.groupby("Driver", observed=True)["lap_time_s"].cumsum(skipna=False)

    leader = df.groupby("LapNumber", observed=True)["elapsed_s"].min().rename("leader_s")
    df = df.merge(leader, on="LapNumber", how="left")
    df["gap_s"] = df["elapsed_s"] - df["leader_s"]
    return df[["Driver", "LapNumber", "elapsed_s", "gap_s"]]


def undercut_gain(
    *,
    gap_to_rival_s: float,
    fresh_tyre_advantage_s: float,
    deg_s_per_lap: float,
    max_laps: int = 25,
) -> pd.DataFrame:
    """How far an undercut moves you against a rival, lap by lap.

    **The pit loss cancels, and that is the whole point of an undercut.**
    Walking through it: you are ``gap_to_rival_s`` behind and box on lap L.
    You immediately concede the pit loss P, so the gap becomes ``gap + P``.
    Over the next N laps you are on fresh rubber and take back the per-lap
    advantage. On lap L+N the rival boxes and concedes the same P, which
    removes it again. Net gap after both stops is therefore

        gap - (accumulated tyre advantage)

    with no P in it. Charging the driver the pit loss - the intuitive but
    wrong version - makes almost every undercut look impossible, because a
    ~20 s pit loss dwarfs anything a tyre advantage can repay.

    Pit loss still matters in practice, but for track position against the
    cars you rejoin among, not for this comparison.

    The per-lap advantage decays as the new tyre ages, floored at zero: a
    tyre that has used up its edge stops gaining, it does not start handing
    time back.
    """
    laps = np.arange(1, max_laps + 1)
    per_lap = np.maximum(fresh_tyre_advantage_s - deg_s_per_lap * (laps - 1), 0.0)
    cumulative = np.cumsum(per_lap)
    return pd.DataFrame({
        "laps_after_stop": laps,
        "per_lap_gain_s": per_lap,
        "cumulative_gain_s": cumulative,
        "net_gap_s": gap_to_rival_s - cumulative,
        "ahead": cumulative > gap_to_rival_s,
    })


def breakeven_lap(table: pd.DataFrame) -> int | None:
    """First lap on which the undercut puts you ahead, if it ever does."""
    if table.empty or "ahead" not in table.columns:
        return None
    winning = table[table["ahead"]]
    return int(winning["laps_after_stop"].iloc[0]) if not winning.empty else None


def max_undercut_gain(table: pd.DataFrame) -> float:
    """Total time an undercut can win before the fresh tyre runs out of edge."""
    if table.empty:
        return 0.0
    return float(table["cumulative_gain_s"].max())
