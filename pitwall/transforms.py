"""Core telemetry primitives: distance-grid resampling, delta time, lap cleaning.

Pure numpy/pandas - no FastF1, no Streamlit. Everything downstream (corners,
degradation, evolution, strategy) is built on the three public functions here.

Why a distance grid
-------------------
Raw telemetry is sampled in *time*, so two drivers' samples never line up in
space and every comparison needs a merge-and-interpolate. Resampling each lap
onto a fixed grid of relative-distance points makes comparison elementwise
arithmetic on aligned arrays.

Aligning on *relative* distance (fraction of lap) rather than absolute metres
is deliberate: drivers take different lines, so their total measured lap
distance differs by a few tenths of a percent. FastF1's own ``delta_time``
handles this by rescaling the comparison lap by ``ref_len / comp_len``, which
is algebraically the same alignment - we just precompute it once at ETL time
instead of on every comparison.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pitwall.config import (
    CONTINUOUS_CHANNELS,
    DISCRETE_CHANNELS,
    GRID_POINTS,
    STINT_OUTLIER_FACTOR,
    STINT_OUTLIER_QUANTILE,
    TRACK_STATUS_CLEAR,
)

# Channels stored as small integer / boolean types to keep Parquet compact.
_INT_CHANNELS = {"nGear": "int8", "DRS": "int8"}


def _to_seconds(series: pd.Series) -> np.ndarray:
    """Timedelta or numeric series -> float seconds."""
    if pd.api.types.is_timedelta64_dtype(series):
        return series.dt.total_seconds().to_numpy(dtype="float64")
    return series.to_numpy(dtype="float64")


def _step_interp(grid: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Piecewise-constant (zero-order hold) interpolation.

    Used for discrete channels. Linearly interpolating gear 4 and gear 6 would
    produce a gear 5 that the driver never selected; the same applies to brake
    and DRS state.
    """
    idx = np.searchsorted(x, grid, side="right") - 1
    idx = np.clip(idx, 0, len(y) - 1)
    return y[idx]


def resample_to_distance_grid(
    tel: pd.DataFrame,
    n_points: int = GRID_POINTS,
) -> pd.DataFrame:
    """Resample one lap of telemetry onto a uniform relative-distance grid.

    Parameters
    ----------
    tel
        Telemetry for a single lap. Must contain ``Distance`` and ``Time``;
        any of the configured continuous/discrete channels present are
        resampled, and missing ones are simply skipped.
    n_points
        Number of grid points. Every lap in the dataset uses the same value,
        which is what makes laps directly comparable.

    Returns
    -------
    DataFrame with exactly ``n_points`` rows and columns:
    ``RelDistance`` (0..1), ``Distance`` (metres), ``t`` (seconds from lap
    start), plus each resampled channel. ``LapLength`` is attached as a
    single-valued column so absolute distance can be recovered later.
    """
    if "Distance" not in tel.columns or "Time" not in tel.columns:
        raise ValueError("telemetry must contain 'Distance' and 'Time' columns")
    if len(tel) < 2:
        raise ValueError(f"need at least 2 telemetry samples, got {len(tel)}")

    d = tel["Distance"].to_numpy(dtype="float64")
    t = _to_seconds(tel["Time"])

    # Normalise both to start at zero.
    d = d - d[0]
    t = t - t[0]

    # Distance must be strictly increasing for np.interp. Position data is
    # noisy and occasionally stalls or steps backwards; keep the first sample
    # then only strictly-increasing ones.
    keep = np.concatenate([[True], np.diff(d) > 0])
    d, t = d[keep], t[keep]
    if len(d) < 2:
        raise ValueError("telemetry has no usable distance progression")

    lap_length = float(d[-1])
    rel = np.linspace(0.0, 1.0, n_points)
    grid_d = rel * lap_length

    out: dict[str, np.ndarray] = {
        "RelDistance": rel,
        "Distance": grid_d,
        "t": np.interp(grid_d, d, t),
    }

    for ch in CONTINUOUS_CHANNELS:
        if ch == "Time" or ch not in tel.columns:
            continue
        vals = tel[ch].to_numpy(dtype="float64")[keep]
        out[ch] = np.interp(grid_d, d, vals)

    for ch in DISCRETE_CHANNELS:
        if ch not in tel.columns:
            continue
        raw = tel[ch]
        vals = raw.to_numpy(dtype="float64")[keep] if raw.dtype != bool else raw.to_numpy()[keep]
        out[ch] = _step_interp(grid_d, d, vals)

    frame = pd.DataFrame(out)
    frame["LapLength"] = lap_length

    # Compact dtypes - this dataset ships inside the repo.
    for col in frame.columns:
        if col in _INT_CHANNELS:
            frame[col] = frame[col].round().astype(_INT_CHANNELS[col])
        elif col == "Brake":
            frame[col] = frame[col].astype(bool)
        else:
            frame[col] = frame[col].astype("float32")

    return frame


# --------------------------------------------------------------------------
# Storage encoding
# --------------------------------------------------------------------------
#
# The gridded telemetry is committed to the repo, so its on-disk size is a
# real constraint. Profiling one qualifying session showed 2.2 MB, of which
# almost all was float32 continuous channels. Three observations shrink it by
# ~4x with no analytically meaningful loss:
#
#   1. Distance and RelDistance are pure redundancy - on a uniform grid they
#      are a function of the row index and the lap length.
#   2. X/Y/Z are *circuit geometry*, identical for every driver, so they
#      belong in one session-level track map rather than repeated per lap.
#   3. The remaining channels carry far less real precision than a float32:
#      speed is meaningful to 0.1 km/h, throttle to 1%, RPM to 10 rpm.
#
# Time is kept as int32 microseconds. It is monotonic, so Parquet's
# delta encoding compresses it hard, and microsecond resolution is three
# orders of magnitude finer than the differences the analysis reports.

_SPEED_SCALE = 10.0   # 0.1 km/h
_RPM_SCALE = 0.1      # 10 rpm
_US_PER_S = 1_000_000

_ENCODED_SCHEMA = {
    "t_us": "int32",
    "Speed_dq": "int16",
    "Throttle_pct": "int8",
    "RPM_dq": "int16",
    "Brake": "bool",
    "nGear": "int8",
    "DRS": "int8",
}


def encode_grid(frame: pd.DataFrame) -> pd.DataFrame:
    """Compact a gridded lap for storage. Inverse of :func:`decode_grid`."""
    out = pd.DataFrame(index=frame.index)
    out["t_us"] = (frame["t"].to_numpy(dtype="float64") * _US_PER_S).round().astype("int32")
    if "Speed" in frame:
        out["Speed_dq"] = (frame["Speed"].to_numpy() * _SPEED_SCALE).round().astype("int16")
    if "Throttle" in frame:
        out["Throttle_pct"] = frame["Throttle"].round().clip(0, 100).astype("int8")
    if "RPM" in frame:
        out["RPM_dq"] = (frame["RPM"].to_numpy() * _RPM_SCALE).round().astype("int16")
    for ch in ("Brake", "nGear", "DRS"):
        if ch in frame:
            out[ch] = frame[ch]
    return out


def decode_grid(frame: pd.DataFrame, n_points: int = GRID_POINTS) -> pd.DataFrame:
    """Expand stored telemetry back to physical units.

    Reconstructs ``RelDistance`` and ``Distance`` from position within each
    lap and the lap's own ``LapLength``, so callers see the same columns the
    resampler produced.
    """
    out = frame.copy()
    if "t_us" in out:
        out["t"] = out.pop("t_us").astype("float64") / _US_PER_S
    if "Speed_dq" in out:
        out["Speed"] = out.pop("Speed_dq").astype("float32") / _SPEED_SCALE
    if "Throttle_pct" in out:
        out["Throttle"] = out.pop("Throttle_pct").astype("float32")
    if "RPM_dq" in out:
        out["RPM"] = out.pop("RPM_dq").astype("float32") / _RPM_SCALE

    # Position on the grid -> relative distance -> metres.
    rel = np.tile(np.linspace(0.0, 1.0, n_points), len(out) // n_points + 1)[: len(out)]
    out["RelDistance"] = rel.astype("float32")
    if "LapLength" in out:
        out["Distance"] = (out["RelDistance"] * out["LapLength"]).astype("float32")
    return out


def extract_track_map(frame: pd.DataFrame, rotation: float = 0.0) -> pd.DataFrame:
    """Session-level circuit geometry from one gridded reference lap.

    Every driver drives the same circuit, so X/Y is stored once per session
    rather than once per lap. ``rotation`` (degrees, from FastF1's circuit
    info) is applied so the map matches broadcast orientation.
    """
    if not {"X", "Y"}.issubset(frame.columns):
        return pd.DataFrame()
    theta = np.deg2rad(rotation)
    x = frame["X"].to_numpy(dtype="float64")
    y = frame["Y"].to_numpy(dtype="float64")
    return pd.DataFrame({
        "RelDistance": frame["RelDistance"].astype("float32"),
        "Distance": frame["Distance"].astype("float32"),
        "X": (x * np.cos(theta) - y * np.sin(theta)).astype("float32"),
        "Y": (x * np.sin(theta) + y * np.cos(theta)).astype("float32"),
    })


def delta_time(lap_a: pd.DataFrame, lap_b: pd.DataFrame) -> np.ndarray:
    """Cumulative time delta between two gridded laps.

    Both laps must be on the same grid (same ``n_points``), which
    :func:`resample_to_distance_grid` guarantees.

    Returns
    -------
    Array of ``t_b - t_a`` in seconds. **Positive means B is behind A**
    (B has taken more time to reach the same point on the lap). The final
    value equals the lap-time difference.
    """
    if len(lap_a) != len(lap_b):
        raise ValueError(
            f"laps are on different grids: {len(lap_a)} vs {len(lap_b)} points"
        )
    return lap_b["t"].to_numpy(dtype="float64") - lap_a["t"].to_numpy(dtype="float64")


def clean_laps(
    laps: pd.DataFrame,
    *,
    require_accurate: bool = True,
    drop_pit_laps: bool = True,
    require_clear_track: bool = True,
    drop_stint_outliers: bool = True,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Filter laps down to those usable for pace analysis.

    Every model in this project (degradation, evolution, race pace) depends on
    this filter, so it returns its own audit trail rather than dropping rows
    silently - the app surfaces the rejection breakdown so a user can see
    exactly what was excluded and why.

    Returns
    -------
    (kept, rejections)
        ``kept`` is the filtered frame. ``rejections`` has one row per reason
        with a ``count`` column, in the order the filters were applied.
    """
    df = laps.copy()
    reasons: list[dict] = []
    n_start = len(df)

    def _record(reason: str, mask_keep: pd.Series) -> pd.DataFrame:
        """Apply a keep-mask and record how many rows it removed."""
        removed = int((~mask_keep).sum())
        if removed:
            reasons.append({"reason": reason, "count": removed})
        return df[mask_keep]

    # A lap with no recorded time is unusable regardless of any other flag.
    df = _record("no lap time", df["LapTime"].notna())

    if require_accurate and "IsAccurate" in df.columns:
        # FastF1's own data-quality flag: timing is complete and consistent.
        # .eq(True) treats NaN as False without the deprecated fillna+astype
        # on an object-dtype column.
        df = _record("failed IsAccurate", df["IsAccurate"].eq(True))

    if drop_pit_laps:
        if "PitInTime" in df.columns:
            df = _record("in-lap (pit entry)", df["PitInTime"].isna())
        if "PitOutTime" in df.columns:
            df = _record("out-lap (pit exit)", df["PitOutTime"].isna())

    if require_clear_track and "TrackStatus" in df.columns:
        # Anything other than "1" means yellow / SC / VSC / red somewhere on
        # the lap, which makes the lap time meaningless as a pace measurement.
        status = df["TrackStatus"].astype(str)
        df = _record("track not clear (yellow/SC/VSC)", status == TRACK_STATUS_CLEAR)

    if drop_stint_outliers and len(df) and {"Driver", "Stint"}.issubset(df.columns):
        secs = df["LapTime"].dt.total_seconds()
        grp = df.groupby(["Driver", "Stint"], observed=True)
        # Two complementary cuts: an absolute 107%-of-stint-best rule catches
        # laps ruined by traffic or a mistake, while the per-stint quantile
        # adapts to stints that were genuinely slow throughout (wet, fuel-save).
        best = grp["LapTime"].transform(lambda s: s.dt.total_seconds().min())
        qhi = grp["LapTime"].transform(
            lambda s: s.dt.total_seconds().quantile(STINT_OUTLIER_QUANTILE)
        )
        keep = (secs <= best * STINT_OUTLIER_FACTOR) & (secs <= qhi * STINT_OUTLIER_FACTOR)
        df = _record("stint outlier (traffic / mistake)", keep)

    rejections = pd.DataFrame(reasons, columns=["reason", "count"])
    if not rejections.empty:
        rejections["pct_of_input"] = (rejections["count"] / max(n_start, 1) * 100).round(1)

    return df, rejections


def fuel_correct(
    laps: pd.DataFrame,
    *,
    total_laps: int,
    race_fuel_kg: float,
    fuel_effect_s_per_kg: float,
) -> pd.Series:
    """Remove the lap-time gain caused by burning fuel.

    A car gets faster through a stint simply because it is getting lighter,
    which partly cancels the tyre getting slower. Without this correction a
    genuinely degrading tyre can look flat.

    The correction is added back to early (heavy) laps so that every lap is
    expressed as *equivalent time at the end-of-race fuel load*:

        corrected = raw - effect * kg_per_lap * (total_laps - lap_number)

    Returns a Series of corrected lap times in seconds.
    """
    if total_laps <= 0:
        raise ValueError("total_laps must be positive")
    kg_per_lap = race_fuel_kg / total_laps
    laps_remaining = (total_laps - laps["LapNumber"]).clip(lower=0)
    penalty = fuel_effect_s_per_kg * kg_per_lap * laps_remaining
    return laps["LapTime"].dt.total_seconds() - penalty
