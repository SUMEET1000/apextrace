"""The ETL's choice of reference lap.

The reference lap is the datum for three things at once - the track map, the
pit-lane racing line, and the start/finish phase every other lap is measured
against. The third makes the choice load-bearing in a way the first two do
not: if the datum lap is itself misanchored, the phase guard inverts and drops
every *correctly* anchored lap in the session.

That is not hypothetical. In 2026/08_Q the session's fastest lap sits 2.4% of
a lap (~104 m) round from where 57 of its 88 laps agree the start line is, and
anchoring on it kept the 31-lap minority. These tests pin the fix: the datum
is the phase the largest group of laps shares, not the phase of the quickest
lap.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pitwall.config import MAX_START_LINE_OFFSET
from pitwall.ingest import _modal_offset, _reference_lap
from pitwall.transforms import start_line_offset

N = 500


def _profile() -> np.ndarray:
    """A periodic speed trace with enough structure to correlate against."""
    i = np.arange(N)
    return (250.0
            + 45.0 * np.sin(2 * np.pi * i / N)
            + 60.0 * np.sin(6 * np.pi * i / N)
            - 35.0 * np.cos(10 * np.pi * i / N))


def _lap(driver: str, lap_number: int, speed: np.ndarray,
         lap_time: float) -> pd.DataFrame:
    theta = 2 * np.pi * np.arange(N) / N
    return pd.DataFrame({
        "Driver": driver,
        "LapNumber": lap_number,
        "Speed": speed,
        "LapTime_s": lap_time,
        "X": np.cos(theta) * 1000.0,
        "Y": np.sin(theta) * 1000.0,
    })


def _session(n_majority: int, n_minority: int, shift: float) -> pd.DataFrame:
    """Two phase groups; the *fastest* lap is always in the minority."""
    base = _profile()
    rolled = np.roll(base, int(round(shift * N)))
    laps = []
    for k in range(n_minority):
        # quickest laps in the session, and all anchored in the wrong place
        laps.append(_lap(f"MIN{k}", k + 1, rolled, 60.0 + k * 0.01))
    for k in range(n_majority):
        laps.append(_lap(f"MAJ{k}", k + 1, base, 70.0 + k * 0.01))
    return pd.concat(laps, ignore_index=True)


def test_modal_offset_takes_the_larger_group():
    offsets = np.array([0.0, 0.001, -0.002, 0.0005, 0.031, 0.030, 0.032])
    assert abs(_modal_offset(offsets, 0.01)) < 0.01


def test_modal_offset_ignores_scattered_outliers():
    """A degraded feed scatters laps; a median of scatter is not a phase."""
    good = np.full(20, 0.002)
    scattered = np.linspace(-0.45, 0.45, 25)
    centre = _modal_offset(np.concatenate([good, scattered]), 0.01)
    assert abs(centre - 0.002) < 0.01


def test_reference_lap_follows_the_majority_not_the_fastest_lap():
    """2026/08_Q in miniature: the quickest lap is the misanchored one."""
    telemetry = _session(n_majority=57, n_minority=31, shift=0.024)
    ref = _reference_lap(telemetry)

    assert ref is not None
    assert ref["Driver"].iloc[0].startswith("MAJ")
    # and the datum it provides really is the majority's phase
    offset = start_line_offset(ref["Speed"].to_numpy(), _profile())
    assert abs(offset) <= MAX_START_LINE_OFFSET


def test_reference_lap_keeps_the_fastest_lap_when_the_session_agrees():
    """No inversion where there is nothing to invert - the common case."""
    telemetry = _session(n_majority=60, n_minority=0, shift=0.0)
    ref = _reference_lap(telemetry)

    assert ref is not None
    fastest = telemetry.loc[telemetry["LapTime_s"].idxmin(), "Driver"]
    assert ref["Driver"].iloc[0] == fastest


def test_the_clustering_window_resolves_groups_closer_than_the_threshold():
    """Why the window is half the rejection threshold, not equal to it.

    The two groups in 2026/08_Q sit 2.4% apart while the guard rejects at 2%.
    A window as wide as the threshold spans both groups and settles between
    them - on a phase neither group holds - which reads as "everything agrees"
    and keeps whichever group the fastest lap happens to be in.
    """
    # Each group has real width - that is what lets a wide window bridge them.
    # These spans are 2026/08_Q's, measured against its own fastest lap.
    majority = np.linspace(-0.035, -0.024, 57)
    minority = np.linspace(-0.009, 0.000, 31)
    offsets = np.concatenate([majority, minority])

    def group_size(centre: float, tol: float) -> int:
        return int((np.abs(offsets - centre) <= tol).sum())

    resolved = _modal_offset(offsets, MAX_START_LINE_OFFSET / 2)
    bridged = _modal_offset(offsets, MAX_START_LINE_OFFSET)

    # the narrow window lands inside the larger group and holds only that group
    assert majority.min() <= resolved <= majority.max()
    assert group_size(resolved, MAX_START_LINE_OFFSET / 2) == 57

    # the wide one reaches across the gap and counts laps from both
    assert group_size(bridged, MAX_START_LINE_OFFSET) > 57
