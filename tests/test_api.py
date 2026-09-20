"""Tests for the FastAPI service the React frontend runs on.

These are integration tests against the built dataset and **skip** when it is
absent, the same contract ``tests/test_integration.py`` uses. What they pin is
the API's side of the boundary: that a response carries the fields a page
needs, and that every chart id renders.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api.charts import BUILDERS
from api.main import app

client = TestClient(app)


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def manifest() -> dict:
    response = client.get("/api/manifest")
    assert response.status_code == 200
    return response.json()


@pytest.fixture(scope="module")
def any_slug(manifest) -> str:
    if not manifest["sessions"]:
        pytest.skip("No processed sessions in the repository.")
    return manifest["sessions"][0]["slug"]


def _slug_of(manifest, session_type: str) -> str:
    for row in manifest["sessions"]:
        if row["session"] == session_type:
            return row["slug"]
    pytest.skip(f"No {session_type} session built.")


@pytest.fixture(scope="module")
def race_slug(manifest) -> str:
    return _slug_of(manifest, "R")


@pytest.fixture(scope="module")
def quali_slug(manifest) -> str:
    return _slug_of(manifest, "Q")


# --------------------------------------------------------------------------
# Manifest, theme, circuits
# --------------------------------------------------------------------------

def test_status():
    """`/api/status`, not `/` — once `frontend/dist` exists the app owns `/`."""
    body = client.get("/api/status").json()
    assert body["status"] == "online"


def test_manifest_keeps_every_column(manifest):
    """The previous API modelled this response and silently dropped half of it.

    ``n_drivers`` / ``total_laps`` / ``grid_points`` are read directly by the
    home page's proof strip and by Race Arc's fuel model, so a response model
    that quietly discards them fails at the far end of the app, not here.
    """
    if not manifest["sessions"]:
        pytest.skip("No processed sessions in the repository.")
    row = manifest["sessions"][0]
    for column in ("year", "round", "session", "slug", "event_name", "location",
                   "country", "n_drivers", "n_laps", "total_laps", "grid_points"):
        assert column in row, f"manifest response is missing {column}"
    assert manifest["years"] == sorted(manifest["years"], reverse=True)


def test_featured_sessions_point_at_react_routes(manifest):
    for item in manifest["featured"]:
        assert item["route"].startswith("/"), item
        assert not item["route"].endswith(".py"), "Streamlit page path leaked through"


def test_theme_exposes_the_tokens_the_client_must_not_hardcode():
    theme = client.get("/api/theme").json()
    assert theme["colours"]["accent"].startswith("#")
    assert len(theme["series"]) >= 4
    assert "SOFT" in theme["compound_colours"]
    assert theme["plotly_config"]["displaylogo"] is False


def test_circuits_gallery_is_deduplicated():
    circuits = client.get("/api/circuits").json()["circuits"]
    if not circuits:
        pytest.skip("No trackmaps built.")
    names = [c["name"] for c in circuits]
    assert len(names) == len(set(names))
    assert all(len(c["x"]) == len(c["y"]) > 2 for c in circuits)


# --------------------------------------------------------------------------
# Bad input
# --------------------------------------------------------------------------

def test_malformed_slug_is_400():
    assert client.get("/api/session?slug=not-a-slug").status_code == 400


def test_unbuilt_session_is_404():
    """Not 444 - that is nginx's 'closed without response' and is not an HTTP status."""
    assert client.get("/api/session?slug=1999/01_R").status_code == 404


def test_unknown_chart_is_404():
    assert client.get("/api/chart/no-such-chart?slug=2024/01_R").status_code == 404


# --------------------------------------------------------------------------
# Session detail
# --------------------------------------------------------------------------

def test_session_detail(any_slug):
    body = client.get(f"/api/session?slug={any_slug}").json()
    assert body["slug"] == any_slug
    assert body["session_label"]
    assert isinstance(body["is_race"], bool)
    assert len(body["trackmap"]["x"]) == len(body["trackmap"]["y"])
    assert set(body["availability"]["summary"]) >= {
        "n_laps", "n_stored", "n_missing", "coverage", "stores_all_laps"}


def test_driver_laps_carry_what_the_selector_labels_them_with(any_slug):
    """The lap dropdown prints time, compound, kind and coverage for every option.

    A lap that reaches the client without ``kind``/``cov_*`` cannot be
    labelled as partial, which is the one thing that selector must never leave
    implicit.
    """
    body = client.get(f"/api/session?slug={any_slug}").json()
    if not body["driver_laps"]:
        pytest.skip("No stored telemetry for this session.")
    laps = next(iter(body["driver_laps"].values()))
    assert set(laps[0]) == {"lap", "time_s", "compound", "kind",
                            "cov_start", "cov_end"}


def test_lap_order_follows_session_type(race_slug, quali_slug):
    """Races list chronologically, qualifying fastest-first - as the pages do."""
    race = client.get(f"/api/session?slug={race_slug}").json()["driver_laps"]
    quali = client.get(f"/api/session?slug={quali_slug}").json()["driver_laps"]

    for laps in race.values():
        if len(laps) > 2:
            numbers = [lap["lap"] for lap in laps]
            assert numbers == sorted(numbers)
            break

    for laps in quali.values():
        times = [lap["time_s"] for lap in laps if lap["time_s"] is not None]
        if len(times) > 2:
            assert times == sorted(times)
            break


# --------------------------------------------------------------------------
# Home
# --------------------------------------------------------------------------

def test_home(any_slug):
    body = client.get(f"/api/home?slug={any_slug}").json()
    assert body["slug"] == any_slug
    if body["fastest_per_driver"]:
        first = body["fastest_per_driver"][0]
        assert first["Status"] == "Session best"
        assert first["Gap"] == "—"
        assert ":" in first["Lap time"], "lap time should be m:ss.mmm"


# --------------------------------------------------------------------------
# Corner analysis
# --------------------------------------------------------------------------

def test_corner_analysis(quali_slug):
    session = client.get(f"/api/session?slug={quali_slug}").json()
    drivers = session["drivers"]
    if len(drivers) < 2:
        pytest.skip("Need two drivers with telemetry.")
    a, b = drivers[0], drivers[1]

    body = client.get(
        f"/api/corner-analysis?slug={quali_slug}&driver1={a}&driver2={b}").json()
    assert body["display_a"] == a and body["display_b"] == b
    assert body["segments"], "segment tiling should never be empty"

    # Stable keys, not the driver-suffixed columns compare_corners emits.
    assert set(body["segments"][0]) == {
        "label", "kind", "delta_s", "cum_delta_s", "comparable",
        "v_min_a", "v_min_b", "v_min_diff",
        "brake_m_a", "brake_m_b", "brake_m_diff"}

    assert set(body["summary"]) >= {"total_delta_s", "corner_delta_s",
                                    "straight_delta_s", "coverage",
                                    "n_segments", "n_comparable",
                                    "biggest_gains", "biggest_losses"}
    # The ghost replay needs one time sample per grid point, for both laps.
    assert len(body["ghost"]["t_a"]) == len(body["ghost"]["t_b"]) > 0


def test_same_driver_comparison_gets_distinguishable_labels(quali_slug):
    """Comparing a driver with themselves must not produce two identical names."""
    drivers = client.get(f"/api/session?slug={quali_slug}").json()["drivers"]
    if not drivers:
        pytest.skip("No drivers with telemetry.")
    a = drivers[0]
    body = client.get(
        f"/api/corner-analysis?slug={quali_slug}&driver1={a}&driver2={a}").json()
    assert body["display_a"] != body["display_b"]


# --------------------------------------------------------------------------
# Race arc
# --------------------------------------------------------------------------

def test_race_arc(race_slug):
    body = client.get(f"/api/race-arc?slug={race_slug}").json()
    assert body["is_race"] is True
    assert body["degradation"]["n_prepared"] >= 0
    assert "pit_loss" in body["strategy"]
    assert body["strategy"]["default_deg_rate"] is not None


def test_race_arc_drops_the_unserialisable_model(race_slug):
    """``fit_evolution`` returns a statsmodels wrapper under ``model``.

    It cannot cross the wire and nothing on the client can use it, so it is
    dropped in ``cache.load_evolution`` rather than at each call site. If it
    ever comes back, the response stops being JSON at all.
    """
    body = client.get(f"/api/race-arc?slug={race_slug}").json()
    result = body["evolution"]["result"]
    if result is None:
        pytest.skip("This race does not support the pooled model.")
    assert "model" not in result
    assert result["r_squared"] is not None


def test_race_arc_on_a_non_race_still_answers(quali_slug):
    body = client.get(f"/api/race-arc?slug={quali_slug}").json()
    assert body["is_race"] is False
    assert body["strategy"] == {}


def test_undercut():
    body = client.get(
        "/api/undercut?gap_s=1.5&advantage=0.8&deg_rate=0.12").json()
    assert len(body["table"]) > 0
    assert set(body["table"][0]) >= {"laps_after_stop", "cumulative_gain_s",
                                     "net_gap_s", "ahead"}


# --------------------------------------------------------------------------
# Charts
# --------------------------------------------------------------------------

# Which session type each chart id can actually be exercised against, plus any
# extra query parameters it needs. Every id in BUILDERS must appear here - the
# completeness test below is what stops a new chart shipping untested.
CHART_CASES: dict[str, tuple[str, str]] = {
    "speed-delta-map": ("Q", ""),
    "speed-map": ("Q", "&which=a"),
    "trace-panel": ("Q", ""),
    "corner-delta-bars": ("Q", ""),
    "lap-by-lap": ("Q", ""),
    "session-best": ("Q", ""),
    "degradation-scatter": ("R", ""),
    "degradation-bars": ("R", ""),
    "evolution-curve": ("R", ""),
    "evolution-temperature": ("R", ""),
    "stint-chart": ("R", ""),
    "race-pace-box": ("R", ""),
    "gap-chart": ("R", ""),
    "position-chart": ("R", ""),
    "undercut-chart": ("none", "gap_s=1.5&advantage=0.8&deg_rate=0.12"),
}


def test_every_chart_id_is_covered():
    assert set(CHART_CASES) == set(BUILDERS), (
        "CHART_CASES and the chart registry have drifted apart")


@pytest.mark.parametrize("chart_id", sorted(CHART_CASES))
def test_chart_renders(chart_id, manifest):
    session_type, extra = CHART_CASES[chart_id]

    if session_type == "none":
        url = f"/api/chart/{chart_id}?{extra}"
    else:
        slug = _slug_of(manifest, session_type)
        query = f"slug={slug}{extra}"
        if chart_id in {"speed-delta-map", "speed-map", "trace-panel",
                        "corner-delta-bars", "lap-by-lap"}:
            drivers = client.get(f"/api/session?slug={slug}").json()["drivers"]
            if len(drivers) < 2:
                pytest.skip("Need two drivers with telemetry.")
            query += f"&driver1={drivers[0]}&driver2={drivers[1]}"
        if chart_id == "gap-chart":
            pace = client.get(f"/api/race-arc?slug={slug}").json()
            names = pace["strategy"].get("gap_drivers", [])[:5]
            if not names:
                pytest.skip("No race pace to plot.")
            query += f"&drivers={','.join(names)}"
        url = f"/api/chart/{chart_id}?{query}"

    response = client.get(url)
    if response.status_code == 404:
        pytest.skip(f"{chart_id}: not available for this dataset")
    assert response.status_code == 200, response.text

    figure = json.loads(response.text)
    assert "data" in figure and "layout" in figure
    # Every figure goes through ``theme.apply``; losing the template is how a
    # chart silently reverts to Plotly's white default on a black page.
    assert figure["layout"].get("template"), f"{chart_id} lost the pitwall template"


# --------------------------------------------------------------------------
# Static file containment
# --------------------------------------------------------------------------

@pytest.mark.parametrize("attack", [
    "/etc/passwd",
    "C:/Windows/win.ini",
    "../../../../requirements.txt",
    "..%2f..%2f..%2frequirements.txt",
])
def test_the_spa_route_cannot_read_a_file_outside_the_build(attack):
    """A path that escapes frontend/dist gets the shell, never the file.

    `Path(base) / "/etc/passwd"` discards the base, so an absolute path walks
    out without a single `..`. Containment is checked after resolving.
    """
    from api.main import _DIST

    if not _DIST.is_dir():
        pytest.skip("frontend/dist is not built, so the SPA route is not mounted.")

    response = client.get(f"/{attack}")
    assert response.status_code == 200
    body = response.text
    assert "root:" not in body, "served /etc/passwd"
    assert "fastapi" not in body.lower(), "served requirements.txt"
    assert "<html" in body.lower() or "<!doctype" in body.lower(), "not the SPA shell"


def test_the_telemetry_cache_holds_two_frames_not_four():
    """~74 MB per decoded frame against Render's 512 MB. See DECISIONS.md ADR-001."""
    from api.cache import load_telemetry

    assert load_telemetry.cache_info().maxsize == 2
