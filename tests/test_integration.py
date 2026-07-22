"""Validation against real data and official timing.

These tests skip when the curated dataset has not been built, so the suite
still runs on a clean checkout.

The important one is the sector-time check. FastF1's own ``utils.delta_time``
is deprecated and its docstring warns that it "has a tendency to give
inaccurate results", recommending verification against sector times instead -
so that is what we do here, rather than agreeing with a function its authors
no longer trust.

The idea: a sector line is a fixed point on the track. Take each driver's
officially timed Sector 1 duration, find the distance at which that much time
had elapsed in their telemetry, and every driver should land on the *same*
distance. The spread across drivers measures the accuracy of the whole
resample-and-align pipeline in metres.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pitwall import store
from pitwall.corners import build_segments, compare_corners
from pitwall.ingest import SessionKey
from pitwall.transforms import delta_time

KEY = SessionKey(2024, 12, "Q")  # Silverstone qualifying


@pytest.fixture(scope="module")
def bundle():
    if not store.session_is_complete(KEY):
        pytest.skip(f"dataset for {KEY} not built - run scripts/build_dataset.py")
    return {
        "telemetry": store.read_telemetry(KEY),
        "laps": store.read_artefact(KEY, "laps"),
        "corners": store.read_artefact(KEY, "corners"),
        "trackmap": store.read_artefact(KEY, "trackmap"),
    }


@pytest.fixture(scope="module")
def timed_laps(bundle):
    """Stored telemetry laps joined to their official sector times."""
    tel = bundle["telemetry"]
    laps = bundle["laps"][
        ["Driver", "LapNumber", "LapTime_s", "Sector1Time_s", "Sector2Time_s", "Sector3Time_s"]
    ].copy()
    laps["LapNumber"] = laps["LapNumber"].astype(int)

    keys = tel[["Driver", "LapNumber"]].drop_duplicates()
    keys["Driver"] = keys["Driver"].astype(str)
    merged = keys.merge(laps, on=["Driver", "LapNumber"], how="inner")
    return merged.dropna(subset=["Sector1Time_s", "Sector2Time_s"])


def _distance_at_elapsed(lap: pd.DataFrame, seconds: float) -> float:
    """Distance at which a given amount of lap time had elapsed."""
    return float(np.interp(seconds, lap["t"].to_numpy(), lap["Distance"].to_numpy()))


def test_dataset_has_expected_shape(bundle):
    assert not bundle["telemetry"].empty
    assert len(bundle["corners"]) == 18          # Silverstone
    assert len(bundle["trackmap"]) == 1000
    lengths = bundle["telemetry"].groupby(["Driver", "LapNumber"], observed=True).size()
    assert set(lengths.unique()) == {1000}       # every lap on the same grid


def test_lap_time_matches_official_timing(bundle, timed_laps):
    """Telemetry-derived lap duration must match the timing feed."""
    tel = bundle["telemetry"]
    errors = []
    for row in timed_laps.itertuples():
        lap = store.get_lap(tel, row.Driver, row.LapNumber)
        errors.append(abs(lap["t"].iloc[-1] - row.LapTime_s))
    errors = np.array(errors)
    # Telemetry starts and ends fractionally off the timing line, so a small
    # constant offset is expected; large errors would mean misaligned laps.
    assert np.median(errors) < 0.35, f"median lap-time error {np.median(errors):.3f}s"
    assert errors.max() < 1.0, f"worst lap-time error {errors.max():.3f}s"


def test_sector_lines_land_at_a_consistent_distance(bundle, timed_laps):
    """The core validation: all drivers must cross a sector line at the
    same point on track, independently derived from official sector times."""
    tel = bundle["telemetry"]
    lap_length = float(tel["LapLength"].median())

    for sector, cumulative in (("S1", "Sector1Time_s"), ("S2", "Sector2Time_s")):
        distances = []
        for row in timed_laps.itertuples():
            lap = store.get_lap(tel, row.Driver, row.LapNumber)
            elapsed = (row.Sector1Time_s if sector == "S1"
                       else row.Sector1Time_s + row.Sector2Time_s)
            distances.append(_distance_at_elapsed(lap, elapsed))

        distances = np.array(distances)
        spread = distances.std()
        # Under 1% of lap length: the sector line is being located to within
        # a couple of car lengths across the whole field.
        assert spread < 0.01 * lap_length, (
            f"{sector} line spread {spread:.1f} m over {len(distances)} laps "
            f"(lap length {lap_length:.0f} m)"
        )


def test_delta_time_reproduces_official_sector_gaps(bundle, timed_laps):
    """Delta time at the sector line must match the officially timed gap.

    This is the end-to-end check on the headline number the app reports.
    """
    tel = bundle["telemetry"]
    reference = timed_laps.loc[timed_laps["LapTime_s"].idxmin()]
    ref_lap = store.get_lap(tel, reference["Driver"], int(reference["LapNumber"]))

    # Locate the S1 line once, as the median across the field.
    s1_distances = []
    for row in timed_laps.itertuples():
        lap = store.get_lap(tel, row.Driver, row.LapNumber)
        s1_distances.append(_distance_at_elapsed(lap, row.Sector1Time_s))
    s1_line = float(np.median(s1_distances))

    errors = []
    for row in timed_laps.itertuples():
        if row.Driver == reference["Driver"]:
            continue
        lap = store.get_lap(tel, row.Driver, row.LapNumber)
        delta = delta_time(ref_lap, lap)
        measured = float(np.interp(s1_line, ref_lap["Distance"].to_numpy(), delta))
        official = row.Sector1Time_s - reference["Sector1Time_s"]
        errors.append(abs(measured - official))

    errors = np.array(errors)
    assert np.median(errors) < 0.10, (
        f"median S1 delta error {np.median(errors):.3f}s across {len(errors)} drivers"
    )


def test_segment_deltas_sum_to_the_real_lap_time_gap(bundle, timed_laps):
    """On real telemetry, the corner table must still account for the whole lap."""
    tel = bundle["telemetry"]
    lap_length = float(tel["LapLength"].median())
    segments = build_segments(bundle["corners"], lap_length)

    fastest_two = timed_laps.nsmallest(2, "LapTime_s")
    a = store.get_lap(tel, fastest_two.iloc[0]["Driver"], int(fastest_two.iloc[0]["LapNumber"]))
    b = store.get_lap(tel, fastest_two.iloc[1]["Driver"], int(fastest_two.iloc[1]["LapNumber"]))

    comparison = compare_corners(a, b, segments)
    lap_gap = b["t"].iloc[-1] - a["t"].iloc[-1]
    assert comparison["delta_s"].sum() == pytest.approx(lap_gap, abs=5e-3)


def test_braking_points_are_physically_sane(bundle, timed_laps):
    """Every corner should show braking before the apex and throttle after."""
    tel = bundle["telemetry"]
    segments = build_segments(bundle["corners"], float(tel["LapLength"].median()))
    fastest = timed_laps.loc[timed_laps["LapTime_s"].idxmin()]
    lap = store.get_lap(tel, fastest["Driver"], int(fastest["LapNumber"]))

    from pitwall.corners import corner_metrics
    metrics = corner_metrics(lap, segments)
    corners = metrics[metrics["kind"] == "corner"]

    assert len(corners) == 18
    assert corners["v_min"].between(40, 330).all(), "implausible minimum speeds"

    braked = corners.dropna(subset=["brake_m"])
    # Silverstone is a low-braking circuit: Abbey, Farm and the
    # Maggotts/Becketts complex are all flat in qualifying trim, so only
    # about seven genuine braking zones exist. Assert a plausible range
    # rather than a count per corner marker.
    assert 5 <= len(braked) <= 12, f"{len(braked)} braking zones is implausible"
    assert (braked["brake_m"] < braked["apex_m_actual"]).all()

    # Corners without braking must be classified flat, not given a
    # meaningless throttle-application point.
    flat = corners[corners["is_flat"]]
    assert len(flat) > 0, "expected flat-out corners at Silverstone"
    assert flat["throttle_m"].isna().all()
    assert flat["v_min"].min() > 150, "a 'flat' corner should still be quick"
