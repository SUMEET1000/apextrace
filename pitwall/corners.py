"""Corner-by-corner lap segmentation and driver comparison.

This is the module the whole "pit wall" idea rests on. A lap time difference
of 0.2s is not actionable; "0.08s of that comes from Copse, where he brakes
12 m later and carries 6 km/h more apex speed" is.

The lap is tiled into alternating corner and straight segments so that the
per-segment time deltas **sum exactly to the lap-time difference**. Reporting
corners alone would silently drop the straights, where power-unit and
slipstream differences live.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pitwall.config import (
    CORNER_MAX_ENTRY_M,
    CORNER_MAX_EXIT_M,
    THROTTLE_ON_PCT,
)


def build_segments(
    corners: pd.DataFrame,
    lap_length: float,
    *,
    max_entry_m: float = CORNER_MAX_ENTRY_M,
    max_exit_m: float = CORNER_MAX_EXIT_M,
) -> pd.DataFrame:
    """Tile a lap into corner and straight segments.

    A corner's natural extent runs from the midpoint of the preceding straight
    to the midpoint of the following one. That is clipped to ``max_entry_m`` /
    ``max_exit_m`` so a corner at the end of a long straight does not absorb
    the entire straight and take credit for a slipstream advantage.

    Whatever is left between two clipped corner windows becomes a ``straight``
    segment, so the tiling covers ``[0, lap_length]`` with no gaps.

    Parameters
    ----------
    corners
        Corner markers with ``Distance`` (apex, metres from the line) and
        ``CornerLabel``. Distances beyond ``lap_length`` are dropped.
    lap_length
        Reference lap length in metres.

    Returns
    -------
    DataFrame with ``segment_id, kind, label, start_m, end_m, apex_m``,
    ordered by ``start_m`` and contiguous.
    """
    if corners is None or corners.empty or "Distance" not in corners.columns:
        return pd.DataFrame(
            [{"segment_id": 0, "kind": "lap", "label": "Full lap",
              "start_m": 0.0, "end_m": float(lap_length), "apex_m": np.nan}]
        )

    c = corners.dropna(subset=["Distance"]).copy()
    c = c[(c["Distance"] >= 0) & (c["Distance"] <= lap_length)]
    c = c.sort_values("Distance").reset_index(drop=True)
    if c.empty:
        return build_segments(pd.DataFrame(), lap_length)

    apex = c["Distance"].to_numpy(dtype="float64")
    labels = (c["CornerLabel"] if "CornerLabel" in c.columns
              else c["Number"].astype(int).astype(str)).astype(str).tolist()
    n = len(apex)

    # Midpoints between consecutive apexes, wrapping across the start/finish
    # line so the first and last corners are treated like any other.
    mid_before = np.empty(n)
    mid_after = np.empty(n)
    for i in range(n):
        prev_apex = apex[i - 1] if i > 0 else apex[-1] - lap_length
        next_apex = apex[i + 1] if i < n - 1 else apex[0] + lap_length
        mid_before[i] = (prev_apex + apex[i]) / 2.0
        mid_after[i] = (apex[i] + next_apex) / 2.0

    start = np.maximum(mid_before, apex - max_entry_m)
    end = np.minimum(mid_after, apex + max_exit_m)

    # Clip to the lap. A corner sitting on the start/finish line gets a
    # truncated window; the telemetry ends there anyway.
    start = np.clip(start, 0.0, lap_length)
    end = np.clip(end, 0.0, lap_length)

    rows: list[dict] = []
    cursor = 0.0
    for i in range(n):
        if start[i] > cursor + 1.0:  # ignore sub-metre slivers
            rows.append({"kind": "straight", "label": f"Straight to T{labels[i]}",
                         "start_m": cursor, "end_m": start[i], "apex_m": np.nan})
        rows.append({"kind": "corner", "label": f"T{labels[i]}",
                     "start_m": start[i], "end_m": end[i], "apex_m": apex[i]})
        cursor = end[i]

    if cursor < lap_length - 1.0:
        rows.append({"kind": "straight", "label": "Straight to line",
                     "start_m": cursor, "end_m": float(lap_length), "apex_m": np.nan})

    seg = pd.DataFrame(rows)
    seg.insert(0, "segment_id", range(len(seg)))
    # Boundaries are also carried as fractions of the lap. Individual laps
    # differ in measured length by a few tenths of a percent, so metre
    # boundaries taken from a reference length would fall slightly short of
    # (or past) the end of any given lap. Comparing at the same *fraction* of
    # each lap is the same alignment the distance grid itself uses.
    seg["ref_length_m"] = float(lap_length)
    seg["start_rel"] = seg["start_m"] / lap_length
    seg["end_rel"] = seg["end_m"] / lap_length
    return seg


def _segment_slice(lap: pd.DataFrame, start_m: float, end_m: float) -> pd.DataFrame:
    d = lap["Distance"].to_numpy()
    mask = (d >= start_m) & (d <= end_m)
    if not mask.any():
        # Degenerate window narrower than the grid spacing - take the nearest
        # single sample so downstream code still gets a row.
        idx = int(np.abs(d - (start_m + end_m) / 2).argmin())
        mask = np.zeros(len(d), dtype=bool)
        mask[idx] = True
    return lap[mask]


def corner_metrics(lap: pd.DataFrame, segments: pd.DataFrame) -> pd.DataFrame:
    """Per-segment driving metrics for a single gridded lap.

    Corner-specific fields are NaN on straight segments.

    Metrics
    -------
    v_min / v_max     minimum (corner) or maximum (straight) speed, km/h
    apex_m_actual     distance at which minimum speed occurred
    v_entry / v_exit  speed at the segment boundaries
    brake_m           where the driver got on the brakes for this corner
    throttle_m        where the driver got back to full throttle
    brake_to_apex_m   braking distance - how late the car was braked
    seg_time_s        time spent in the segment
    """
    if lap.empty:
        return pd.DataFrame()

    required = {"Distance", "t", "Speed"}
    missing = required - set(lap.columns)
    if missing:
        raise ValueError(f"lap is missing required columns: {sorted(missing)}")

    # Boundary quantities are interpolated at the exact segment edges rather
    # than read off the nearest grid sample. Snapping to samples loses up to
    # one grid spacing of time per boundary (~0.09 s at 200 km/h), which
    # accumulates across segments and would stop the deltas summing to the
    # lap-time difference - the property the whole corner table relies on.
    #
    # Interpolation happens against relative distance so that each lap is
    # sampled at the same fraction of its own length, matching how the grid
    # aligns laps in the first place.
    has_rel = "RelDistance" in lap.columns and "start_rel" in segments.columns
    axis = lap["RelDistance" if has_rel else "Distance"].to_numpy(dtype="float64")
    lap_t = lap["t"].to_numpy(dtype="float64")
    lap_v = lap["Speed"].to_numpy(dtype="float64")

    rows = []
    for seg in segments.itertuples():
        s = _segment_slice(lap, seg.start_m, seg.end_m)
        speed = s["Speed"].to_numpy(dtype="float64")
        dist = s["Distance"].to_numpy(dtype="float64")

        edges = ([seg.start_rel, seg.end_rel] if has_rel
                 else [seg.start_m, seg.end_m])
        t_start, t_end = np.interp(edges, axis, lap_t)
        v_start, v_end = np.interp(edges, axis, lap_v)

        row = {
            "segment_id": seg.segment_id,
            "kind": seg.kind,
            "label": seg.label,
            "start_m": seg.start_m,
            "end_m": seg.end_m,
            "v_entry": v_start,
            "v_exit": v_end,
            "seg_time_s": t_end - t_start,
        }

        if seg.kind == "corner":
            i_min = int(speed.argmin())
            row["v_min"] = speed[i_min]
            row["v_max"] = np.nan
            row["apex_m_actual"] = dist[i_min]

            # Braking point: the last transition into braking before the apex.
            # Taking the *last* one matters - a driver may brush the brakes on
            # entry, release, then brake properly.
            row["brake_m"] = np.nan
            if "Brake" in s.columns:
                brake = s["Brake"].to_numpy().astype(bool)[: i_min + 1]
                if brake.any():
                    onsets = np.flatnonzero(brake & ~np.concatenate([[False], brake[:-1]]))
                    if len(onsets):
                        row["brake_m"] = dist[onsets[-1]]

            # A corner taken without braking and without lifting is "flat".
            # At a circuit like Silverstone that is most of the corner
            # markers, and reporting a throttle-application point for one
            # would be meaningless - the driver never came off the throttle.
            thr_all = (s["Throttle"].to_numpy(dtype="float64")
                       if "Throttle" in s.columns else None)
            lifted = thr_all is not None and bool((thr_all < THROTTLE_ON_PCT).any())
            row["is_flat"] = (not lifted) and np.isnan(row["brake_m"])

            # Throttle point: first return to (near) full throttle after apex.
            row["throttle_m"] = np.nan
            if thr_all is not None and not row["is_flat"]:
                thr = thr_all[i_min:]
                on = np.flatnonzero(thr >= THROTTLE_ON_PCT)
                if len(on):
                    row["throttle_m"] = dist[i_min + on[0]]

            row["brake_to_apex_m"] = (
                row["apex_m_actual"] - row["brake_m"]
                if not np.isnan(row["brake_m"]) else np.nan
            )
        else:
            row["v_min"] = np.nan
            row["v_max"] = float(speed.max())
            row["is_flat"] = False
            for k in ("apex_m_actual", "brake_m", "throttle_m", "brake_to_apex_m"):
                row[k] = np.nan

        rows.append(row)

    return pd.DataFrame(rows)


def compare_corners(
    lap_a: pd.DataFrame,
    lap_b: pd.DataFrame,
    segments: pd.DataFrame,
    *,
    name_a: str = "A",
    name_b: str = "B",
) -> pd.DataFrame:
    """Side-by-side segment comparison of two laps.

    ``lap_a`` is the reference. ``delta_s`` is the time B gains or loses in
    each segment: **negative means B is faster there**. Because the segments
    tile the whole lap, ``delta_s`` sums to the lap-time difference.
    """
    ma = corner_metrics(lap_a, segments)
    mb = corner_metrics(lap_b, segments)
    if ma.empty or mb.empty:
        return pd.DataFrame()

    keys = ["segment_id", "kind", "label", "start_m", "end_m"]
    out = ma[keys].copy()

    for col, better_low in (
        ("v_min", False), ("v_max", False), ("v_entry", False), ("v_exit", False),
        ("brake_m", False), ("throttle_m", True), ("brake_to_apex_m", True),
        ("apex_m_actual", None), ("seg_time_s", True),
    ):
        out[f"{col}_{name_a}"] = ma[col].to_numpy()
        out[f"{col}_{name_b}"] = mb[col].to_numpy()
        if better_low is not None:
            out[f"{col}_diff"] = mb[col].to_numpy() - ma[col].to_numpy()

    # The headline number: time B gained (negative) or lost (positive) here.
    out["delta_s"] = mb["seg_time_s"].to_numpy() - ma["seg_time_s"].to_numpy()
    out["cum_delta_s"] = out["delta_s"].cumsum()
    return out


def summarise_comparison(comparison: pd.DataFrame, *, top_n: int = 3) -> dict:
    """Headline findings from a comparison, for a plain-English summary."""
    if comparison.empty:
        return {}
    corners_only = comparison[comparison["kind"] == "corner"]
    ranked = comparison.reindex(comparison["delta_s"].abs().sort_values(ascending=False).index)
    return {
        "total_delta_s": float(comparison["delta_s"].sum()),
        "corner_delta_s": float(corners_only["delta_s"].sum()),
        "straight_delta_s": float(
            comparison[comparison["kind"] == "straight"]["delta_s"].sum()
        ),
        "biggest_gains": ranked[ranked["delta_s"] < 0].head(top_n)[
            ["label", "delta_s"]
        ].to_dict("records"),
        "biggest_losses": ranked[ranked["delta_s"] > 0].head(top_n)[
            ["label", "delta_s"]
        ].to_dict("records"),
    }
