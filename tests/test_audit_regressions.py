"""One regression test per confirmed finding of the 19 September 2026 blind audit.

Each test is the audit's own assertion, ported onto this package. The number in
each name is that finding's number in the audit's report, so a failure here
points straight at the defect it was written for.

Finding 23 has no test here. Its mechanism is real - the integer encoding
cannot hold a NaN inside a lap's covered span, so one is written as a measured
zero - but across the whole stored dataset exactly one of 9,237 zero-speed
samples inside a covered span is not a car that had genuinely stopped, and
that one sits on a coverage boundary. Nothing was corrupted, and the fix would
cost a nullable column on a 631 MB dataset.
"""

from __future__ import annotations

import importlib
import math
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api.main import app
from pitwall import corners, degradation, evolution, ingest, store, strategy, transforms
from pitwall.config import PIT_LANE_OFFSET_M, POSITION_UNITS_PER_M
from pitwall.ingest import SessionKey
from pitwall.viz import charts as viz_charts

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import backfill_gaps  # noqa: E402
import build_dataset  # noqa: E402
import validate_dataset  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------
# Shared fixtures, matching the audit's
# --------------------------------------------------------------------------

def evolution_data(offset: float = 0.0, noise: float = 0.0) -> pd.DataFrame:
    """Four drivers, 60 laps, a true 0.1 s/lap slope on both compounds.

    ``offset`` gives SOFT a constant pace advantage that has nothing to do
    with degradation; ``noise`` makes the fit uncertain so a confidence band
    has something to be wide about.
    """
    rng = np.random.default_rng(42)
    rows = []
    for driver in range(4):
        for lap in range(1, 61):
            compound = "SOFT" if (lap // 10 + driver) % 2 else "HARD"
            age = int(rng.integers(1, 21))
            time = 90 + driver + 0.1 * age - lap / 60
            time += offset * (compound == "SOFT") + noise * rng.normal()
            rows.append((str(driver), compound, age, lap, time))
    return pd.DataFrame(rows, columns=["Driver", "Compound", "TyreLife",
                                       "LapNumber", "LapTime_corrected_s"])


def gap_data(missing: bool = False) -> pd.DataFrame:
    """Two drivers over three laps; B is 3 s behind by the end."""
    return pd.DataFrame({
        "Driver": ["A"] * 3 + ["B"] * 3,
        "LapNumber": [1, 2, 3] * 2,
        "LapTime_s": [90, 90, 90, 91, np.nan if missing else 91, 91],
    })


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


# --------------------------------------------------------------------------
# The pooled evolution model
# --------------------------------------------------------------------------

def test_01_compound_pace_does_not_leak_into_the_degradation_slope():
    """A constant compound advantage must not change the age slope.

    Without a C(Compound) main effect the offset had nowhere to go but the
    interaction, turning two true 0.100 s/lap slopes into 0.179 and 0.031.
    """
    result = evolution.fit_evolution(evolution_data(offset=-2))
    assert result is not None
    assert np.allclose(result["degradation"]["deg_s_per_lap"], 0.1, atol=0.01), \
        result["degradation"]


def test_01_control_identical_compound_pace_recovers_the_slope():
    result = evolution.fit_evolution(evolution_data())
    assert np.allclose(result["degradation"]["deg_s_per_lap"], 0.1, atol=0.01)


def test_02_degradation_rows_are_labelled_with_compound_names():
    """The label has to be the compound, not the patsy term that produced it."""
    result = evolution.fit_evolution(evolution_data())
    assert set(result["degradation"]["Compound"]) == {"SOFT", "HARD"}


def test_03_the_evolution_band_is_an_interval_for_the_plotted_difference():
    """The curve's first point is its own baseline, so its interval is zero wide.

    Sliding an absolute prediction interval down by the baseline ignored the
    baseline's own variance and put a +/-0.105 s band on an exact zero.
    """
    curve = evolution.fit_evolution(evolution_data(noise=0.1))["curve"]
    assert curve["evolution_s"].iloc[0] == pytest.approx(0, abs=1e-12)
    assert curve["ci_high"].iloc[0] - curve["ci_low"].iloc[0] == pytest.approx(0, abs=1e-12)
    # Away from the baseline the noisy fit is still uncertain.
    assert curve["ci_high"].iloc[-1] > curve["ci_low"].iloc[-1]


def under_supported_after_filtering() -> pd.DataFrame:
    """48 laps over four drivers that the compound filter cuts to 32.

    The surviving frame is a perfectly estimable design - four drivers, two
    compounds, tyre ages that vary independently - so the only thing that can
    refuse it is the minimum-support guard itself.
    """
    rng = np.random.default_rng(7)
    rows = []
    for driver in range(4):
        laps = ["SOFT"] * 4 + ["HARD"] * 4 + ["WET"] * 2 + ["INTERMEDIATE"] * 2
        for i, compound in enumerate(laps, start=1):
            rows.append((str(driver), compound, int(rng.integers(1, 21)), i + driver * 12))
    df = pd.DataFrame(rows, columns=["Driver", "Compound", "TyreLife", "LapNumber"])
    df["LapTime_corrected_s"] = (90 + df["Driver"].astype(int)
                                 + 0.1 * df["TyreLife"] - df["LapNumber"] / 60)
    return df


def test_20_support_thresholds_are_rechecked_after_the_compound_filter():
    """The guard ran before the filter, so it judged laps that were about to go."""
    df = under_supported_after_filtering()
    counts = df["Compound"].value_counts()
    kept = df[df["Compound"].isin(counts[counts >= 10].index)]
    # The fixture only tests what it claims to if it passes the guard on the
    # way in and fails it on the way out.
    assert len(df) >= evolution.MIN_LAPS_FOR_MODEL
    assert df["Driver"].nunique() >= evolution.MIN_DRIVERS_FOR_MODEL
    assert len(kept) < evolution.MIN_LAPS_FOR_MODEL
    assert evolution.fit_evolution(df) is None


def test_21_an_aliased_tyre_track_split_is_refused_rather_than_guessed():
    """Every tyre ageing exactly with race progress cannot be decomposed.

    OLS answers from a pseudoinverse instead of failing, which reported a
    0.92 s/lap slope with a zero-width confidence interval beside it.
    """
    df = evolution_data()
    df["Compound"] = "HARD"
    df["TyreLife"] = df["LapNumber"]
    df["LapTime_corrected_s"] = 90 + df["Driver"].astype(int) + 0.1 * df["TyreLife"]
    assert evolution.fit_evolution(df) is None


def progression(deleted: bool = False) -> pd.DataFrame:
    """B starts 5 s later than A but finishes 5 s earlier, on a faster lap."""
    return pd.DataFrame({
        "Driver": ["A", "B"],
        "Compound": ["SOFT"] * 2,
        "LapStartTime": pd.to_timedelta([0, 5], unit="s"),
        "LapTime": pd.to_timedelta([100, 90], unit="s"),
        "Deleted": [False, deleted],
    })


def test_11_session_best_is_ordered_by_when_a_lap_finished():
    assert evolution.session_best_progression(progression())["Driver"].tolist() == ["B", "A"]


def test_12_a_deleted_lap_cannot_become_the_session_record():
    assert evolution.session_best_progression(progression(True))["session_best_s"].iloc[-1] == 100


def test_12_control_a_valid_lap_still_sets_the_record():
    assert evolution.session_best_progression(progression())["session_best_s"].iloc[-1] == 90


# --------------------------------------------------------------------------
# Degradation and compound pace
# --------------------------------------------------------------------------

def summary_input(std_err: float) -> pd.DataFrame:
    return pd.DataFrame([dict(Compound="SOFT", std_err=std_err, deg_s_per_lap=0.1,
                              n_laps=10, pace_s=90, intercept_s=90, has_cliff=False)])


def test_09_an_all_unusable_pool_returns_an_empty_summary_not_a_crash():
    assert degradation.compound_summary(summary_input(0)).empty


def test_09_control_a_usable_standard_error_still_pools():
    assert len(degradation.compound_summary(summary_input(0.01))) == 1


def test_14_compound_offsets_are_read_at_a_common_tyre_age():
    """Identical tyres seen at different ages must not acquire an advantage.

    Both compounds run 90 s at age zero and degrade 0.1 s/lap; their median
    paces of 90.5 and 92 are ages 5 and 20, not a 1.5 s compound difference.
    """
    rows = pd.DataFrame({"Compound": ["SOFT", "HARD"], "median_pace_s": [90.5, 92],
                         "deg_s_per_lap": [0.1, 0.1], "intercept_s": [90, 90]})
    assert np.allclose(degradation.compound_offsets(rows)["offset_s"], 0)


def test_14_control_equal_age_equal_pace_gives_no_offset():
    rows = pd.DataFrame({"Compound": ["SOFT", "HARD"], "median_pace_s": [91, 91]})
    assert np.allclose(degradation.compound_offsets(rows)["offset_s"], 0)


# --------------------------------------------------------------------------
# Race gaps, head-to-head and pit loss
# --------------------------------------------------------------------------

def test_04_a_missing_lap_time_does_not_make_a_trailing_driver_the_leader():
    """Dropping an untimed lap made the rest look consecutive.

    On the stored races that understated three drivers' elapsed time by about
    300 s each in 2024/05_R.
    """
    out = strategy.gap_evolution(gap_data(missing=True))
    value = out.query("Driver == 'B' and LapNumber == 3")["gap_s"]
    assert value.empty or value.isna().all(), out


def test_04_control_complete_histories_give_the_right_gap():
    out = strategy.gap_evolution(gap_data())
    assert out.query("Driver == 'B' and LapNumber == 3")["gap_s"].iloc[0] == 3


def test_05_an_unscored_lap_leaves_the_running_total_unknown():
    out = strategy.head_to_head(gap_data(missing=True), "A", "B")
    assert pd.isna(out["cumulative_s"].iloc[-1]), out


def test_05_control_three_scored_laps_total_three_seconds():
    assert strategy.head_to_head(gap_data(), "A", "B")["cumulative_s"].iloc[-1] == 3


def pit_fixture(same_lap: bool = False) -> pd.DataFrame:
    """A 30 s pit loss, either split across two laps or contained in one."""
    times = [90, 120, 90] if same_lap else [90, 100, 110, 90]
    size = len(times)
    ins: list = [pd.NaT] * size
    outs: list = [pd.NaT] * size
    ins[1] = pd.Timedelta(seconds=175)
    outs[1 if same_lap else 2] = pd.Timedelta(seconds=200)
    return pd.DataFrame({"Driver": ["A"] * size, "LapNumber": np.arange(1, size + 1),
                         "LapTime": pd.to_timedelta(times, unit="s"),
                         "PitInTime": ins, "PitOutTime": outs})


def test_22_a_pit_visit_contained_in_one_lap_is_counted_once():
    """Counting it in both medians doubled it: 107.05 s against 58.60 s on
    2024/06_Sprint, where a real pit loss is near 23 s."""
    assert strategy.pit_loss(pit_fixture(same_lap=True))["pit_loss_s"] == 30


def test_22_control_a_stop_split_across_two_laps_still_totals_thirty():
    assert strategy.pit_loss(pit_fixture())["pit_loss_s"] == 30


# --------------------------------------------------------------------------
# Telemetry primitives
# --------------------------------------------------------------------------

def test_06_the_pit_lane_threshold_is_metres_not_position_units():
    """FastF1 X/Y are tenths of a metre, so 50 units is 5 m and stays."""
    tel = pd.DataFrame({"X": [0, 0], "Y": [PIT_LANE_OFFSET_M * POSITION_UNITS_PER_M / 2.4, 0]})
    assert len(transforms.trim_to_track(tel, np.array([[0, 0]]), "lead")) == 2


def test_06_control_a_point_well_off_the_track_is_still_trimmed():
    tel = pd.DataFrame({"X": [0, 0], "Y": [PIT_LANE_OFFSET_M * POSITION_UNITS_PER_M * 2, 0]})
    assert len(transforms.trim_to_track(tel, np.array([[0, 0]]), "lead")) == 1


def test_13_a_backwards_distance_jump_is_rejected():
    """The keep-mask left [0, 100, 60, 200], which np.interp cannot use."""
    tel = pd.DataFrame({"Distance": [0, 100, 50, 60, 200], "Time": [0, 1, 2, 3, 4]})
    with pytest.raises(ValueError, match="distance|monoton"):
        transforms.resample_to_distance_grid(tel)


def test_13_control_increasing_distance_resamples_to_finite_times():
    tel = pd.DataFrame({"Distance": [0, 100, 200, 300], "Time": [0, 1, 2, 3]})
    assert np.isfinite(transforms.resample_to_distance_grid(tel)["t"]).all()


def test_08_a_deleted_lap_is_rejected_by_clean_laps():
    laps = pd.DataFrame({"LapTime": pd.to_timedelta([90, 91], unit="s"),
                         "Deleted": [True, False]})
    kept, _ = transforms.clean_laps(laps)
    assert len(kept) == 1 and not kept["Deleted"].any()


def test_08_control_two_valid_laps_are_both_kept():
    laps = pd.DataFrame({"LapTime": pd.to_timedelta([90, 91], unit="s"),
                         "Deleted": [False, False]})
    assert len(transforms.clean_laps(laps)[0]) == 2


def test_10_absent_pit_columns_do_not_explain_a_lap_as_an_in_lap():
    """The optional-column fallback was False, and False.notna() is True."""
    laps = pd.DataFrame({"Driver": ["A"], "LapNumber": [2]})
    _, reasons = transforms.telemetry_coverage(laps, pd.DataFrame())
    assert reasons["reason"].iloc[0] == "telemetry missing or unusable in the source feed"


def test_10_control_explicit_null_pit_times_give_the_same_reason():
    laps = pd.DataFrame({"Driver": ["A"], "LapNumber": [2],
                         "PitInTime": [pd.NaT], "PitOutTime": [pd.NaT]})
    _, reasons = transforms.telemetry_coverage(laps, pd.DataFrame())
    assert reasons["reason"].iloc[0] == "telemetry missing or unusable in the source feed"


def _grid(duration_s: float) -> pd.DataFrame:
    return pd.DataFrame({"t": [0.0, duration_s / 2, duration_s],
                         "RelDistance": [0.0, 0.5, 1.0]})


def test_34_a_lap_longer_than_the_counter_is_refused_not_wrapped():
    """2024/08_R was red-flagged on lap 1 and wrote -2147.5 s into 17 laps."""
    with pytest.raises(ValueError, match="counter|beyond"):
        transforms.encode_grid(_grid(60_000.0))


def test_34_a_red_flag_length_lap_round_trips():
    """2400 s is past the old int32-microsecond ceiling of 2147.5 s."""
    out = transforms.decode_grid(transforms.encode_grid(_grid(2400.0)), n_points=3)
    assert np.allclose(out["t"], [0.0, 1200.0, 2400.0])


def test_34_control_an_ordinary_lap_still_round_trips():
    out = transforms.decode_grid(transforms.encode_grid(_grid(200.0)), n_points=3)
    assert np.allclose(out["t"], [0.0, 100.0, 200.0])


def _partial_pair() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Identical motion, but B has no telemetry for the first half of the lap."""
    rel = np.linspace(0.0, 1.0, 101)
    full = pd.DataFrame({"RelDistance": rel, "t": rel * 100.0,
                         "CovStart": 0.0, "CovEnd": 1.0})
    partial = full.copy()
    partial["CovStart"] = 0.5
    # A partial lap's clock starts at its own first stored sample.
    partial["t"] = np.where(rel < 0.5, np.nan, (rel - 0.5) * 100.0)
    return full, partial


def test_33_a_partial_lap_does_not_invent_a_running_advantage():
    """2024/02_R showed a +54.2 s swing between a flying lap and an out-lap."""
    full, partial = _partial_pair()
    delta = transforms.delta_time(full, partial)
    finite = delta[np.isfinite(delta)]
    assert np.allclose(finite, 0.0, atol=1e-9), finite


def test_33_control_two_identical_full_laps_have_a_zero_delta():
    full, _ = _partial_pair()
    assert np.allclose(transforms.delta_time(full, full.copy()), 0.0)


# --------------------------------------------------------------------------
# Corner segmentation
# --------------------------------------------------------------------------

def lap_for_corner(length: float) -> pd.DataFrame:
    rel = np.linspace(0, 1, 1001)
    return pd.DataFrame({"RelDistance": rel, "Distance": rel * length,
                         "t": rel * 90,
                         "Speed": np.where(np.isclose(rel, 0.7), 80, 200)})


def corner_segment() -> pd.DataFrame:
    return pd.DataFrame([dict(segment_id=0, kind="corner", label="T1",
                              start_m=600, end_m=710,
                              start_rel=0.6, end_rel=0.71, ref_length_m=1000)])


def test_07_corner_metrics_read_one_axis_for_the_window_and_the_timing():
    """A 1.5 % length difference is inside the ingestion tolerance, and worth
    81 m on a 5400 m circuit - wider than a corner window."""
    out = corners.corner_metrics(lap_for_corner(1015), corner_segment())
    assert out["v_min"].iloc[0] == 80, out


def test_07_control_a_reference_length_lap_finds_the_same_apex():
    out = corners.corner_metrics(lap_for_corner(1000), corner_segment())
    assert out["v_min"].iloc[0] == 80


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------

def _round_trip_at(size: int, monkeypatch) -> pd.DataFrame:
    """One stored lap of ``size`` points, read back the way the app reads it.

    The round trip goes through store.read_telemetry rather than calling
    decode_grid directly, because the defect was in that wiring: the decoder
    was always handed the 1000-point default instead of the stored size.
    """
    rel = np.linspace(0.0, 1.0, size)
    frame = pd.DataFrame({"Driver": ["VER"] * size, "LapNumber": [1.0] * size,
                          "t": rel * 90.0, "LapLength": 5000.0,
                          "Speed": np.full(size, 200.0)})
    encoded = pd.concat([frame[["Driver", "LapNumber", "LapLength"]],
                         transforms.encode_grid(frame)], axis=1)
    monkeypatch.setattr(store, "read_artefact", lambda key, name: encoded)
    return store.read_telemetry(SessionKey(2024, 1, "R"))


def test_17_a_custom_grid_size_is_read_from_the_stored_laps(monkeypatch):
    out = _round_trip_at(500, monkeypatch)
    assert out["RelDistance"].iloc[-1] == 1
    assert out["Distance"].iloc[-1] == 5000


def test_17_control_the_default_grid_size_round_trips(monkeypatch):
    out = _round_trip_at(1000, monkeypatch)
    assert out["RelDistance"].iloc[-1] == 1
    assert out["Distance"].iloc[-1] == 5000


# --------------------------------------------------------------------------
# HTTP boundary
# --------------------------------------------------------------------------

@pytest.mark.parametrize("value", ["nan", "inf", "-1"])
def test_15_nonfinite_fuel_parameters_are_a_client_error(client, value):
    response = client.get("/api/race-arc",
                          params={"slug": "2024/01_R", "fuel_effect": value})
    assert response.status_code == 422, response.text[:200]


def test_15_control_a_finite_fuel_effect_is_served(client):
    response = client.get("/api/race-arc",
                          params={"slug": "2024/01_R", "fuel_effect": 0.032})
    assert response.status_code == 200, response.text[:200]


def test_16_a_malformed_chart_number_is_a_client_error(client):
    response = client.get("/api/chart/undercut-chart", params={"gap_s": "oops"})
    assert response.status_code in (400, 422), response.text[:200]


def test_16_control_a_numeric_chart_parameter_is_served(client):
    response = client.get("/api/chart/undercut-chart", params={"gap_s": "1.5"})
    assert response.status_code == 200, response.text[:200]


def test_32_charts_refuse_the_corner_data_the_analysis_endpoint_refuses(client,
                                                                       monkeypatch):
    """The 409 belongs to the shared input path, not to one endpoint."""
    broken = pd.DataFrame({"Number": [1, 2], "CornerLabel": ["1", "2"],
                           "Distance": [500.0, 500.0]})
    real = api_cache_load_artefact = __import__("api.cache", fromlist=["cache"]).load_artefact

    def fake(slug, name):
        return broken if name == "corners" else real(slug, name)

    monkeypatch.setattr("api.cache.load_artefact", fake)
    monkeypatch.setattr("api.charts.cache.load_artefact", fake)
    response = client.get("/api/chart/corner-delta-bars",
                          params={"slug": "2024/01_Q", "driver1": "VER",
                                  "driver2": "LEC"})
    assert response.status_code == 409, response.text[:200]


# --------------------------------------------------------------------------
# Charts
# --------------------------------------------------------------------------

def weather_position(temperatures: list[float]) -> float:
    curve = pd.DataFrame({"progress": [0., .5, 1.], "evolution_s": [0., -.5, -1.],
                          "ci_low": [0., -.6, -1.1], "ci_high": [0., -.4, -.9]})
    weather = pd.DataFrame({"Time_s": [0., 60., 120.], "TrackTemp": temperatures})
    figure = viz_charts.evolution_with_temperature(curve, weather)
    trace = next(t for t in figure.data if t.name == "Track temp")
    return np.asarray(trace.x)[np.asarray(trace.y) == 40].item()


def test_25_a_missing_temperature_does_not_move_the_other_readings():
    assert weather_position([np.nan, 40., 39.]) == .5


def test_25_control_a_complete_series_places_the_reading_at_half():
    assert weather_position([41., 40., 39.]) == .5


def stint_bar_end(numbers: list[int]) -> float:
    laps = pd.DataFrame({"Driver": ["A"] * len(numbers), "Stint": 1,
                         "Compound": "SOFT", "LapNumber": numbers})
    figure = viz_charts.stint_chart(strategy.stint_table(laps))
    return figure.data[0].base[0] + figure.data[0].x[0]


def test_26_a_stint_bar_spans_its_laps_not_its_observed_row_count():
    """The bar ended at lap 4 while its own hover text said lap 5."""
    assert stint_bar_end([1, 2, 4, 5]) == 5


def test_26_control_a_complete_stint_ends_where_it_ends():
    assert stint_bar_end([1, 2, 3, 4, 5]) == 5


# --------------------------------------------------------------------------
# Scripts
# --------------------------------------------------------------------------

def test_18_complete_artefacts_with_no_manifest_row_are_not_skipped(monkeypatch):
    """Artefacts are written before the manifest row, so an interruption can
    leave files the manifest never learns about."""
    monkeypatch.setattr(store, "session_is_complete", lambda key: True)
    monkeypatch.setattr(store, "read_manifest", lambda: pd.DataFrame())
    monkeypatch.setattr(build_dataset.ingest, "load_session",
                        lambda key, **kw: (_ for _ in ()).throw(RuntimeError("rebuilt")))
    with pytest.raises(RuntimeError, match="rebuilt"):
        build_dataset.build_session(SessionKey(2024, 1, "R"), force=False, n_points=1000)


def test_18_control_a_session_the_manifest_knows_is_skipped(monkeypatch):
    monkeypatch.setattr(store, "session_is_complete", lambda key: True)
    monkeypatch.setattr(store, "read_manifest",
                        lambda: pd.DataFrame([{"slug": "2024/01_R"}]))
    status, meta = build_dataset.build_session(SessionKey(2024, 1, "R"),
                                               force=False, n_points=1000)
    assert status.startswith("skipped") and meta is None


def _runner_args() -> SimpleNamespace:
    return SimpleNamespace(force=False, grid_points=1000, laps_per_driver=None, pause=0)


def test_19_a_rate_limited_build_reports_the_work_it_did_not_do(monkeypatch):
    """(0, 0, 0) made main() exit zero on a run that built nothing."""
    def limited(*args, **kwargs):
        raise ingest.RateLimited("test rate limit")

    monkeypatch.setattr(build_dataset, "build_session", limited)
    ok, skipped, failed = build_dataset._run_sequential(
        [SessionKey(2024, 1, "R"), SessionKey(2024, 2, "R")], _runner_args())
    assert failed > 0, (ok, skipped, failed)


def test_19_control_a_successful_target_counts_as_built(monkeypatch):
    monkeypatch.setattr(build_dataset, "build_session", lambda *a, **k: ("ok", None))
    assert build_dataset._run_sequential([SessionKey(2024, 1, "R")],
                                         _runner_args()) == (1, 0, 0)


def test_27_a_listed_session_with_missing_artefacts_is_queued(monkeypatch):
    frame = pd.DataFrame([{"year": 2024, "round": 1, "session": "Q"}])
    monkeypatch.setattr(backfill_gaps, "expected_sessions", lambda years: frame)
    monkeypatch.setattr(store, "read_manifest", lambda: frame)
    monkeypatch.setattr(store, "session_is_complete", lambda key: False)
    assert len(backfill_gaps.find_gaps([2024], None)) == 1


def test_27_control_a_complete_listed_session_is_not_queued(monkeypatch):
    frame = pd.DataFrame([{"year": 2024, "round": 1, "session": "Q"}])
    monkeypatch.setattr(backfill_gaps, "expected_sessions", lambda years: frame)
    monkeypatch.setattr(store, "read_manifest", lambda: frame)
    monkeypatch.setattr(store, "session_is_complete", lambda key: True)
    assert backfill_gaps.find_gaps([2024], None).empty


def test_28_an_empty_schedule_can_still_be_filtered_by_session(monkeypatch):
    monkeypatch.setattr(backfill_gaps.ingest, "get_schedule",
                        lambda year: pd.DataFrame())
    monkeypatch.setattr(store, "read_manifest", lambda: pd.DataFrame())
    assert backfill_gaps.find_gaps([2099], ["Q"]).empty


class FakeFrontend:
    """Stands in for the frontend path: node_modules always looks installed."""

    def __truediv__(self, other):
        return SimpleNamespace(is_dir=lambda: True)

    def __str__(self):
        return "frontend"


class FakeCarData:
    """What FastF1 hands back from get_car_data: sized, and distance-derivable."""

    def __init__(self, frame):
        self._frame = frame

    def __len__(self):
        return len(self._frame)

    def add_distance(self):
        return self._frame


class FakeProcess:
    def __init__(self, returncode=None):
        self.returncode = returncode
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode


def _launcher(monkeypatch, fail_web: bool):
    import run_dev
    api = FakeProcess(None if fail_web else 0)
    web = FakeProcess(None)
    calls = iter([api, web])

    def popen(*args, **kwargs):
        process = next(calls)
        if fail_web and process is web:
            raise OSError("frontend launch failed")
        return process

    monkeypatch.setattr(run_dev.subprocess, "Popen", popen)
    monkeypatch.setattr(run_dev.shutil, "which", lambda name: "npm")
    monkeypatch.setattr(run_dev, "FRONTEND", FakeFrontend())
    return run_dev, api, web


def test_29_a_failed_frontend_launch_does_not_leak_the_api_process(monkeypatch):
    """A leaked uvicorn holds port 8000 and breaks the next start."""
    run_dev, api, _ = _launcher(monkeypatch, fail_web=True)
    with pytest.raises(OSError, match="frontend launch failed"):
        run_dev.main()
    assert api.terminated


def test_29_control_a_normal_shutdown_still_stops_the_frontend(monkeypatch):
    run_dev, _, web = _launcher(monkeypatch, fail_web=False)
    assert run_dev.main() == 0
    assert web.terminated


@pytest.mark.skipif(not (REPO_ROOT / "data" / "processed" / "manifest.parquet").exists(),
                    reason="needs the built dataset")
def test_30_the_validator_rejects_backwards_telemetry_time(monkeypatch):
    """Row counts and lap maxima are unchanged; only one interior time moves."""
    key = SessionKey(2024, 1, "Q")
    meta = store.read_manifest().query("slug == '2024/01_Q'").iloc[0]
    telemetry = store.read_telemetry(key).copy()
    telemetry.loc[10, "t"] = -1.0
    monkeypatch.setattr(validate_dataset.store, "read_telemetry", lambda key: telemetry)
    assert any(level == "FAIL"
               for level, _ in validate_dataset.check_session(key.slug, meta))


@pytest.mark.skipif(not (REPO_ROOT / "data" / "processed" / "manifest.parquet").exists(),
                    reason="needs the built dataset")
def test_30_control_the_stored_session_passes_the_validator():
    key = SessionKey(2024, 1, "Q")
    meta = store.read_manifest().query("slug == '2024/01_Q'").iloc[0]
    assert validate_dataset.check_session(key.slug, meta) == []


def test_24_ingestion_loads_the_messages_that_carry_the_deleted_flag():
    """FastF1 derives Deleted from race-control messages. With them off the
    column was written for every lap and was False on all 161,941 of them."""
    captured: dict = {}

    class FakeSession:
        def load(self, **kwargs):
            captured.update(kwargs)

    import pitwall.ingest as ingest_module
    original = ingest_module.fastf1.get_session
    ingest_module.fastf1.get_session = lambda *a, **k: FakeSession()
    try:
        ingest.load_session(SessionKey(2024, 1, "R"))
    finally:
        ingest_module.fastf1.get_session = original
    assert captured.get("messages") is True, captured


def _run_wrapper(tmp_path: Path, build_exit: int) -> subprocess.CompletedProcess:
    command = tmp_path / ".venv" / "Scripts" / "python.ps1"
    command.parent.mkdir(parents=True, exist_ok=True)
    command.write_text(f'Write-Output "offline build result {build_exit}"\n'
                       f"exit {build_exit}\n", encoding="utf-8")
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(REPO_ROOT / "scripts" / "resume_dataset.ps1")],
        cwd=tmp_path, capture_output=True, text=True, timeout=60)


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell wrapper")
def test_35_the_resume_wrapper_propagates_a_failed_build(tmp_path):
    """Matching only the rate-limit phrase sent every other failure down the
    success branch, which deleted the log and exited zero."""
    result = _run_wrapper(tmp_path, 1)
    assert "offline build result 1" in result.stdout, (result.stdout, result.stderr)
    assert result.returncode != 0, result.stdout


@pytest.mark.skipif(sys.platform != "win32", reason="PowerShell wrapper")
def test_35_control_a_successful_build_reports_completion(tmp_path):
    result = _run_wrapper(tmp_path, 0)
    assert result.returncode == 0, result.stderr
    assert "Finished all possible sessions!" in result.stdout


def test_31_nonfinite_position_falls_back_to_car_data():
    """stale_position_fraction answers 0.0 when it cannot tell, so a NaN
    position scored 0 % stale and was accepted as a healthy feed."""
    rows = 10
    merged = pd.DataFrame({
        "Time": pd.to_timedelta(np.arange(rows), unit="s"),
        "Speed": np.full(rows, 200.0),
        "Distance": np.arange(rows) * 50.0,
        "X": np.concatenate([[np.nan], np.arange(rows - 1, dtype=float)]),
        "Y": np.zeros(rows),
    })
    car = merged.drop(columns=["X", "Y"])

    class FakeLap:
        def get_telemetry(self):
            return merged

        def get_car_data(self):
            return FakeCarData(car)

        def get(self, key, default=None):
            return default

    _, has_position = ingest._lap_telemetry(FakeLap())
    assert has_position is False


def test_31_control_finite_position_is_kept():
    rows = 10
    merged = pd.DataFrame({
        "Time": pd.to_timedelta(np.arange(rows), unit="s"),
        "Speed": np.full(rows, 200.0),
        "Distance": np.arange(rows) * 50.0,
        "X": np.arange(rows, dtype=float) * 500.0,
        "Y": np.zeros(rows),
    })

    class FakeLap:
        def get_telemetry(self):
            return merged

        def get(self, key, default=None):
            return default

    _, has_position = ingest._lap_telemetry(FakeLap())
    assert has_position is True
