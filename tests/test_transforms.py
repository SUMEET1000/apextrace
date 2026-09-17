"""Tests for the distance-grid resampler, delta time, encoding and cleaning."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pitwall.config import (
    MAX_LAP_LENGTH_DEVIATION,
    MAX_STALE_POSITION_FRACTION,
    MAX_START_LINE_OFFSET,
    POSITION_UNITS_PER_M,
)
from pitwall.transforms import (
    align_corner_distances,
    clean_laps,
    decode_grid,
    delta_time,
    distance_from_position,
    encode_grid,
    extract_track_map,
    fuel_correct,
    resample_to_distance_grid,
    stale_position_fraction,
    start_line_offset,
    telemetry_coverage,
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


# ------------------------------------------------- distance from position

def _lap_with_consistent_position(lap_length: float = 5000.0, **kw) -> pd.DataFrame:
    """A lap whose X/Y trace really is ``lap_length`` metres long.

    ``make_lap`` draws a unit-ish circle that is not scaled to its own
    ``Distance``, which is fine for every other test but meaningless for an
    arc-length measurement. Here the circle's circumference is pinned to the
    lap length (in position units) so the two agree.
    """
    lap = make_lap(lap_length=lap_length, **kw)
    radius = lap_length * POSITION_UNITS_PER_M / (2 * np.pi)
    theta = 2 * np.pi * lap["Distance"].to_numpy() / lap_length
    lap["X"] = np.cos(theta) * radius
    lap["Y"] = np.sin(theta) * radius
    return lap


def test_position_distance_measures_the_real_lap_length():
    lap = _lap_with_consistent_position(lap_length=5451.0)
    out = distance_from_position(lap)
    # Chord-vs-arc error over ~900 samples is well under a metre.
    assert out["Distance"].iloc[-1] == pytest.approx(5451.0, rel=1e-3)


def test_position_distance_repairs_a_corrupt_speed_integral():
    """The reason this function exists.

    FastF1 derives ``Distance`` by integrating Speed over time, so a defective
    speed channel drags the whole distance axis with it and the error never
    recovers. That is what put 2026/02_Sprint's laps 10-20% off a 5451 m
    circuit and got 69% of them rejected by MAX_LAP_LENGTH_DEVIATION. The car
    drove a normal lap; only the integral was wrong, and the position trace
    still knows it.
    """
    lap = _lap_with_consistent_position(lap_length=5451.0)
    lap["Distance"] = lap["Distance"] * 1.18  # a badly mis-scaled integral

    corrupt = resample_to_distance_grid(lap, n_points=200)["LapLength"].iloc[0]
    assert abs(corrupt / 5451.0 - 1) > MAX_LAP_LENGTH_DEVIATION  # would be dropped

    repaired = resample_to_distance_grid(
        distance_from_position(lap), n_points=200)["LapLength"].iloc[0]
    assert abs(repaired / 5451.0 - 1) < MAX_LAP_LENGTH_DEVIATION  # is kept


def test_position_distance_falls_back_when_there_is_no_position_data():
    """Laps rescued from car data alone have no X/Y; the speed integral stands."""
    lap = _lap_with_consistent_position().drop(columns=["X", "Y", "Z"])
    out = distance_from_position(lap)
    pd.testing.assert_series_equal(out["Distance"], lap["Distance"])


# ------------------------------------------------------- stale position feed

def _freeze_position(lap: pd.DataFrame, every: int = 3) -> pd.DataFrame:
    """Hold X/Y still for ``every - 1`` samples out of every ``every``.

    This is what the Hungary 2026 feed did: it kept emitting on schedule while
    re-sending the coordinate it already had, then teleported to catch up.
    """
    out = lap.copy()
    idx = np.arange(len(out)) // every * every
    out["X"] = out["X"].to_numpy()[idx]
    out["Y"] = out["Y"].to_numpy()[idx]
    return out


def test_a_healthy_position_trace_is_not_stale():
    assert stale_position_fraction(_lap_with_consistent_position()) == 0.0


def test_a_frozen_position_trace_is_detected():
    frozen = _freeze_position(_lap_with_consistent_position(), every=3)
    assert stale_position_fraction(frozen) > MAX_STALE_POSITION_FRACTION


def test_a_stopped_car_is_not_stale():
    """A car that is genuinely stationary reports the same place correctly.

    The check is against the speed channel, not against the clock, precisely
    so a spin or a red-flag crawl cannot be mistaken for a dead feed.
    """
    lap = _lap_with_consistent_position()
    stopped = lap.iloc[:50].copy()
    stopped["Speed"] = 0.0
    stopped["X"] = lap["X"].iloc[0]
    stopped["Y"] = lap["Y"].iloc[0]
    assert stale_position_fraction(stopped) == 0.0


def test_a_frozen_trace_measures_the_feed_rather_than_the_lap():
    """Why a stale trace is refused rather than measured.

    Nothing about a frozen trace raises: X/Y is populated, the timestamps
    advance, and the arc length comes out as a perfectly plausible number.
    What gives it away is that it is the *same* number for laps that were not
    the same - at 2026/11_R the arc length landed on 3649.8 m for hundreds of
    consecutive laps, which is a cached path being replayed rather than cars
    driving. A wrong-but-consistent length is worse than a noisy one, because
    it survives every guard MAX_LAP_LENGTH_DEVIATION applies: once the frozen
    laps are the majority they *are* the session median, and the handful of
    healthy laps become the anomaly that gets rejected.
    """
    short = _lap_with_consistent_position(lap_length=4381.0)
    long = _lap_with_consistent_position(lap_length=5451.0)

    # Both laps' feeds freeze onto the same replayed path.
    for lap in (short, long):
        lap["X"] = short["X"].to_numpy()[::4].repeat(4)[:len(lap)]
        lap["Y"] = short["Y"].to_numpy()[::4].repeat(4)[:len(lap)]

    assert stale_position_fraction(short) > MAX_STALE_POSITION_FRACTION
    assert stale_position_fraction(long) > MAX_STALE_POSITION_FRACTION
    measured = [distance_from_position(lap)["Distance"].iloc[-1]
                for lap in (short, long)]
    assert measured[0] == pytest.approx(measured[1])          # indistinguishable
    assert abs(measured[1] / 5451.0 - 1) > MAX_LAP_LENGTH_DEVIATION  # and wrong


# --------------------------------------------------- start/finish anchoring

def _gridded(lap: pd.DataFrame, n_points: int = 1000) -> np.ndarray:
    return resample_to_distance_grid(lap, n_points=n_points)["Speed"].to_numpy()


def test_a_correctly_anchored_lap_has_no_start_line_offset():
    ref = _gridded(make_lap(seed=1))
    other = _gridded(make_lap(seed=2))
    assert abs(start_line_offset(other, ref)) <= MAX_START_LINE_OFFSET


def test_a_slower_lap_is_still_anchored_at_zero():
    """Pace must not read as position - braking points carry the signal."""
    ref = _gridded(make_lap(seed=1))
    slow = _gridded(make_lap(seed=1, speed_scale=0.85))
    assert abs(start_line_offset(slow, ref)) <= MAX_START_LINE_OFFSET


@pytest.mark.parametrize("fraction", [0.12, 0.35, -0.2])
def test_a_rotated_lap_is_measured_at_its_true_offset(fraction):
    """The 2026/11_R failure: a complete, normal lap that starts elsewhere.

    Its duration is right, its length is right and its speed trace is a real
    lap, so every other guard passes. Only the phase gives it away.
    """
    ref = _gridded(make_lap(seed=1))
    rotated = np.roll(ref, int(round(fraction * len(ref))))
    assert start_line_offset(rotated, ref) == pytest.approx(fraction, abs=0.01)
    assert abs(start_line_offset(rotated, ref)) > MAX_START_LINE_OFFSET


# ------------------------------------------------------ corner marker anchoring

def _circular_track_map(lap_length: float = 4381.0, n: int = 1000) -> pd.DataFrame:
    rel = np.linspace(0.0, 1.0, n)
    radius = lap_length * POSITION_UNITS_PER_M / (2 * np.pi)
    theta = 2 * np.pi * rel
    return pd.DataFrame({
        "RelDistance": rel,
        "Distance": rel * lap_length,
        "X": np.cos(theta) * radius,
        "Y": np.sin(theta) * radius,
    })


def _markers_at(distances, lap_length: float = 4381.0) -> pd.DataFrame:
    radius = lap_length * POSITION_UNITS_PER_M / (2 * np.pi)
    theta = 2 * np.pi * np.asarray(distances, dtype=float) / lap_length
    return pd.DataFrame({
        "Number": np.arange(1, len(theta) + 1),
        "CornerLabel": [str(i) for i in range(1, len(theta) + 1)],
        "Distance": np.full(len(theta), np.nan),  # what FastF1 got wrong
        "X": np.cos(theta) * radius,
        "Y": np.sin(theta) * radius,
    })


def test_corner_markers_are_re_measured_against_the_track_map():
    truth = [600.0, 1200.0, 2500.0, 3900.0]
    aligned = align_corner_distances(_markers_at(truth), _circular_track_map())
    assert aligned["Distance"].to_numpy() == pytest.approx(truth, abs=10.0)


def test_corner_alignment_undoes_the_track_map_rotation():
    """The map is stored rotated to broadcast orientation; markers are not."""
    truth = [600.0, 1200.0, 2500.0, 3900.0]
    rotation = 40.0
    track_map = extract_track_map(_circular_track_map(), rotation=rotation)
    aligned = align_corner_distances(_markers_at(truth), track_map, rotation)
    assert aligned["Distance"].to_numpy() == pytest.approx(truth, abs=10.0)


def test_corner_alignment_is_a_no_op_without_a_track_map():
    corners = _markers_at([600.0])
    corners["Distance"] = [123.0]
    out = align_corner_distances(corners, pd.DataFrame())
    pd.testing.assert_frame_equal(out, corners)


def _stadium_track_map(straight: float = 1500.0, gap: float = 120.0,
                       n: int = 1000) -> pd.DataFrame:
    """A circuit whose two straights run ``gap`` metres apart.

    Baku's 2.2 km main straight passes within metres of the T2-T3 section, so
    a marker on one can be physically nearer the other. A circle cannot
    reproduce that; this can.
    """
    r = gap / 2
    peri = 2 * straight + 2 * np.pi * r
    s = np.linspace(0.0, peri, n, endpoint=False)
    x = np.empty(n)
    y = np.empty(n)
    for i, t in enumerate(s):
        if t < straight:                                  # bottom straight, +x
            x[i], y[i] = t, -r
        elif t < straight + np.pi * r:                    # right hairpin
            a = (t - straight) / r
            x[i], y[i] = straight + r * np.sin(a), -r * np.cos(a)
        elif t < 2 * straight + np.pi * r:                # top straight, -x
            u = t - straight - np.pi * r
            x[i], y[i] = straight - u, r
        else:                                             # left hairpin
            a = (t - 2 * straight - np.pi * r) / r
            x[i], y[i] = -r * np.sin(a), r * np.cos(a)
    return pd.DataFrame({
        "RelDistance": s / peri,
        "Distance": s,
        "X": x * POSITION_UNITS_PER_M,
        "Y": y * POSITION_UNITS_PER_M,
    })


def test_a_marker_nearer_the_wrong_straight_is_placed_by_its_corner_number():
    """Baku's T20: the nearest map point is on the parallel straight.

    Snapping each marker independently puts T20 at 2176 m in 2025/17_Q, before
    corners it comes after. Corner *numbering* is lap order, so ordering is the
    information that resolves which of two adjacent passes a marker is on.
    """
    track_map = _stadium_track_map()
    straight, r = 1500.0, 60.0
    third_true = 2600.0
    u = third_true - straight - np.pi * r
    markers = pd.DataFrame({
        "Number": [1, 2, 3],
        "CornerLabel": ["1", "2", "3"],
        "Distance": [np.nan] * 3,
        # first two sit on the bottom straight; the third belongs on the top
        # straight but is pulled halfway across, so its nearest map point is
        # on the bottom one - at a distance *earlier* than corner 2.
        "X": np.array([300.0, 1000.0, straight - u]) * POSITION_UNITS_PER_M,
        "Y": np.array([-r, -r, -r / 2]) * POSITION_UNITS_PER_M,
    })

    aligned = align_corner_distances(markers, track_map)
    got = aligned["Distance"].to_numpy()

    assert got[0] == pytest.approx(300.0, abs=15.0)
    assert got[1] == pytest.approx(1000.0, abs=15.0)
    assert got[2] == pytest.approx(third_true, abs=15.0)
    assert np.all(np.diff(got) > 0)


def test_corner_alignment_orders_by_corner_number_not_row_order():
    """A corners frame that arrives out of order still aligns in lap order."""
    truth = [600.0, 1200.0, 2500.0, 3900.0]
    markers = _markers_at(truth).iloc[::-1].reset_index(drop=True)
    aligned = align_corner_distances(markers, _circular_track_map())
    by_number = aligned.sort_values("Number")["Distance"].to_numpy()
    assert by_number == pytest.approx(truth, abs=10.0)


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


# -------------------------------------------------------- telemetry coverage

def _availability_tables() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Six driven laps against a telemetry artefact holding only two.

    Lap 3 is an in-lap, lap 4 has no lap time, lap 5 was deleted, and lap 6 is
    a plain flying lap with no stored trace - the case that means the source
    telemetry itself was unusable.
    """
    laps = pd.DataFrame({
        "Driver": ["VER"] * 6,
        "LapNumber": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        "LapTime": pd.to_timedelta([95.0, 90.0, 99.0, np.nan, 90.5, 90.4], unit="s"),
        "PitInTime": pd.to_timedelta([None, None, 5.0, None, None, None], unit="s"),
        "PitOutTime": pd.to_timedelta([None] * 6, unit="s"),
        "Deleted": [False, False, False, False, True, False],
    })
    stored = pd.DataFrame({"Driver": ["VER", "VER"], "LapNumber": [1.0, 2.0]})
    return laps, stored


def test_coverage_attributes_every_absent_lap_to_exactly_one_reason():
    """The counts must reconcile: a selector offering fewer laps than were
    driven has to account for the whole shortfall, or the audit is decorative."""
    laps, stored = _availability_tables()
    summary, rejections = telemetry_coverage(laps, stored)

    assert summary["n_laps"] == 6
    assert summary["n_stored"] == 2
    assert summary["n_missing"] == 4
    assert rejections["count"].sum() == summary["n_missing"]

    reasons = dict(zip(rejections["reason"], rejections["count"]))
    assert reasons["no lap time recorded (retired or incomplete lap)"] == 1
    assert reasons["deleted lap"] == 1
    assert reasons["telemetry missing or unusable in the source feed"] == 1
    assert sum(v for k, v in reasons.items() if k.startswith("in-lap")) == 1


def test_coverage_reports_nothing_to_explain_when_every_lap_is_stored():
    laps, _ = _availability_tables()
    stored = laps[["Driver", "LapNumber"]]
    summary, rejections = telemetry_coverage(laps, stored)
    assert summary["coverage"] == 1.0
    assert rejections.empty


def test_coverage_distinguishes_a_missing_trace_from_one_never_requested():
    """Qualifying keeps only a driver's fastest few laps, so an absent lap there
    is a stated choice. A race asks for every lap, so the same absence means the
    source feed failed. Reporting both the same way would blame the wrong thing."""
    laps, stored = _availability_tables()
    _, race = telemetry_coverage(laps, stored, stores_all_laps=True)
    _, quali = telemetry_coverage(laps, stored, stores_all_laps=False)

    assert "telemetry missing or unusable in the source feed" in set(race["reason"])
    assert "not among the fastest laps kept for this session type" in set(quali["reason"])
    # Same shortfall either way - only the explanation changes.
    assert race["count"].sum() == quali["count"].sum()


def test_coverage_survives_a_session_with_no_stored_telemetry_at_all():
    laps, _ = _availability_tables()
    summary, rejections = telemetry_coverage(laps, pd.DataFrame())
    assert summary["n_stored"] == 0
    assert summary["coverage"] == 0.0
    assert rejections["count"].sum() == 6


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
