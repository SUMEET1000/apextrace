"""The circuit map against laps that do not cover the whole circuit.

A partial lap is NaN outside its covered span by design (see
``tests/test_partial_laps.py`` for why it is anchored rather than stretched).
The map has to survive that and, more importantly, has to leave the uncovered
track unpainted: a colour there would claim a driver's pace on a piece of
circuit they were not on.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pitwall.transforms import resample_to_distance_grid
from pitwall.viz.trackmap import _smooth, speed_delta_map, speed_map
from tests.conftest import make_lap

TRACK_LENGTH = 5000.0
N = 200


def _full() -> pd.DataFrame:
    return resample_to_distance_grid(
        make_lap(lap_length=TRACK_LENGTH), n_points=N,
    )


def _partial(frm: float) -> pd.DataFrame:
    """A grid start: the car joins the lap `frm` metres in."""
    lap = make_lap(lap_length=TRACK_LENGTH)
    return resample_to_distance_grid(
        lap[lap["Distance"] >= frm].reset_index(drop=True),
        n_points=N, anchor="tail", track_length=TRACK_LENGTH,
    )


@pytest.fixture
def track() -> pd.DataFrame:
    grid = _full()
    return grid[["X", "Y", "Distance"]].copy()


def _ribbon_segments(fig) -> int:
    """Coloured mini-sectors, excluding the glow underlay and overlays."""
    return sum(1 for t in fig.data
               if t.mode == "lines" and t.line.color != "rgba(0,0,0,0.85)")


# --------------------------------------------------------------------------
# The crash
# --------------------------------------------------------------------------

def test_delta_map_renders_when_one_lap_is_partial(track):
    """Lap 1 against a flying lap used to raise ValueError from the colourscale.

    NaN in the delta made every percentile NaN, so the scale limits were NaN,
    so every bin's colour position was NaN and plotly's integer rounding blew
    up. Nothing about the comparison is impossible - the covered span is real.
    """
    fig = speed_delta_map(track, _partial(1500.0), _full(), name_a="A", name_b="B")
    assert _ribbon_segments(fig) > 0


def test_speed_map_renders_when_the_lap_is_partial(track):
    fig = speed_map(track, _partial(1500.0))
    assert _ribbon_segments(fig) > 0


def test_maps_survive_a_lap_with_no_usable_telemetry(track):
    """The degenerate end of the same bug: nothing finite to colour by."""
    blank = _full()
    blank[["t", "Speed"]] = np.nan
    assert _ribbon_segments(speed_delta_map(track, blank, _full(),
                                           name_a="A", name_b="B")) == 0
    assert _ribbon_segments(speed_map(track, blank)) == 0


# --------------------------------------------------------------------------
# Honesty about what was covered
# --------------------------------------------------------------------------

def test_uncovered_track_is_left_unpainted(track):
    """Fewer mini-sectors for a partial lap, in proportion to what it drove.

    The alternative - carrying the last known colour across the gap - is the
    stretch-to-fill mistake in a different costume.
    """
    full = _ribbon_segments(speed_delta_map(track, _full(), _full(),
                                            name_a="A", name_b="B"))
    part = _ribbon_segments(speed_delta_map(track, _partial(1500.0), _full(),
                                            name_a="A", name_b="B"))
    assert 0 < part < full
    # 3500 m of 5000 m driven, give or take the smoothing window.
    assert part == pytest.approx(full * 0.7, abs=0.06 * full)


def test_hover_readout_only_covers_samples_both_laps_recorded(track):
    """No point may report a running gap that neither lap can support."""
    fig = speed_delta_map(track, _partial(1500.0), _full(), name_a="A", name_b="B")
    hover = next(t for t in fig.data if t.mode == "markers" and t.customdata is not None)
    assert np.isfinite(np.asarray(hover.customdata, dtype=float)).all()
    assert len(hover.x) < N


# --------------------------------------------------------------------------
# Smoothing
# --------------------------------------------------------------------------

def test_smoothing_does_not_eat_covered_track():
    """A boxcar convolution turns one NaN into `window` NaNs.

    That is the difference between reporting the gap this lap covered and
    silently discarding a further 2% of it at each edge, which is why this is
    a nan-aware mean rather than np.convolve.
    """
    values = np.arange(100.0)
    values[:10] = np.nan
    smoothed = _smooth(values, window=11)
    assert np.isnan(smoothed[:10]).all()
    assert np.isfinite(smoothed[10:]).all()


def test_smoothing_matches_a_plain_boxcar_when_nothing_is_missing():
    values = np.sin(np.linspace(0, 6, 200))
    window = 9
    expected = np.convolve(values, np.ones(window) / window, mode="same")
    got = _smooth(values, window)
    # The edges differ by construction: np.convolve divides by the full window
    # even where it hangs off the end, this divides by what it actually saw.
    assert got[window:-window] == pytest.approx(expected[window:-window])
