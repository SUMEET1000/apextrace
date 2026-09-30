"""Chart-data responses and the existing figures must plot the same observations."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api.charts import BUILDERS, _plain
from api.main import app
from pitwall.viz.charts import box_statistics, lap_by_lap_data
from pitwall.viz.traces import trace_panel_data

client = TestClient(app)
Q = "2024/12_Q"
R = "2024/01_R"
DRIVERS = {"driver1": "RUS", "driver2": "VER"}
CASES = {
    "speed-delta-map": (Q, DRIVERS),
    "speed-map": (Q, {**DRIVERS, "which": "a"}),
    "trace-panel": (Q, DRIVERS),
    "corner-delta-bars": (Q, DRIVERS),
    "lap-by-lap": (Q, DRIVERS),
    "session-best": (Q, {}),
    "degradation-scatter": (R, {}),
    "degradation-bars": (R, {}),
    "evolution-curve": (R, {}),
    "evolution-temperature": (R, {}),
    "stint-chart": (R, {}),
    "race-pace-box": (R, {}),
    "gap-chart": (R, {"drivers": "VER,PER,SAI,NOR,LEC,RUS,HAM,PIA,HUL,ALO,"
                                 "GAS,STR,SAR,TSU,RIC,ZHO,MAG,ALB,OCO,BOT"}),
    "position-chart": (R, {}),
    "undercut-chart": ("", {"gap_s": "1.5", "advantage": "0.8", "deg_rate": "0.12"}),
}


def same(actual, expected):
    if isinstance(actual, np.ndarray):
        actual = actual.tolist()
    if isinstance(actual, (list, tuple)):
        assert len(actual) == len(expected)
        for left, right in zip(actual, expected):
            same(left, right)
    elif expected is None:
        assert actual is None or (isinstance(actual, (int, float)) and math.isnan(actual))
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        assert float(actual) == pytest.approx(float(expected), abs=1e-7)
    else:
        assert actual == expected


def test_registry_is_exhaustive():
    assert set(CASES) == set(BUILDERS)
    assert len(CASES) == 15


@pytest.mark.parametrize("chart_id", sorted(CASES))
def test_data_twin_matches_figure(chart_id):
    slug, params = CASES[chart_id]
    if slug:
        params = {"slug": slug, **params}
        manifest = client.get("/api/manifest").json()
        if slug not in {s["slug"] for s in manifest["sessions"]}:
            pytest.skip(f"{slug} is not packaged")
    response = client.get(f"/api/chart-data/{chart_id}", params=params)
    assert response.status_code == 200, response.text[:300]
    data = response.json()
    assert data["chart_id"] == chart_id
    assert data["finding"] and data["x_unit"]
    figure = BUILDERS[chart_id](slug, params)
    traces = figure.data

    if chart_id in {"speed-delta-map", "speed-map"}:
        sectors = data["sectors"]
        for trace, sector in zip(traces[1:1 + len(sectors)], sectors):
            same(trace.x, sector["x"])
            same(trace.y, sector["y"])
            assert trace.line.color == sector["colour"]
        hover = traces[1 + len(sectors)]
        mask = data["readable"] if chart_id == "speed-delta-map" else data["known"]
        same(hover.x, [x for x, keep in zip(data["x"], mask) if keep])
        same(hover.y, [y for y, keep in zip(data["y"], mask) if keep])
        values = data["rate"] if chart_id == "speed-delta-map" else data["speed"]
        same(hover.marker.color, [v for v, keep in zip(values, mask) if keep])
    elif chart_id == "trace-panel":
        i = 0
        for driver in data["drivers"]:
            for field in ("speed", "throttle", "brake", "gear"):
                same(traces[i].x, driver["distance"])
                same(traces[i].y, driver[field])
                i += 1
        same(traces[i].y, data["delta"])
    elif chart_id == "corner-delta-bars":
        same(traces[0].x, data["labels"])
        same(traces[0].y, data["delta_s"])
    elif chart_id == "lap-by-lap":
        for row in data["lap_times"]:
            trace = next(t for t in traces if t.name == row["driver"])
            same(trace.x, row["lap"])
            same(trace.y, row["time_s"])
            if row["pit_lap"]:
                pit = next(t for t in traces if t.name == row["driver"] + " pit")
                same(pit.x, row["pit_lap"])
                same(pit.y, row["pit_time_s"])
        delta = next(t for t in traces if t.name == "Per-lap delta")
        total = next(t for t in traces if t.name == "Cumulative")
        same(delta.x, data["delta"]["lap"])
        same(delta.y, data["delta"]["seconds"])
        same(total.x, data["cumulative"]["lap"])
        same(total.y, data["cumulative"]["seconds"])
    elif chart_id == "degradation-scatter":
        i = 0
        for panel in data["panels"]:
            same(traces[i].x, panel["age"])
            same(traces[i].y, panel["lap_time_s"])
            i += 1
            if panel["fit"]:
                same(traces[i].x, panel["fit"]["age"])
                same(traces[i].y, panel["fit"]["lap_time_s"])
                i += 1
        assert i == len(traces)
    elif chart_id == "degradation-bars":
        same(traces[0].x, data["compounds"])
        same(traces[0].y, data["rate"])
        same(traces[0].error_y.array,
             [hi - rate for hi, rate in zip(data["upper"], data["rate"])])
        same(traces[0].error_y.arrayminus,
             [rate - lo for rate, lo in zip(data["rate"], data["lower"])])
    elif chart_id == "session-best":
        same(traces[0].x, data["minutes"])
        same(traces[0].y, data["lap_time_s"])
        same(traces[1].x, data["minutes"])
        same(traces[1].y, data["best_s"])
    elif chart_id in {"evolution-curve", "evolution-temperature"}:
        same(traces[0].x, data["progress"] + list(reversed(data["progress"])))
        same(traces[0].y, data["upper"] + list(reversed(data["lower"])))
        same(traces[1].x, data["progress"])
        same(traces[1].y, data["evolution_s"])
        if chart_id == "evolution-curve" and data["naive"]:
            same(traces[2].x, data["naive"]["progress"])
            same(traces[2].y, data["naive"]["evolution_s"])
        if chart_id == "evolution-temperature" and data["temperature"]:
            same(traces[2].x, data["temperature"]["progress"])
            same(traces[2].y, data["temperature"]["celsius"])
    elif chart_id == "stint-chart":
        assert len(traces) == len(data["stints"])
        for trace, row in zip(traces, data["stints"]):
            same(trace.x, [row["extent"]])
            same(trace.base, [row["start_lap"] - 1])
            same(trace.y, [row["driver"]])
    elif chart_id == "race-pace-box":
        assert len(traces) == len(data["boxes"])
        for trace, box in zip(traces, data["boxes"]):
            assert trace.name == box["driver"]
            same(trace.y, box["samples"])
    elif chart_id in {"gap-chart", "position-chart"}:
        if chart_id == "gap-chart":
            assert [row["driver"] for row in data["series"]] == params["drivers"].split(",")
        assert len(traces) == len(data["series"])
        for trace, row in zip(traces, data["series"]):
            same(trace.x, row["lap"])
            same(trace.y, row["gap_s" if chart_id == "gap-chart" else "position"])
        assert data["y_direction"] == "reversed"
    else:
        same(traces[0].x, data["laps"])
        same(traces[0].y, data["gain_s"])


@pytest.mark.parametrize(("samples", "q1", "median", "q3", "lo", "hi", "outliers"), [
    ([1, 2, 3, 4, 5, 6, 7], 2.25, 4, 5.75, 1, 7, []),
    ([1, 2, 3, 4, 5, 6], 2, 3.5, 5, 1, 6, []),
    ([1, 2, 3], 1.25, 2, 2.75, 1, 3, []),
    ([1, 2, 3, 4, 5, 6, 7, 8, 9, 100], 3, 5.5, 8, 1, 9, [100]),
])
def test_box_statistics_are_hazen_with_1_5_iqr_whiskers(
        samples, q1, median, q3, lo, hi, outliers):
    box = box_statistics(samples)
    assert (box["q1"], box["median"], box["q3"], box["lo"], box["hi"]) == (
        q1, median, q3, lo, hi)
    same(box["outliers"], outliers)


def test_missing_discrete_telemetry_stays_null():
    lap = pd.DataFrame({"Distance": [0.0, 1.0, 2.0],
                        "Speed": [100.0, np.nan, 120.0],
                        "Throttle": [80.0, 80.0, 90.0],
                        "Brake": [False, True, False], "nGear": [3, 3, 4]})
    segments = pd.DataFrame(columns=["kind", "apex_m", "label"])
    data = _plain(trace_panel_data(lap, None, segments, name_a="A"))
    assert data["drivers"][0]["speed"][1] is None
    assert data["drivers"][0]["brake"][1] is None
    assert data["drivers"][0]["gear"][1] is None


def test_fixed_findings():
    q = client.get("/api/chart-data/corner-delta-bars",
                   params={"slug": Q, **DRIVERS})
    monza = client.get("/api/chart-data/corner-delta-bars",
                       params={"slug": "2024/16_R", "driver1": "LEC", "driver2": "PIA",
                               "lap1": 2, "lap2": 2})
    r = client.get("/api/chart-data/degradation-bars", params={"slug": R})
    evolution = client.get("/api/chart-data/evolution-curve", params={"slug": R})
    assert q.status_code == monza.status_code == r.status_code == evolution.status_code == 200
    assert q.json()["finding"] == "Russell gained 0.326 s in the corners against VER."
    assert monza.json()["finding"] == "Piastri gained 0.537 s in the corners against LEC."
    assert evolution.json()["finding"] == (
        "The adjusted track estimate ends 0.372 s faster than at the first fitted point.")
    assert r.json()["finding"] == "SOFT tyres lose 0.116 s per lap on average."


def test_qualifying_lap_finding_uses_comparable_pairs():
    response = client.get("/api/chart-data/lap-by-lap", params={"slug": Q, **DRIVERS})
    assert response.status_code == 200
    data = response.json()
    assert data["finding"] == (
        f"{len(data['delta']['lap'])} comparable lap time pairs are available for RUS and VER.")
    assert "nan" not in data["finding"].lower()


def test_running_gap_finding_does_not_claim_a_race_finish():
    rows = pd.DataFrame({"LapNumber": [1, 2, 3], "LapTime_s_a": [90, 90, np.nan],
                         "LapTime_s_b": [91, 88, 89], "delta_s": [1, -2, np.nan],
                         "cumulative_s": [1, -1, np.nan]})
    assert lap_by_lap_data(rows, name_a="A", name_b="B")["finding"] == (
        "Through lap 2, B was 1.000 s ahead of A on summed lap times.")


def test_qualifying_without_degradation_summary_returns_empty_data():
    figure = client.get("/api/chart/degradation-bars", params={"slug": Q})
    twin = client.get("/api/chart-data/degradation-bars", params={"slug": Q})
    assert figure.status_code == twin.status_code == 200
    assert figure.json()["data"] == []
    assert twin.json()["compounds"] == []
    assert twin.json()["finding"] == "No degradation estimate is available."


def test_refusals_match_figure_route(monkeypatch):
    for endpoint in ("/api/chart/", "/api/chart-data/"):
        assert client.get(endpoint + "missing").status_code == 404
        assert client.get(endpoint + "speed-map").status_code == 400
        assert client.get(endpoint + "speed-map", params={"slug": "bad"}).status_code == 400
        assert client.get(endpoint + "speed-map", params={"slug": "2024/99_Q"}).status_code == 404
        assert client.get(endpoint + "undercut-chart",
                          params={"gap_s": "not-a-number"}).status_code == 400
    from api import cache
    real = cache.load_artefact
    broken = pd.DataFrame({"Number": [1, 2], "CornerLabel": ["1", "2"],
                           "Distance": [500.0, 500.0]})
    monkeypatch.setattr(cache, "load_artefact",
                        lambda slug, name: broken if name == "corners" else real(slug, name))
    for endpoint in ("/api/chart/", "/api/chart-data/"):
        response = client.get(endpoint + "corner-delta-bars",
                              params={"slug": Q, **DRIVERS})
        assert response.status_code == 409, response.text[:200]
