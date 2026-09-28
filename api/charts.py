"""Plotly figures and plain chart-data twins share one input-resolution path.

The existing client still uses Plotly; its major must match plotly.py until
the SVG replacement removes that dependency (Phase 2B Steps 5-7).
"""

from __future__ import annotations

import math
from typing import Any, Callable

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Request, Response

from api import cache
from pitwall import config, evolution, store, strategy
from pitwall.corners import compare_corners, corner_data_issues
from pitwall.strategy import head_to_head
from pitwall.viz import charts as viz_charts
from pitwall.viz import traces as viz_traces
from pitwall.viz import trackmap as viz_trackmap

router = APIRouter()


# --------------------------------------------------------------------------
# Shared input resolution
# --------------------------------------------------------------------------

def _number(params: dict[str, str], name: str, default: float) -> float:
    """A finite float from a query string, or 400 with the offending value.

    float() on raw query text raised ValueError for "oops" and accepted
    "nan"/"inf", so a malformed public request reached the analysis and came
    back as a 500 rather than a client error.
    """
    raw = params.get(name)
    if raw in (None, "", "null"):
        return float(default)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise HTTPException(400, f"{name} must be a number, got {raw!r}") from None
    if not math.isfinite(value):
        raise HTTPException(400, f"{name} must be finite, got {raw!r}")
    return value


def _laps_for_comparison(slug: str, params: dict[str, str]):
    """The two selected laps plus the segment tiling, as the pages resolve them."""
    driver_a = params.get("driver1")
    driver_b = params.get("driver2")
    if not driver_a or not driver_b:
        raise HTTPException(400, "driver1 and driver2 are required")

    # The same refusal /api/corner-analysis makes, in the path both share.
    # Enforced on one endpoint only, a chart built from markers the analysis
    # had already declared unusable still rendered with a 200.
    issues = corner_data_issues(cache.load_artefact(slug, "corners"))
    if issues:
        raise HTTPException(
            409,
            "Corner analysis is unavailable for this session because "
            + "; ".join(issues)
            + ". Lap times, strategy and degradation are unaffected.",
        )

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

    fuel_effect = _number(params, "fuel_effect", config.FUEL_EFFECT_S_PER_KG)
    fuel_kg = _number(params, "fuel_kg", config.race_fuel_kg(year))

    prepared, _ = cache.load_prepared(slug, year, total_laps, fuel_effect, fuel_kg)
    stints, summary = cache.load_stint_fits(
        slug, year, total_laps, fuel_effect, fuel_kg)
    return prepared, stints, summary, year, total_laps, fuel_effect, fuel_kg


# --------------------------------------------------------------------------
# Builders — one per chart id, each a thin call into pitwall.viz
# --------------------------------------------------------------------------

def _speed_delta_map(slug: str, p: dict[str, str], data: bool = False):
    a, b, name_a, name_b, _ = _laps_for_comparison(slug, p)
    render = viz_trackmap.speed_delta_map_data if data else viz_trackmap.speed_delta_map
    return render(
        cache.load_artefact(slug, "trackmap"), a, b,
        name_a=name_a, name_b=name_b,
        corners=cache.load_artefact(slug, "corners"),
    )


def _speed_map(slug: str, p: dict[str, str], data: bool = False):
    a, b, name_a, name_b, _ = _laps_for_comparison(slug, p)
    which = p.get("which", "a")
    render = viz_trackmap.speed_map_data if data else viz_trackmap.speed_map
    return render(
        cache.load_artefact(slug, "trackmap"),
        a if which == "a" else b,
        corners=cache.load_artefact(slug, "corners"),
    )


def _trace_panel(slug: str, p: dict[str, str], data: bool = False):
    a, b, name_a, name_b, segments = _laps_for_comparison(slug, p)
    render = viz_traces.trace_panel_data if data else viz_traces.trace_panel
    return render(a, b, segments, name_a=name_a, name_b=name_b)


def _corner_delta_bars(slug: str, p: dict[str, str], data: bool = False):
    a, b, name_a, name_b, segments = _laps_for_comparison(slug, p)
    comparison = compare_corners(a, b, segments, name_a=name_a, name_b=name_b)
    render = viz_traces.corner_delta_bars_data if data else viz_traces.corner_delta_bars
    result = render(comparison, name_a=name_a, name_b=name_b)
    if data and not comparison.empty:
        corners = comparison.loc[comparison["kind"] == "corner", "delta_s"]
        gain = round(float(corners.sum()), 3)
        winner = name_a if gain > 0 else name_b if gain < 0 else None
        names = cache.load_artefact(slug, "results")
        full_name = winner
        if winner and {"Abbreviation", "FullName"}.issubset(names.columns):
            match = names.loc[names["Abbreviation"] == winner, "FullName"]
            if not match.empty:
                full_name = str(match.iloc[0]).split()[-1]
        result["finding"] = (f"{full_name} gained {abs(gain):.3f} s in the corners "
                             f"against {name_b if winner == name_a else name_a}."
                             if winner else f"The corners are even at 0.000 s between {name_a} and {name_b}.")
    return result


def _lap_by_lap(slug: str, p: dict[str, str], data: bool = False):
    driver_a, driver_b = p.get("driver1"), p.get("driver2")
    if not driver_a or not driver_b:
        raise HTTPException(400, "driver1 and driver2 are required")
    h2h = head_to_head(cache.load_laps(slug), driver_a, driver_b)
    if h2h.empty:
        raise HTTPException(404, "No lap table stored for this session")
    render = viz_charts.lap_by_lap_data if data else viz_charts.lap_by_lap
    return render(h2h, name_a=driver_a, name_b=driver_b)


def _degradation_scatter(slug: str, p: dict[str, str], data: bool = False):
    prepared, stints, _, *_ = _race_arc_inputs(slug, p)
    render = viz_charts.degradation_scatter_data if data else viz_charts.degradation_scatter
    return render(prepared, stints)


def _degradation_bars(slug: str, p: dict[str, str], data: bool = False):
    _, _, summary, *_ = _race_arc_inputs(slug, p)
    render = viz_charts.degradation_bars_data if data else viz_charts.degradation_bars
    return render(summary)


def _session_best(slug: str, p: dict[str, str], data: bool = False):
    progression = evolution.session_best_progression(cache.load_laps(slug))
    render = viz_charts.session_best_curve_data if data else viz_charts.session_best_curve
    return render(progression)


def _evolution_pair(slug: str, p: dict[str, str]):
    prepared, _, _, year, total_laps, fuel_effect, fuel_kg = _race_arc_inputs(slug, p)
    result = cache.load_evolution(slug, year, total_laps, fuel_effect, fuel_kg)
    if result is None:
        raise HTTPException(404, "This session does not support the pooled model")
    naive = evolution.naive_evolution(prepared, total_laps=total_laps)
    return result["curve"], naive


def _evolution_curve(slug: str, p: dict[str, str], data: bool = False):
    curve, naive = _evolution_pair(slug, p)
    render = viz_charts.evolution_curve_data if data else viz_charts.evolution_curve
    return render(curve, naive)


def _evolution_temperature(slug: str, p: dict[str, str], data: bool = False):
    curve, _ = _evolution_pair(slug, p)
    render = (viz_charts.evolution_with_temperature_data if data
              else viz_charts.evolution_with_temperature)
    return render(
        curve, cache.load_artefact(slug, "weather"))


def _stint_chart(slug: str, p: dict[str, str], data: bool = False):
    render = viz_charts.stint_chart_data if data else viz_charts.stint_chart
    return render(strategy.stint_table(cache.load_laps(slug)))


def _race_pace_box(slug: str, p: dict[str, str], data: bool = False):
    prepared, *_ = _race_arc_inputs(slug, p)
    if data:
        return viz_charts.race_pace_box_data(prepared, strategy.race_pace(prepared))
    return viz_charts.race_pace_box(
        prepared, strategy.race_pace(prepared),
        results=cache.load_artefact(slug, "results"),
    )


def _gap_chart(slug: str, p: dict[str, str], data: bool = False):
    chosen = [d for d in (p.get("drivers") or "").split(",") if d]
    if data:
        return viz_charts.gap_chart_data(strategy.gap_evolution(cache.load_laps(slug)), chosen)
    return viz_charts.gap_chart(
        strategy.gap_evolution(cache.load_laps(slug)), chosen,
        results=cache.load_artefact(slug, "results"),
    )


def _position_chart(slug: str, p: dict[str, str], data: bool = False):
    if data:
        return viz_charts.position_chart_data(cache.load_laps(slug))
    return viz_charts.position_chart(
        cache.load_laps(slug), results=cache.load_artefact(slug, "results"))


def _undercut_chart(slug: str, p: dict[str, str], data: bool = False):
    gap_s = _number(p, "gap_s", 1.5)
    table = strategy.undercut_gain(
        gap_to_rival_s=gap_s,
        fresh_tyre_advantage_s=_number(p, "advantage", 0.8),
        deg_s_per_lap=_number(p, "deg_rate", 0.10),
    )
    render = viz_charts.undercut_chart_data if data else viz_charts.undercut_chart
    return render(table, gap_s)


# ``slug`` is unused by the undercut chart - it is a pure function of its three
# slider values - but the signature is uniform so the registry stays a plain
# lookup rather than a set of special cases.
BUILDERS: dict[str, Callable[..., Any]] = {
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


def _validated_builder(chart_id: str, slug: str) -> Callable[..., Any]:
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
    return builder


def _plain(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return [_plain(item) for item in value]
    if isinstance(value, np.generic):
        return _plain(value.item())
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


@router.get("/api/chart/{chart_id}")
def get_chart(chart_id: str, request: Request,
              slug: str = Query("", description="e.g. 2024/12_Q")):
    """A tuned ``pitwall.viz`` figure, as Plotly JSON."""
    builder = _validated_builder(chart_id, slug)

    figure = builder(slug, dict(request.query_params))
    return Response(content=figure.to_json(), media_type="application/json")


@router.get("/api/chart-data/{chart_id}")
def get_chart_data(chart_id: str, request: Request,
                   slug: str = Query("", description="e.g. 2024/12_Q")):
    builder = _validated_builder(chart_id, slug)
    return _plain(dict(chart_id=chart_id,
                       **builder(slug, dict(request.query_params), data=True)))
