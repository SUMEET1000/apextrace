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

import logging

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from pitwall.config import (
    CONTINUOUS_CHANNELS,
    DISCRETE_CHANNELS,
    GRID_POINTS,
    MAX_CORNER_SNAP_M,
    MIN_PARTIAL_COVERAGE,
    PIT_LANE_OFFSET_M,
    POSITION_UNITS_PER_M,
    STALE_POSITION_MIN_MOVE_M,
    STALE_POSITION_STEP_M,
    STINT_OUTLIER_FACTOR,
    STINT_OUTLIER_QUANTILE,
    TRACK_STATUS_CLEAR,
)

log = logging.getLogger(__name__)

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


def stale_position_fraction(tel: pd.DataFrame) -> float:
    """Fraction of a lap's *moving* samples whose position did not change.

    The position feed can freeze: it keeps emitting on schedule, but re-sends
    the last coordinate it had instead of a new one. Nothing about the frame
    looks wrong - the timestamps advance, the car channels are healthy, X/Y is
    populated - so every position-derived quantity comes out plausible and
    wrong. 2026/11_R is the case: from around lap 14 the trace holds still for
    stretches and then teleports, and its arc length lands on exactly 3649.8 m
    for hundreds of consecutive laps.

    The test is against the *speed* channel rather than against time, because
    a car that is genuinely stopped should not count as stale. Only intervals
    where speed says the car covered at least
    :data:`config.STALE_POSITION_MIN_MOVE_M` are counted, and of those, the
    ones where position moved less than
    :data:`config.STALE_POSITION_STEP_M`.

    Returns 0.0 when the question cannot be asked - no position channel, no
    speed channel, or no interval in which the car was moving.
    """
    if not {"X", "Y", "Speed"}.issubset(tel.columns) or len(tel) < 2:
        return 0.0
    xy = tel[["X", "Y"]].to_numpy(dtype="float64")
    if not np.isfinite(xy).all():
        return 0.0

    step_m = np.hypot(*np.diff(xy, axis=0).T) / POSITION_UNITS_PER_M
    dt_s = np.diff(_to_seconds(tel["Time"]))
    speed_ms = tel["Speed"].to_numpy(dtype="float64")[1:] / 3.6
    expected_m = speed_ms * dt_s

    moving = expected_m > STALE_POSITION_MIN_MOVE_M
    if not moving.any():
        return 0.0
    return float((step_m[moving] < STALE_POSITION_STEP_M).mean())


def start_line_offset(profile: np.ndarray, reference: np.ndarray) -> float:
    """How far a gridded lap has to be rotated to line up with a reference.

    Returned as a signed fraction of a lap in ``(-0.5, 0.5]``. Both arrays are
    the same channel (in practice ``Speed``) on the same distance grid, so the
    circular cross-correlation peak is the offset between where the lap thinks
    the start/finish line is and where the reference does.

    Braking points are what carry the signal: they sit at fixed places on the
    circuit and dominate the variance of a speed trace, so this measures track
    position rather than pace. Two laps driven at very different speeds still
    correlate at zero shift; the same lap rotated by a corner does not.
    """
    if len(profile) != len(reference) or len(profile) < 4:
        return 0.0
    a = np.asarray(profile, dtype="float64")
    b = np.asarray(reference, dtype="float64")
    if not (np.isfinite(a).all() and np.isfinite(b).all()):
        return 0.0
    a = a - a.mean()
    b = b - b.mean()
    if not a.any() or not b.any():
        return 0.0

    n = len(a)
    corr = np.fft.irfft(np.fft.rfft(a) * np.conj(np.fft.rfft(b)), n)
    shift = int(np.argmax(corr))
    if shift > n // 2:
        shift -= n
    return shift / n


def align_corner_distances(
    corners: pd.DataFrame,
    track_map: pd.DataFrame,
    rotation: float = 0.0,
) -> pd.DataFrame:
    """Re-measure each corner marker's ``Distance`` against the track map.

    FastF1 assigns corner distances by snapping each marker onto the raw
    position samples of ``session.laps.pick_fastest()``. Two things go wrong
    with that. The fastest lap is an arbitrary lap as far as the *position*
    feed is concerned - at Hungary 2026 it fell well inside the frozen stretch
    (see :func:`stale_position_fraction`), and several markers snapped onto the
    same held coordinate, giving duplicate and out-of-order distances that
    :func:`corners.corner_data_issues` then has to refuse. And its distance
    axis is FastF1's speed integral, while the stored telemetry grid is arc
    length along the position trace, so the two axes agree only by luck.

    The track map is the better reference on both counts: it is one validated,
    gridded, complete lap, and its ``Distance`` column *is* the axis the
    stored telemetry is resampled onto. Aligning against it makes corner
    markers land on the same axis as the traces they annotate by construction.

    Snapping each marker to its *nearest* map point independently is not enough,
    because a circuit visits some places twice. At Baku the 2.2 km main straight
    runs within a few metres of the T2-T3 section, and the nearest map point to
    T6 and T7 lies on the wrong one - 2025/17_Q realigns to T6 at 5004 m and T7
    at 4582 m, straddling T20, when the two belong at roughly 2100 m and 2490 m.
    An unconstrained snap has no way to know which of two adjacent passes it is
    looking at.

    Corner *numbering* supplies exactly that missing information: corners are
    numbered in the order the driver meets them, so their distances must
    increase. This picks the assignment minimising total squared marker-to-map
    distance **subject to** that ordering, by dynamic programming over the map
    (O(n_markers x grid), a few tens of thousands of states). Ambiguous markers
    are then resolved by their neighbours rather than in isolation.

    ``rotation`` is the circuit rotation already baked into the track map by
    :func:`extract_track_map`; the markers are unrotated, so the map is turned
    back rather than the markers turned forward.

    Returns ``corners`` unchanged when either frame lacks what it needs, so a
    session with no track map keeps whatever FastF1 provided. A marker left
    further than :data:`config.MAX_CORNER_SNAP_M` from the map it was matched
    to is logged: ordering can always be satisfied, so a large residual is the
    signal that the map or the markers are wrong rather than merely ambiguous.
    """
    if corners is None or corners.empty or not {"X", "Y"}.issubset(corners.columns):
        return corners
    if track_map is None or track_map.empty:
        return corners
    if not {"X", "Y", "Distance"}.issubset(track_map.columns):
        return corners

    theta = np.deg2rad(-rotation)
    mx = track_map["X"].to_numpy(dtype="float64")
    my = track_map["Y"].to_numpy(dtype="float64")
    unrotated = np.column_stack([
        mx * np.cos(theta) - my * np.sin(theta),
        mx * np.sin(theta) + my * np.cos(theta),
    ])

    markers = corners[["X", "Y"]].to_numpy(dtype="float64")
    usable = np.isfinite(markers).all(axis=1)
    if not usable.any():
        return corners

    map_distance = track_map["Distance"].to_numpy(dtype="float64")
    order = _corner_lap_order(corners)
    order = order[usable[order]]
    if len(order) > len(unrotated):
        return corners

    # squared distance from every ordered marker to every map point
    cost = ((markers[order][:, None, :] - unrotated[None, :, :]) ** 2).sum(axis=-1)
    idx = _monotone_assignment(cost)

    out = corners.copy()
    distance = np.full(len(out), np.nan)
    distance[order] = map_distance[idx]
    out["Distance"] = distance

    residual = np.sqrt(cost[np.arange(len(order)), idx]) / POSITION_UNITS_PER_M
    far = residual > MAX_CORNER_SNAP_M
    if far.any():
        log.warning(
            "%d corner marker(s) sit >%.0f m from the track map after "
            "alignment (worst %.0f m) - the map or the markers are unreliable",
            int(far.sum()), MAX_CORNER_SNAP_M, float(residual.max()),
        )
    return out


def _corner_lap_order(corners: pd.DataFrame) -> np.ndarray:
    """Row positions of ``corners`` in the order the driver meets them.

    ``Number`` plus ``Letter`` is the lap order - T1, T1A, T2 - and is what
    :func:`corners.corner_data_issues` requires distances to increase along.
    Falls back to stored row order when the columns are absent.
    """
    if "Number" not in corners.columns:
        return np.arange(len(corners))
    letter = (
        corners["Letter"].fillna("").astype(str).to_numpy()
        if "Letter" in corners.columns
        else np.array([""] * len(corners))
    )
    key = pd.DataFrame({"n": corners["Number"].to_numpy(), "l": letter})
    return key.sort_values(["n", "l"], kind="stable").index.to_numpy()


def _monotone_assignment(cost: np.ndarray) -> np.ndarray:
    """Cheapest strictly increasing map index per row of ``cost``.

    ``cost[i, k]`` is the price of putting marker ``i`` at map point ``k``.
    Returns one ``k`` per marker, strictly increasing, minimising the total.
    """
    n, grid = cost.shape
    best = np.empty((n, grid), dtype="float64")
    back = np.zeros((n, grid), dtype="int64")
    best[0] = cost[0]
    for i in range(1, n):
        prev = best[i - 1]
        run_min = np.minimum.accumulate(prev)
        run_arg = np.zeros(grid, dtype="int64")
        j = 0
        for k in range(1, grid):
            if prev[k] < prev[j]:
                j = k
            run_arg[k] = j
        best[i, 0] = np.inf
        best[i, 1:] = cost[i, 1:] + run_min[:-1]
        back[i, 1:] = run_arg[:-1]

    idx = np.empty(n, dtype="int64")
    idx[-1] = int(np.argmin(best[-1]))
    for i in range(n - 1, 0, -1):
        idx[i - 1] = back[i, idx[i]]
    return idx


def distance_from_position(tel: pd.DataFrame) -> pd.DataFrame:
    """Replace ``Distance`` with arc length measured along the position trace.

    FastF1 derives ``Distance`` by integrating ``Speed`` over time. That makes
    the distance axis inherit every defect of the speed channel, and because
    it is an integral the error never recovers - one mis-scaled stretch shifts
    every sample after it to the end of the lap. Arc length along X/Y is a
    direct measurement instead, so a bad sample costs one segment rather than
    the remainder of the lap.

    This matters more than it sounds. In 2026/02_Sprint the speed integral put
    lap length anywhere between 4.8 and 6.2 km on a 5451 m circuit, and the
    resulting spread was rejected wholesale by
    :data:`config.MAX_LAP_LENGTH_DEVIATION`; arc length recovers a median of
    5450.5 m with a 15 m interquartile range.

    Returns ``tel`` unchanged when there is no usable position data, so the
    speed integral stays the fallback rather than a hard requirement.
    """
    if not {"X", "Y"}.issubset(tel.columns) or len(tel) < 2:
        return tel
    xy = tel[["X", "Y"]].to_numpy(dtype="float64")
    if not np.isfinite(xy).all():
        return tel
    steps = np.hypot(*np.diff(xy, axis=0).T) / POSITION_UNITS_PER_M
    out = tel.copy()
    out["Distance"] = np.concatenate([[0.0], np.cumsum(steps)])
    return out


def resample_to_distance_grid(
    tel: pd.DataFrame,
    n_points: int = GRID_POINTS,
    *,
    anchor: str = "full",
    track_length: float | None = None,
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
    anchor
        Where the lap sits against the start/finish line.

        ``"full"``
            The lap covers the whole track; stretch it across the entire
            grid. This is every flying lap.
        ``"head"``
            The lap *starts* at the line but stops early - an in-lap, which
            ends at pit entry. Occupies the grid from 0 up to its coverage.
        ``"tail"``
            The lap *ends* at the line but began late - lap 1 from a grid
            box, or an out-lap from the pit exit. Occupies the grid from
            ``1 - coverage`` up to 1.

        The whole point of the anchors is that a partial lap must land on the
        part of the track it actually drove. Stretching one across [0, 1]
        - the only option before - silently misaligns every corner on it,
        which is why partial laps used to be dropped rather than stored.
    track_length
        The session's full lap length in metres. Required for the partial
        anchors, since a partial lap cannot measure the track itself.

    Returns
    -------
    DataFrame with exactly ``n_points`` rows and columns:
    ``RelDistance`` (0..1), ``Distance`` (metres), ``t`` (seconds from lap
    start), plus each resampled channel. ``LapLength`` is attached as a
    single-valued column so absolute distance can be recovered later, along
    with ``CovStart``/``CovEnd`` marking the covered span of the grid.
    Grid points outside that span are NaN for continuous channels.
    """
    if anchor not in ("full", "head", "tail"):
        raise ValueError(f"anchor must be full/head/tail, got {anchor!r}")
    if anchor != "full" and not track_length:
        raise ValueError(f"anchor={anchor!r} needs an explicit track_length")
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

    covered = float(d[-1])
    rel = np.linspace(0.0, 1.0, n_points)

    if anchor == "full":
        lap_length = covered
        cov_start, cov_end = 0.0, 1.0
        # Absolute distance along the lap for each grid point.
        sample_at = rel * lap_length
    else:
        lap_length = float(track_length)  # type: ignore[arg-type]
        frac = min(covered / lap_length, 1.0)
        if anchor == "head":
            cov_start, cov_end = 0.0, frac
            offset = 0.0
        else:  # tail
            cov_start, cov_end = 1.0 - frac, 1.0
            offset = lap_length - covered
        # Grid point -> distance into *this lap's* own telemetry. Points
        # outside the covered span fall outside [0, covered] and are masked.
        sample_at = rel * lap_length - offset

    inside = (rel >= cov_start - 1e-12) & (rel <= cov_end + 1e-12)

    def _mask(values: np.ndarray) -> np.ndarray:
        """NaN outside the covered span, so nothing invented gets read."""
        if anchor == "full":
            return values
        return np.where(inside, values, np.nan)

    out: dict[str, np.ndarray] = {
        "RelDistance": rel,
        "Distance": rel * lap_length,
        "t": _mask(np.interp(sample_at, d, t)),
    }

    for ch in CONTINUOUS_CHANNELS:
        if ch == "Time" or ch not in tel.columns:
            continue
        vals = tel[ch].to_numpy(dtype="float64")[keep]
        out[ch] = _mask(np.interp(sample_at, d, vals))

    for ch in DISCRETE_CHANNELS:
        if ch not in tel.columns:
            continue
        raw = tel[ch]
        vals = raw.to_numpy(dtype="float64")[keep] if raw.dtype != bool else raw.to_numpy()[keep]
        # Discrete channels keep an edge-held value outside the covered span:
        # they are stored as small ints and bools, which cannot carry NaN.
        # CovStart/CovEnd is the authority on what is real.
        out[ch] = _step_interp(sample_at, d, vals)

    frame = pd.DataFrame(out)
    frame["LapLength"] = lap_length
    frame["CovStart"] = cov_start
    frame["CovEnd"] = cov_end

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


def _fill(values: np.ndarray) -> np.ndarray:
    """NaN -> 0 so a masked partial lap still fits the integer encoding.

    The zeros are never read back as data: :func:`decode_grid` restores NaN
    everywhere outside ``CovStart``/``CovEnd``, which is what actually records
    where a partial lap has telemetry.
    """
    return np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0)


def encode_grid(frame: pd.DataFrame) -> pd.DataFrame:
    """Compact a gridded lap for storage. Inverse of :func:`decode_grid`."""
    out = pd.DataFrame(index=frame.index)
    out["t_us"] = (_fill(frame["t"].to_numpy(dtype="float64")) * _US_PER_S).round().astype("int32")
    if "Speed" in frame:
        out["Speed_dq"] = (_fill(frame["Speed"].to_numpy()) * _SPEED_SCALE).round().astype("int16")
    if "Throttle" in frame:
        out["Throttle_pct"] = pd.Series(
            _fill(frame["Throttle"].to_numpy()), index=frame.index
        ).round().clip(0, 100).astype("int8")
    if "RPM" in frame:
        out["RPM_dq"] = (_fill(frame["RPM"].to_numpy()) * _RPM_SCALE).round().astype("int16")
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

    # Restore the mask on partial laps. The encoder had to write zeros where a
    # lap has no telemetry, because the compact dtypes cannot hold NaN; without
    # this, a grid-start lap would read as 300 m of stationary car rather than
    # as track it never drove.
    if "CovStart" in out and "CovEnd" in out:
        outside = (rel < out["CovStart"].to_numpy() - 1e-9) | (rel > out["CovEnd"].to_numpy() + 1e-9)
        if outside.any():
            for ch in ("t", "Speed", "Throttle", "RPM"):
                if ch in out:
                    out.loc[outside, ch] = np.nan
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


def trim_to_track(
    tel: pd.DataFrame,
    track_xy: np.ndarray,
    side: str,
    max_offset_m: float = PIT_LANE_OFFSET_M,
) -> pd.DataFrame:
    """Drop the pit-lane run from one end of an in- or out-lap.

    FastF1 keeps counting ``Distance`` down the pit lane, so an out-lap can
    measure *longer* than the circuit (the crawl from the box to the pit exit
    is added to a nearly full lap of track). Anchoring such a lap to the
    start/finish line is only correct once that pit-lane run is removed.

    Detection is geometric rather than speed-based on purpose: the pit limiter
    sits at 80 km/h, but so does the Monaco hairpin, and a speed threshold
    would quietly amputate the slowest corner of the lap. Instead a sample
    counts as pit lane when it lies further than ``max_offset_m`` from the
    racing line.

    ``side`` is ``"lead"`` (out-lap: pit lane first) or ``"trail"`` (in-lap:
    pit lane last). Only the contiguous run at that end is removed - an
    off-track excursion mid-lap is left alone, since it is real driving.
    """
    if side not in ("lead", "trail"):
        raise ValueError(f"side must be lead/trail, got {side!r}")
    if not {"X", "Y"}.issubset(tel.columns) or len(track_xy) == 0:
        return tel

    pts = tel[["X", "Y"]].to_numpy(dtype="float64")
    dist, _ = cKDTree(track_xy).query(pts, k=1)
    off = dist > max_offset_m
    if not off.any():
        return tel

    n = len(tel)
    if side == "lead":
        # First sample that is on track, and everything after it.
        on = np.flatnonzero(~off)
        start = int(on[0]) if len(on) else n
        return tel.iloc[start:]
    on = np.flatnonzero(~off)
    end = int(on[-1]) + 1 if len(on) else 0
    return tel.iloc[:end]


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


def telemetry_coverage(
    laps: pd.DataFrame,
    telemetry: pd.DataFrame,
    *,
    stores_all_laps: bool = True,
) -> tuple[dict, pd.DataFrame]:
    """Which of a session's laps have stored telemetry, and why the rest do not.

    The ``laps`` artefact holds every lap of the session; ``telemetry`` holds
    only the laps that were successfully gridded. Any view driven by a lap
    *selector* can therefore offer strictly fewer laps than were driven, and a
    lap silently absent from a selector is indistinguishable from a lap that
    was never run. This reconciles the two and names every absence, for the
    same reason :func:`clean_laps` returns its rejections.

    ``stores_all_laps`` says whether this session type keeps every valid lap
    (races and sprints, ``config.LAPS_PER_DRIVER`` 0) or only a driver's
    fastest few (qualifying). It only changes how the residual is *described*:
    with every lap requested, a lap still missing means the source telemetry
    was absent or unusable; otherwise it was simply never requested.

    Returns
    -------
    (summary, rejections)
        ``summary`` carries ``n_laps`` / ``n_stored`` / ``n_missing`` /
        ``coverage``. ``rejections`` has one row per reason with a ``count``,
        in the order :func:`pitwall.ingest.extract_telemetry` applies them.
    """
    empty = pd.DataFrame(columns=["reason", "count", "pct_of_input"])
    n_laps = int(len(laps))
    if n_laps == 0:
        return ({"n_laps": 0, "n_stored": 0, "n_missing": 0, "coverage": 1.0,
                 "stores_all_laps": stores_all_laps}, empty)

    stored_keys: set[tuple[str, float]] = set()
    if not telemetry.empty:
        stored_keys = set(zip(telemetry["Driver"].astype(str),
                              telemetry["LapNumber"].astype(float)))
    key = pd.Series(
        list(zip(laps["Driver"].astype(str), laps["LapNumber"].astype(float))),
        index=laps.index,
    )
    stored = key.isin(stored_keys)
    n_stored = int(stored.sum())

    missing = laps.loc[~stored]
    summary = {
        "n_laps": n_laps,
        "n_stored": n_stored,
        "n_missing": n_laps - n_stored,
        "coverage": n_stored / n_laps,
        # Carried through so a caller can tell a shortfall that means something
        # went wrong from one that was the stated intent for this session type.
        "stores_all_laps": stores_all_laps,
    }
    if missing.empty:
        return summary, empty

    # Attribute each absence to the first filter that would have removed it,
    # in the order the ETL applies them - otherwise a deleted in-lap would be
    # counted twice and the reasons would not sum to the shortfall.
    reasons: list[dict] = []
    unexplained = pd.Series(True, index=missing.index)

    def _take(label: str, mask: pd.Series) -> None:
        nonlocal unexplained
        hit = unexplained & mask.reindex(missing.index, fill_value=False)
        count = int(hit.sum())
        if count:
            reasons.append({"reason": label, "count": count})
        unexplained = unexplained & ~hit

    def _col(name: str) -> pd.Series:
        if name not in missing.columns:
            return pd.Series(False, index=missing.index)
        return missing[name]

    # A missing column yields an all-False mask, so a session lacking one of
    # these simply attributes nothing to it.
    _take("no lap time recorded (retired or incomplete lap)",
          _col("LapTime").isna() & pd.Series("LapTime" in missing.columns,
                                             index=missing.index))
    _take("deleted lap", _col("Deleted").eq(True))

    pit_note = (f"below the {MIN_PARTIAL_COVERAGE:.0%} track-coverage floor"
                if stores_all_laps else "not stored for this session type")
    _take(f"in-lap ({pit_note})", _col("PitInTime").notna())
    _take(f"out-lap ({pit_note})", _col("PitOutTime").notna())
    _take(f"lap 1 from the grid ({pit_note})",
          missing["LapNumber"].astype(float).eq(1.0))

    _take(
        "telemetry missing or unusable in the source feed"
        if stores_all_laps else
        "not among the fastest laps kept for this session type",
        pd.Series(True, index=missing.index),
    )

    rejections = pd.DataFrame(reasons, columns=["reason", "count"])
    rejections["pct_of_input"] = (rejections["count"] / n_laps * 100).round(1)
    return summary, rejections


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
