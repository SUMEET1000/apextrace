"""Tests for corner segmentation and per-corner metrics."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pitwall.corners import (
    build_segments,
    compare_corners,
    corner_metrics,
    summarise_comparison,
)
from pitwall.transforms import resample_to_distance_grid
from tests.conftest import make_lap

LAP_LENGTH = 5000.0
APEXES = (1000.0, 2500.0, 4000.0)


@pytest.fixture
def segments(corners_frame):
    return build_segments(corners_frame, LAP_LENGTH)


@pytest.fixture
def gridded_lap():
    return resample_to_distance_grid(make_lap(lap_length=LAP_LENGTH), n_points=1000)


# -------------------------------------------------------------- segmentation

def test_segments_tile_the_lap_without_gaps(segments):
    """Deltas only sum to the lap time if the tiling is complete."""
    assert segments["start_m"].iloc[0] == pytest.approx(0.0)
    assert segments["end_m"].iloc[-1] == pytest.approx(LAP_LENGTH)
    ends = segments["end_m"].to_numpy()[:-1]
    starts = segments["start_m"].to_numpy()[1:]
    assert np.allclose(ends, starts)


def test_segments_do_not_overlap(segments):
    assert np.all(segments["end_m"].to_numpy() > segments["start_m"].to_numpy())


def test_every_corner_appears_exactly_once(segments):
    corners = segments[segments["kind"] == "corner"]
    assert len(corners) == len(APEXES)
    assert sorted(corners["label"]) == ["T1", "T2", "T3"]


def test_each_corner_window_contains_its_apex(segments):
    corners = segments[segments["kind"] == "corner"]
    for row in corners.itertuples():
        assert row.start_m <= row.apex_m <= row.end_m


def test_corner_windows_are_clipped_to_configured_limits(segments):
    """A corner after a long straight must not swallow the whole straight."""
    corners = segments[segments["kind"] == "corner"]
    for row in corners.itertuples():
        assert row.apex_m - row.start_m <= 400.0 + 1e-6
        assert row.end_m - row.apex_m <= 300.0 + 1e-6


def test_straights_are_created_between_corners(segments):
    assert (segments["kind"] == "straight").sum() >= len(APEXES)


def test_wraparound_corner_near_start_finish():
    """A corner sitting just after the line must still get a sane window."""
    corners = pd.DataFrame({
        "Number": [1, 2], "Letter": ["", ""], "CornerLabel": ["1", "2"],
        "Distance": [50.0, 2500.0],
    })
    seg = build_segments(corners, LAP_LENGTH)
    t1 = seg[seg["label"] == "T1"].iloc[0]
    assert t1["start_m"] >= 0.0
    assert t1["start_m"] <= 50.0 <= t1["end_m"]
    assert seg["start_m"].iloc[0] == pytest.approx(0.0)
    assert seg["end_m"].iloc[-1] == pytest.approx(LAP_LENGTH)


def test_missing_corner_data_degrades_to_a_single_segment():
    seg = build_segments(pd.DataFrame(), LAP_LENGTH)
    assert len(seg) == 1
    assert seg["kind"].iloc[0] == "lap"
    assert seg["end_m"].iloc[0] == LAP_LENGTH


def test_corners_outside_the_lap_are_ignored():
    corners = pd.DataFrame({
        "Number": [1, 2], "Letter": ["", ""], "CornerLabel": ["1", "2"],
        "Distance": [1000.0, 99999.0],
    })
    seg = build_segments(corners, LAP_LENGTH)
    assert sorted(seg[seg["kind"] == "corner"]["label"]) == ["T1"]


# ------------------------------------------------------------------ metrics

def test_minimum_speed_is_found_near_the_apex(gridded_lap, segments):
    """The synthetic lap dips to 90 km/h exactly at each apex."""
    metrics = corner_metrics(gridded_lap, segments)
    corners = metrics[metrics["kind"] == "corner"]
    assert np.allclose(corners["v_min"], 90.0, atol=1.0)
    for row in corners.itertuples():
        expected_apex = min(APEXES, key=lambda a: abs(a - row.apex_m_actual))
        assert row.apex_m_actual == pytest.approx(expected_apex, abs=20.0)


def test_braking_precedes_the_apex_and_throttle_follows_it(gridded_lap, segments):
    metrics = corner_metrics(gridded_lap, segments)
    corners = metrics[metrics["kind"] == "corner"]
    for row in corners.itertuples():
        assert row.brake_m < row.apex_m_actual
        assert row.throttle_m >= row.apex_m_actual
        assert row.brake_to_apex_m > 0


def test_last_braking_onset_wins():
    """A brush of the brakes then a real stop must report the real stop."""
    n = 400
    d = np.linspace(0, 1000, n)
    brake = np.zeros(n, dtype=bool)
    brake[50:60] = True    # early brush
    brake[200:260] = True  # the actual braking event
    lap = pd.DataFrame({
        "Distance": d,
        "t": d / 50.0,
        "Speed": np.concatenate([np.full(300, 200.0), np.full(n - 300, 100.0)]),
        "Brake": brake,
        "Throttle": np.zeros(n),
    })
    seg = pd.DataFrame([{"segment_id": 0, "kind": "corner", "label": "T1",
                         "start_m": 0.0, "end_m": 1000.0, "apex_m": 800.0}])
    got = corner_metrics(lap, seg).iloc[0]["brake_m"]
    assert got == pytest.approx(d[200], abs=d[1] - d[0] + 1e-9)


def test_segment_times_sum_to_the_lap_time(gridded_lap, segments):
    metrics = corner_metrics(gridded_lap, segments)
    assert metrics["seg_time_s"].sum() == pytest.approx(
        gridded_lap["t"].iloc[-1], abs=1e-3
    )


def test_metrics_require_the_core_columns():
    with pytest.raises(ValueError, match="missing required columns"):
        corner_metrics(pd.DataFrame({"Distance": [0.0, 1.0]}),
                       build_segments(pd.DataFrame(), 1.0))


# --------------------------------------------------------------- comparison

def test_segment_deltas_sum_to_the_lap_time_difference(segments):
    """The property that makes the corner table trustworthy."""
    a = resample_to_distance_grid(make_lap(lap_length=LAP_LENGTH, speed_scale=1.00, seed=7))
    b = resample_to_distance_grid(make_lap(lap_length=LAP_LENGTH, speed_scale=0.96, seed=7))
    cmp_ = compare_corners(a, b, segments)
    lap_gap = b["t"].iloc[-1] - a["t"].iloc[-1]
    assert cmp_["delta_s"].sum() == pytest.approx(lap_gap, abs=1e-3)
    assert cmp_["cum_delta_s"].iloc[-1] == pytest.approx(lap_gap, abs=1e-3)


def test_identical_laps_compare_to_zero_everywhere(gridded_lap, segments):
    cmp_ = compare_corners(gridded_lap, gridded_lap, segments)
    assert np.allclose(cmp_["delta_s"], 0.0, atol=1e-9)


def test_a_slower_corner_shows_a_positive_delta(segments):
    """Slow one corner only; that corner must carry the loss."""
    base = make_lap(lap_length=LAP_LENGTH, seed=11)
    slowed = base.copy()
    in_t2 = (slowed["Distance"] > 2200) & (slowed["Distance"] < 2800)
    slowed.loc[in_t2, "Speed"] *= 0.7
    v_ms = np.clip(slowed["Speed"].to_numpy(), 1.0, None) / 3.6
    dd = np.diff(slowed["Distance"].to_numpy(), prepend=0.0)
    slowed["Time"] = pd.to_timedelta(np.cumsum(dd / v_ms), unit="s")

    cmp_ = compare_corners(
        resample_to_distance_grid(base), resample_to_distance_grid(slowed), segments
    )
    losses = cmp_.set_index("label")["delta_s"]
    assert losses["T2"] > 0.05
    assert losses["T2"] == pytest.approx(losses.max(), rel=1e-6)


def test_summary_separates_corner_and_straight_losses(segments):
    a = resample_to_distance_grid(make_lap(lap_length=LAP_LENGTH, speed_scale=1.00, seed=13))
    b = resample_to_distance_grid(make_lap(lap_length=LAP_LENGTH, speed_scale=0.96, seed=13))
    summary = summarise_comparison(compare_corners(a, b, segments))
    assert summary["corner_delta_s"] + summary["straight_delta_s"] == pytest.approx(
        summary["total_delta_s"], abs=1e-6
    )
    assert summary["biggest_losses"]
