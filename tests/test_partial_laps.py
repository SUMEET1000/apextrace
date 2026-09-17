"""Partial laps: lap 1 from the grid, in-laps and out-laps.

These laps do not cover the whole track, so the question is not "can we store
them" but "do they land on the piece of track they actually drove". The tests
below check the alignment against a full lap of the same synthetic circuit,
and one of them deliberately reproduces the old stretch-to-fill behaviour to
show what it cost.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pitwall.config import PIT_LANE_OFFSET_M
from pitwall.corners import build_segments, compare_corners, summarise_comparison
from pitwall.transforms import (
    decode_grid,
    encode_grid,
    resample_to_distance_grid,
    trim_to_track,
)
from tests.conftest import make_lap

TRACK_LENGTH = 5000.0
N = 200


@pytest.fixture
def full_grid() -> pd.DataFrame:
    return resample_to_distance_grid(make_lap(lap_length=TRACK_LENGTH), n_points=N)


def _slice(frm: float = 0.0, to: float = TRACK_LENGTH) -> pd.DataFrame:
    """Raw telemetry for only part of the lap."""
    lap = make_lap(lap_length=TRACK_LENGTH)
    return lap[(lap["Distance"] >= frm) & (lap["Distance"] <= to)].reset_index(drop=True)


# --------------------------------------------------------------------------
# Anchoring
# --------------------------------------------------------------------------

def test_tail_anchored_lap_lands_on_the_track_it_actually_drove(full_grid):
    """A grid start covers the last 80% of the track, not a squashed 100%."""
    grid = resample_to_distance_grid(
        _slice(frm=1000.0), n_points=N, anchor="tail", track_length=TRACK_LENGTH,
    )

    assert grid["CovStart"].iloc[0] == pytest.approx(0.2, abs=0.01)
    assert grid["CovEnd"].iloc[0] == pytest.approx(1.0)

    covered = grid["Speed"].notna().to_numpy()
    assert not covered[: int(0.19 * N)].any(), "opening 19% should have no data"
    assert covered[int(0.21 * N):].all(), "everything after the start must be covered"

    # The whole point: at the same place on the track, the same speed.
    np.testing.assert_allclose(
        grid["Speed"].to_numpy()[covered],
        full_grid["Speed"].to_numpy()[covered],
        rtol=0.02,
    )


def test_head_anchored_lap_covers_the_opening_of_the_track(full_grid):
    """An in-lap runs from the line to pit entry: the first 80%."""
    grid = resample_to_distance_grid(
        _slice(to=4000.0), n_points=N, anchor="head", track_length=TRACK_LENGTH,
    )

    assert grid["CovStart"].iloc[0] == pytest.approx(0.0)
    assert grid["CovEnd"].iloc[0] == pytest.approx(0.8, abs=0.01)

    covered = grid["Speed"].notna().to_numpy()
    assert not covered[int(0.81 * N):].any()
    np.testing.assert_allclose(
        grid["Speed"].to_numpy()[covered],
        full_grid["Speed"].to_numpy()[covered],
        rtol=0.02,
    )


def test_stretching_a_partial_lap_misaligns_every_corner_on_it(full_grid):
    """The strawman: why partial laps could not simply be gridded as-is.

    Resampling a partial lap with ``anchor="full"`` is exactly what the ETL
    used to do to any lap that reached it, and it is why in/out-laps had to be
    thrown away instead. The corners end up in the wrong place, so the lap
    looks like a valid comparison while comparing T2 against T3.
    """
    partial = _slice(frm=1000.0)
    stretched = resample_to_distance_grid(partial, n_points=N)
    anchored = resample_to_distance_grid(
        partial, n_points=N, anchor="tail", track_length=TRACK_LENGTH,
    )

    ref = full_grid["Speed"].to_numpy()
    covered = anchored["Speed"].notna().to_numpy()

    anchored_err = np.abs(anchored["Speed"].to_numpy()[covered] - ref[covered]).mean()
    stretched_err = np.abs(stretched["Speed"].to_numpy()[covered] - ref[covered]).mean()

    assert anchored_err < 5.0, "anchored lap should sit on the right track"
    assert stretched_err > 5 * anchored_err, (
        "stretching a partial lap must visibly misalign it - if this fails the "
        "anchoring has stopped doing anything"
    )


def test_partial_anchor_requires_a_track_length():
    """A partial lap cannot measure the circuit, so it must be told."""
    with pytest.raises(ValueError, match="track_length"):
        resample_to_distance_grid(_slice(frm=1000.0), n_points=N, anchor="tail")


# --------------------------------------------------------------------------
# Pit-lane trimming
# --------------------------------------------------------------------------

def _with_pit_lane(side: str) -> tuple[pd.DataFrame, np.ndarray]:
    """A lap with a stretch of pit lane bolted onto one end.

    The synthetic circuit is a circle, so "pit lane" is a run of samples
    pushed radially outward well beyond the on-track threshold.
    """
    lap = make_lap(lap_length=TRACK_LENGTH).copy()
    track_xy = lap[["X", "Y"]].to_numpy(dtype="float64")
    n_pit = 60
    idx = slice(0, n_pit) if side == "lead" else slice(-n_pit, None)
    push = 1 + (PIT_LANE_OFFSET_M * 4) / 1000.0
    lap.loc[lap.index[idx], ["X", "Y"]] *= push
    return lap, track_xy


@pytest.mark.parametrize("side", ["lead", "trail"])
def test_trim_to_track_removes_the_pit_lane_run(side):
    lap, track_xy = _with_pit_lane(side)
    trimmed = trim_to_track(lap, track_xy, side)

    assert len(trimmed) == len(lap) - 60
    if side == "lead":
        assert trimmed["Distance"].iloc[0] > lap["Distance"].iloc[0]
    else:
        assert trimmed["Distance"].iloc[-1] < lap["Distance"].iloc[-1]


def test_trim_to_track_leaves_a_clean_lap_alone():
    lap = make_lap(lap_length=TRACK_LENGTH)
    track_xy = lap[["X", "Y"]].to_numpy(dtype="float64")
    assert len(trim_to_track(lap, track_xy, "lead")) == len(lap)


def test_trim_to_track_keeps_a_mid_lap_excursion():
    """Only the contiguous run at the named end is pit lane.

    Running wide in the middle of a lap is real driving and must survive, or
    every off-line moment would be silently deleted from the trace.
    """
    lap = make_lap(lap_length=TRACK_LENGTH).copy()
    track_xy = lap[["X", "Y"]].to_numpy(dtype="float64")
    mid = len(lap) // 2
    lap.loc[lap.index[mid:mid + 20], ["X", "Y"]] *= 1.05
    assert len(trim_to_track(lap, track_xy, "lead")) == len(lap)


# --------------------------------------------------------------------------
# Storage round-trip
# --------------------------------------------------------------------------

def test_encoding_round_trips_the_partial_lap_mask():
    """The compact dtypes cannot hold NaN, so coverage has to restore it.

    Without this the uncovered opening of a grid-start lap would decode as a
    stationary car sitting on the track rather than as absent data.
    """
    grid = resample_to_distance_grid(
        _slice(frm=1000.0), n_points=N, anchor="tail", track_length=TRACK_LENGTH,
    )
    meta = grid[["LapLength", "CovStart", "CovEnd"]].reset_index(drop=True)
    decoded = decode_grid(pd.concat([meta, encode_grid(grid)], axis=1), n_points=N)

    np.testing.assert_array_equal(decoded["Speed"].isna(), grid["Speed"].isna())
    assert decoded["Speed"].isna().sum() > 0
    covered = grid["Speed"].notna().to_numpy()
    np.testing.assert_allclose(
        decoded["Speed"].to_numpy()[covered],
        grid["Speed"].to_numpy()[covered],
        atol=0.2,
    )


# --------------------------------------------------------------------------
# Comparison
# --------------------------------------------------------------------------

def test_comparison_against_a_partial_lap_reports_its_coverage():
    """A partial comparison must announce that it is partial.

    Same rule as the audited-filtering one: dropping segments is fine,
    dropping them quietly is not.
    """
    corners = pd.DataFrame({
        "Number": [1, 2, 3], "Letter": ["", "", ""],
        "CornerLabel": ["1", "2", "3"],
        "Distance": [1000.0, 2500.0, 4000.0], "Rotation": [0.0] * 3,
    })
    segments = build_segments(corners, TRACK_LENGTH)

    full = resample_to_distance_grid(make_lap(lap_length=TRACK_LENGTH), n_points=N)
    partial = resample_to_distance_grid(
        _slice(frm=1000.0), n_points=N, anchor="tail", track_length=TRACK_LENGTH,
    )

    both_full = summarise_comparison(compare_corners(full, full, segments))
    assert both_full["coverage"] == pytest.approx(1.0)
    assert both_full["n_comparable"] == both_full["n_segments"]

    mixed = summarise_comparison(compare_corners(full, partial, segments))
    assert mixed["coverage"] < 0.95
    assert mixed["n_comparable"] < mixed["n_segments"]
    assert mixed["uncomparable_labels"], "the missing segments must be nameable"
