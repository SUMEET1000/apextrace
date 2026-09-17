"""Chart endpoints: the existing ``pitwall.viz`` figures, served as JSON.

Every figure in the app is built by a function that already exists and is
already tuned - the shared ``pitwall`` Plotly template, the hovertemplates,
the diverging colourscales, the stacked-panel layouts. None of that is
reimplemented here. This module only resolves a chart id to its inputs, calls
the function, and hands the resulting figure to the browser verbatim via
``fig.to_json()``.

That is what keeps the React frontend visually identical to the Streamlit one
it replaces, and it is why the client renders with plotly.js rather than a
charting library that would have to re-derive all of the above by hand.

**The plotly.js major on the client must match the schema plotly.py emits**
here, or traces silently fail to render. See ``frontend/package.json``.
"""

from __future__ import annotations

from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Query, Request, Response

from api import cache
from pitwall import config, evolution, store, strategy
from pitwall.corners import compare_corners
from pitwall.strategy import head_to_head
from pitwall.viz import charts as viz_charts
from pitwall.viz import traces as viz_traces
from pitwall.viz import trackmap as viz_trackmap

router = APIRouter()


# --------------------------------------------------------------------------
# Shared input resolution
# --------------------------------------------------------------------------

def _laps_for_comparison(slug: str, params: dict[str, str]):
    """The two selected laps plus the segment tiling, as the pages resolve them."""
    driver_a = params.get("driver1")
    driver_b = params.get("driver2")
    if not driver_a or not driver_b:
        raise HTTPException(400, "driver1 and driver2 are required")

    telemetry = cache.load_telemetry(slug)
    if telemetry.empty:
        raise HTTPException(404, "No telemetry stored for this session")

    def _lap(value: str | None):
        return float(value) if value not in (None, "", "null") else None

    frame_a = store.get_lap(telemetry, driver_a, _lap(params.get("lap1")))
    frame_b = store.get_lap(telemetry, driver_b, _lap(params.get("lap2")))
    if frame_a.empty or frame_b.empty:
        raise HTTPException(404, "One of the selected laps has no stored telemetry")

    lap_a = int(frame_a["LapNumber"].iloc[0])
    lap_b = int(frame_b["LapNumber"].iloc[0])
    display_a = f"{driver_a} L{lap_a}" if driver_a == driver_b else driver_a
    display_b = f"{driver_b} L{lap_b}" if driver_a == driver_b else driver_b
    if display_a == display_b:
        display_a += " (Ref)"
        display_b += " (Cmp)"

    return frame_a, frame_b, display_a, display_b, cache.load_segments(slug)


def _race_arc_inputs(slug: str, params: dict[str, str]):
    """Prepared laps and stint fits at the requested fuel assumptions.

    The fuel figures arrive from the two sidebar sliders. They are passed
    explicitly rather than defaulted inside, so a chart drawn at the default
    slider positions hits the same cache entry as one drawn with no sliders
    touched at all.
    """
    meta = cache.load_manifest()
    row = meta[meta["slug"] == slug]
    if row.empty:
        raise HTTPException(404, f"Session {slug} is not in the manifest")
    year = int(row.iloc[0]["year"])
    total_laps = int(row.iloc[0]["total_laps"])

    fuel_effect = float(params.get("fuel_effect") or config.FUEL_EFFECT_S_PER_KG)
    fuel_kg = float(params.get("fuel_kg") or config.race_fuel_kg(year))

    prepared, _ = cache.load_prepared(slug, year, total_laps, fuel_effect, fuel_kg)
    stints, summary = cache.load_stint_fits(
        slug, year, total_laps, fuel_effect, fuel_kg)
    return prepared, stints, summary, year, total_laps, fuel_effect, fuel_kg


# --------------------------------------------------------------------------
# Builders — one per chart id, each a thin call into pitwall.viz
# --------------------------------------------------------------------------

def _speed_delta_map(slug: str, p: dict[str, str]):
    a, b, name_a, name_b, _ = _laps_for_comparison(slug, p)
    return viz_trackmap.speed_delta_map(
        cache.load_artefact(slug, "trackmap"), a, b,
        name_a=name_a, name_b=name_b,
        corners=cache.load_artefact(slug, "corners"),
    )


def _speed_map(slug: str, p: dict[str, str]):
    a, b, name_a, name_b, _ = _laps_for_comparison(slug, p)
    which = p.get("which", "a")
    return viz_trackmap.speed_map(
        cache.load_artefact(slug, "trackmap"),
        a if which == "a" else b,
        corners=cache.load_artefact(slug, "corners"),
    )


def _trace_panel(slug: str, p: dict[str, str]):
    a, b, name_a, name_b, segments = _laps_for_comparison(slug, p)
    return viz_traces.trace_panel(a, b, segments, name_a=name_a, name_b=name_b)


def _corner_delta_bars(slug: str, p: dict[str, str]):
    a, b, name_a, name_b, segments = _laps_for_comparison(slug, p)
    comparison = compare_corners(a, b, segments, name_a=name_a, name_b=name_b)
    return viz_traces.corner_delta_bars(comparison, name_a=name_a, name_b=name_b)


def _lap_by_lap(slug: str, p: dict[str, str]):
    driver_a, driver_b = p.get("driver1"), p.get("driver2")
    if not driver_a or not driver_b:
        raise HTTPException(400, "driver1 and driver2 are required")
    h2h = head_to_head(cache.load_laps(slug), driver_a, driver_b)
    if h2h.empty:
        raise HTTPException(404, "No lap table stored for this session")
    return viz_charts.lap_by_lap(h2h, name_a=driver_a, name_b=driver_b)


def _degradation_scatter(slug: str, p: dict[str, str]):
    prepared, stints, _, *_ = _race_arc_inputs(slug, p)
    return viz_charts.degradation_scatter(prepared, stints)


def _degradation_bars(slug: str, p: dict[str, str]):
    _, _, summary, *_ = _race_arc_inputs(slug, p)
    return viz_charts.degradation_bars(summary)


def _session_best(slug: str, p: dict[str, str]):
    progression = evolution.session_best_progression(cache.load_laps(slug))
    return viz_charts.session_best_curve(progression)


def _evolution_pair(slug: str, p: dict[str, str]):
    prepared, _, _, year, total_laps, fuel_effect, fuel_kg = _race_arc_inputs(slug, p)
    result = cache.load_evolution(slug, year, total_laps, fuel_effect, fuel_kg)
    if result is None:
        raise HTTPException(404, "This session does not support the pooled model")
    naive = evolution.naive_evolution(prepared, total_laps=total_laps)
    return result["curve"], naive


def _evolution_curve(slug: str, p: dict[str, str]):
    curve, naive = _evolution_pair(slug, p)
    return viz_charts.evolution_curve(curve, naive)


def _evolution_temperature(slug: str, p: dict[str, str]):
    curve, _ = _evolution_pair(slug, p)
    return viz_charts.evolution_with_temperature(
        curve, cache.load_artefact(slug, "weather"))


def _stint_chart(slug: str, p: dict[str, str]):
    return viz_charts.stint_chart(strategy.stint_table(cache.load_laps(slug)))


def _race_pace_box(slug: str, p: dict[str, str]):
    prepared, *_ = _race_arc_inputs(slug, p)
    return viz_charts.race_pace_box(
        prepared, strategy.race_pace(prepared),
        results=cache.load_artefact(slug, "results"),
    )


def _gap_chart(slug: str, p: dict[str, str]):
    chosen = [d for d in (p.get("drivers") or "").split(",") if d]
    return viz_charts.gap_chart(
        strategy.gap_evolution(cache.load_laps(slug)), chosen,
        results=cache.load_artefact(slug, "results"),
    )


def _position_chart(slug: str, p: dict[str, str]):
    return viz_charts.position_chart(
        cache.load_laps(slug), results=cache.load_artefact(slug, "results"))


def _undercut_chart(slug: str, p: dict[str, str]):
    gap_s = float(p.get("gap_s") or 1.5)
    table = strategy.undercut_gain(
        gap_to_rival_s=gap_s,
        fresh_tyre_advantage_s=float(p.get("advantage") or 0.8),
        deg_s_per_lap=float(p.get("deg_rate") or 0.10),
    )
    return viz_charts.undercut_chart(table, gap_s)


# ``slug`` is unused by the undercut chart - it is a pure function of its three
# slider values - but the signature is uniform so the registry stays a plain
# lookup rather than a set of special cases.
BUILDERS: dict[str, Callable[[str, dict[str, str]], Any]] = {
    # Corner Analysis
    "speed-delta-map": _speed_delta_map,
    "speed-map": _speed_map,
    "trace-panel": _trace_panel,
    "corner-delta-bars": _corner_delta_bars,
    "lap-by-lap": _lap_by_lap,
    # Race Arc · Tyre Degradation
    "degradation-scatter": _degradation_scatter,
    "degradation-bars": _degradation_bars,
    # Race Arc · Track Evolution
    "session-best": _session_best,
    "evolution-curve": _evolution_curve,
    "evolution-temperature": _evolution_temperature,
    # Race Arc · Race Strategy
    "stint-chart": _stint_chart,
    "race-pace-box": _race_pace_box,
    "gap-chart": _gap_chart,
    "position-chart": _position_chart,
    "undercut-chart": _undercut_chart,
}

# The one chart that needs no session at all.
_SLUGLESS = {"undercut-chart"}


@router.get("/api/chart/{chart_id}")
def get_chart(chart_id: str, request: Request,
              slug: str = Query("", description="e.g. 2024/12_Q")):
    """A tuned ``pitwall.viz`` figure, as Plotly JSON.

    Returned as a raw ``Response`` rather than a dict: ``fig.to_json()``
    already produces valid, NaN-free JSON via Plotly's own encoder, and
    round-tripping it through FastAPI's serialiser would only risk mangling
    the numpy arrays it has just encoded correctly.
    """
    builder = BUILDERS.get(chart_id)
    if builder is None:
        raise HTTPException(404, f"Unknown chart: {chart_id!r}")

    if chart_id not in _SLUGLESS:
        if not slug:
            raise HTTPException(400, "slug is required")
        try:
            store.key_from_slug(slug)
        except Exception:
            raise HTTPException(400, f"Invalid session slug: {slug!r}")
        manifest = cache.load_manifest()
        if manifest.empty or slug not in set(manifest["slug"].astype(str)):
            raise HTTPException(404, f"Session {slug} is not in the manifest")

    figure = builder(slug, dict(request.query_params))
    return Response(content=figure.to_json(), media_type="application/json")
