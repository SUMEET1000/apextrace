"""Tests for the distance-grid resampler, delta time, encoding and cleaning."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pitwall.transforms import (
    clean_laps,
    decode_grid,
    delta_time,
    encode_grid,
    extract_track_map,
    fuel_correct,
    resample_to_distance_grid,
)
from tests.conftest import make_lap


# ---------------------------------------------------------------- resampling

def test_grid_has_exact_shape(raw_lap):
    grid = resample_to_distance_grid(raw_lap, n_points=500)
    assert len(grid) == 500


def test_grid_distance_is_strictly_monotonic(raw_lap):
    grid = resample_to_distance_grid(raw_lap, n_points=1000)
    assert np.all(np.diff(grid["Distance"].to_numpy()) > 0)
    assert np.all(np.diff(grid["t"].to_numpy()) >= 0)


def test_grid_endpoints_are_anchored(raw_lap):
    grid = resample_to_distance_grid(raw_lap, n_points=1000)
    assert grid["RelDistance"].iloc[0] == pytest.approx(0.0)
    assert grid["RelDistance"].iloc[-1] == pytest.approx(1.0)
    assert grid["Distance"].iloc[0] == pytest.approx(0.0)
    # Lap length is preserved by the resampling.
    assert grid["Distance"].iloc[-1] == pytest.approx(
        raw_lap["Distance"].iloc[-1], rel=1e-4
    )


def test_grid_preserves_lap_time(raw_lap):
    grid = resample_to_distance_grid(raw_lap, n_points=1000)
    expected = raw_lap["Time"].dt.total_seconds().iloc[-1]
    assert grid["t"].iloc[-1] == pytest.approx(expected, rel=1e-4)


def test_discrete_channels_take_only_observed_values(raw_lap):
    """Gears must never be invented by interpolation."""
    grid = resample_to_distance_grid(raw_lap, n_points=1000)
    assert set(grid["nGear"].unique()).issubset(set(raw_lap["nGear"].unique()))
    assert grid["Brake"].dtype == bool


def test_resampler_rejects_unusable_input():
    with pytest.raises(ValueError):
        resample_to_distance_grid(pd.DataFrame({"Distance": [0.0], "Time": [pd.Timedelta(0)]}))
    with pytest.raises(ValueError):
        resample_to_distance_grid(pd.DataFrame({"Speed": [1, 2, 3]}))


def test_non_monotonic_distance_is_tolerated():
    """Position data occasionally stalls or steps backwards."""
    lap = make_lap(n_raw=300)
    d = lap["Distance"].to_numpy()
    d[100] = d[99]        # duplicate sample
    d[150] = d[149] - 5   # backwards step
    lap["Distance"] = d
    grid = resample_to_distance_grid(lap, n_points=400)
    assert len(grid) == 400
    assert np.all(np.diff(grid["Distance"].to_numpy()) > 0)


# ---------------------------------------------------------------- delta time

def test_delta_time_against_self_is_zero(raw_lap):
    grid = resample_to_distance_grid(raw_lap, n_points=1000)
    assert np.allclose(delta_time(grid, grid), 0.0)


def test_delta_time_final_value_equals_lap_time_difference():
    """The defining property: the curve must end at the lap-time gap."""
    fast = resample_to_distance_grid(make_lap(speed_scale=1.00, seed=1))
    slow = resample_to_distance_grid(make_lap(speed_scale=0.95, seed=1))
    delta = delta_time(fast, slow)
    lap_time_gap = slow["t"].iloc[-1] - fast["t"].iloc[-1]
    assert delta[-1] == pytest.approx(lap_time_gap, abs=1e-3)
    assert delta[-1] > 0  # the slower lap is behind


def test_delta_time_sign_convention():
    """Positive delta means lap B is behind lap A."""
    fast = resample_to_distance_grid(make_lap(speed_scale=1.00, seed=2))
    slow = resample_to_distance_grid(make_lap(speed_scale=0.90, seed=2))
    assert delta_time(fast, slow)[-1] > 0
    assert delta_time(slow, fast)[-1] < 0


def test_delta_time_rejects_mismatched_grids(raw_lap):
    a = resample_to_distance_grid(raw_lap, n_points=500)
    b = resample_to_distance_grid(raw_lap, n_points=1000)
    with pytest.raises(ValueError, match="different grids"):
        delta_time(a, b)


# ------------------------------------------------------------------ encoding

def test_encode_decode_round_trip_within_quantisation(raw_lap):
    grid = resample_to_distance_grid(raw_lap, n_points=1000)
    encoded = encode_grid(grid)
    restored = decode_grid(
        pd.concat([grid[["LapLength"]].reset_index(drop=True), encoded], axis=1),
        n_points=1000,
    )
    assert np.allclose(restored["t"], grid["t"], atol=1e-5)
    assert np.allclose(restored["Speed"], grid["Speed"], atol=0.05)   # 0.1 km/h steps
    assert np.allclose(restored["Throttle"], grid["Throttle"], atol=0.5)
    assert np.allclose(restored["RPM"], grid["RPM"], atol=5.0)        # 10 rpm steps
    assert np.allclose(restored["Distance"], grid["Distance"], atol=0.1)


def test_encoding_preserves_delta_time(raw_lap):
    """Quantisation must not disturb the headline metric."""
    a = resample_to_distance_grid(make_lap(speed_scale=1.00, seed=3))
    b = resample_to_distance_grid(make_lap(speed_scale=0.97, seed=3))
    exact = delta_time(a, b)

    def round_trip(g):
        return decode_grid(
            pd.concat([g[["LapLength"]].reset_index(drop=True), encode_grid(g)], axis=1),
            n_points=len(g),
        )

    approx = delta_time(round_trip(a), round_trip(b))
    assert np.max(np.abs(exact - approx)) < 1e-4


def test_track_map_rotation_preserves_shape(raw_lap):
    grid = resample_to_distance_grid(raw_lap, n_points=200)
    plain = extract_track_map(grid, rotation=0.0)
    turned = extract_track_map(grid, rotation=90.0)
    # Rotation is rigid: distances from the origin are unchanged.
    r0 = np.hypot(plain["X"], plain["Y"])
    r1 = np.hypot(turned["X"], turned["Y"])
    assert np.allclose(r0, r1, atol=1e-3)
    assert not np.allclose(plain["X"], turned["X"], atol=1.0)


# ------------------------------------------------------------ lap cleaning

def _lap_table() -> pd.DataFrame:
    """Eight laps with one of each defect, for exact rejection accounting."""
    return pd.DataFrame({
        "Driver": ["VER"] * 8,
        "Stint": [1.0] * 8,
        "LapNumber": range(1, 9),
        "LapTime": pd.to_timedelta(
            [90.0, 90.2, 90.1, 90.3, 90.4, 120.0, 90.2, np.nan], unit="s"
        ),
        "IsAccurate": [True, True, False, True, True, True, True, True],
        "PitInTime": pd.to_timedelta(
            [None] * 3 + [5.0] + [None] * 4, unit="s"),
        "PitOutTime": pd.to_timedelta(
            [None] * 4 + [5.0] + [None] * 3, unit="s"),
        "TrackStatus": ["1", "1", "1", "1", "1", "1", "4", "1"],
    })


def test_clean_laps_rejects_each_defect_once():
    kept, rejections = clean_laps(_lap_table())
    reasons = dict(zip(rejections["reason"], rejections["count"]))
    assert reasons["no lap time"] == 1
    assert reasons["failed IsAccurate"] == 1
    assert reasons["in-lap (pit entry)"] == 1
    assert reasons["out-lap (pit exit)"] == 1
    assert reasons["track not clear (yellow/SC/VSC)"] == 1
    assert reasons["stint outlier (traffic / mistake)"] == 1
    # Laps 1 and 2 are the only clean ones.
    assert sorted(kept["LapNumber"]) == [1, 2]


def test_clean_laps_reports_every_rejection():
    laps = _lap_table()
    kept, rejections = clean_laps(laps)
    assert len(kept) + rejections["count"].sum() == len(laps)


def test_clean_laps_filters_are_individually_optional():
    kept, _ = clean_laps(_lap_table(), require_clear_track=False)
    assert 7 in set(kept["LapNumber"])  # the yellow-flag lap survives


# ------------------------------------------------------------ fuel correction

def test_fuel_correction_makes_a_constant_pace_stint_flat():
    """A driver lapping at truly constant pace looks like they are speeding
    up, because the car is getting lighter. Correction must remove that."""
    total_laps = 50
    effect, fuel = 0.03, 100.0
    kg_per_lap = fuel / total_laps
    lap_numbers = np.arange(1, total_laps + 1)
    # A heavy car is a slow car: lap 1 carries the full fuel load and is the
    # slowest, and times fall as fuel burns off toward the flag.
    raw = 90.0 + effect * kg_per_lap * (total_laps - lap_numbers)
    assert raw[0] > raw[-1]
    laps = pd.DataFrame({"LapNumber": lap_numbers,
                         "LapTime": pd.to_timedelta(raw, unit="s")})
    corrected = fuel_correct(laps, total_laps=total_laps, race_fuel_kg=fuel,
                             fuel_effect_s_per_kg=effect)
    assert corrected.std() == pytest.approx(0.0, abs=1e-9)
    assert corrected.mean() == pytest.approx(90.0, abs=1e-9)


def test_fuel_correction_is_zero_on_the_final_lap():
    laps = pd.DataFrame({"LapNumber": [50], "LapTime": pd.to_timedelta([90.0], unit="s")})
    corrected = fuel_correct(laps, total_laps=50, race_fuel_kg=100.0,
                             fuel_effect_s_per_kg=0.03)
    assert corrected.iloc[0] == pytest.approx(90.0)


def test_fuel_correction_rejects_bad_total_laps():
    laps = pd.DataFrame({"LapNumber": [1], "LapTime": pd.to_timedelta([90.0], unit="s")})
    with pytest.raises(ValueError):
        fuel_correct(laps, total_laps=0, race_fuel_kg=100.0, fuel_effect_s_per_kg=0.03)
