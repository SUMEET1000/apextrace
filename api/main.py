"""FastAPI service behind the ApexTrace React frontend.

This is the layer ``app/common.py`` used to be: the only place the analysis
library meets a UI. ``pitwall`` stays pure pandas/numpy and knows nothing
about HTTP, exactly as it knew nothing about Streamlit.

Responses are plain dicts rather than Pydantic response models. That is
deliberate: several payloads carry driver-dependent column names, and a
response model with Pydantic's default ``extra='ignore'`` silently drops any
field it was not told about - which is how the previous version of this file
served a manifest with ``n_drivers``, ``total_laps`` and ``grid_points``
missing. Validation that quietly deletes data is worse than none.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from api import cache  # noqa: E402
from pitwall import config, degradation, evolution, store, strategy  # noqa: E402
from pitwall.corners import (  # noqa: E402
    compare_corners, corner_data_issues, summarise_comparison,
)
from pitwall.strategy import head_to_head  # noqa: E402
from pitwall.viz import theme  # noqa: E402
from pitwall.viz.trackmap import corner_labels_data  # noqa: E402

app = FastAPI(
    title="ApexTrace API",
    description="F1 telemetry, corner analysis, and race strategy",
    version="2.0.0",
)

# The Vite dev server proxies /api, so same-origin in development and in the
# built deployment. Kept permissive for direct access to /docs.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=5)


# --------------------------------------------------------------------------
# JSON safety
#
# Parquet-backed frames are full of NaN, NaT and numpy scalars, none of which
# are valid JSON. `json.dumps` will happily emit bare `NaN`, which then fails
# in the browser's JSON.parse rather than at the server - so the conversion is
# done here, once, on the way out.
# --------------------------------------------------------------------------

def jsonable(value: Any) -> Any:
    """Recursively convert pandas/numpy values into JSON-safe Python."""
    if value is None:
        return None
    if isinstance(value, (str, bool, int)) and not isinstance(value, np.generic):
        return value
    if isinstance(value, float):
        return None if (math.isnan(value) or math.isinf(value)) else value
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(v) for v in value]
    if isinstance(value, pd.Timedelta):
        return None if pd.isna(value) else value.total_seconds()
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return None if pd.isna(value) else str(value)
    if isinstance(value, np.ndarray):
        return [jsonable(v) for v in value.tolist()]
    if isinstance(value, pd.Series):
        return [jsonable(v) for v in value.tolist()]
    if isinstance(value, pd.DataFrame):
        return records(value)
    if isinstance(value, np.generic):
        return jsonable(value.item())
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """A DataFrame as JSON-safe records.

    Vectorised via ``to_dict``; the previous version walked every cell with
    ``.loc[i, col]``, which on a 1000-point trace was ~13,000 scalar lookups
    per request.
    """
    if df is None or df.empty:
        return []
    return [jsonable(row) for row in df.to_dict(orient="records")]


def _session_key(slug: str):
    try:
        key = store.key_from_slug(slug)
    except Exception:
        raise HTTPException(400, f"Invalid session slug: {slug!r}")
    manifest = cache.load_manifest()
    if manifest.empty or slug not in set(manifest["slug"].astype(str)):
        raise HTTPException(404, f"Session {slug} is not in the manifest")
    return key


def _meta(slug: str) -> pd.Series:
    manifest = cache.load_manifest()
    row = manifest[manifest["slug"] == slug]
    if row.empty:
        raise HTTPException(404, f"Session {slug} is not in the manifest")
    return row.iloc[0]


def _trackmap_xy(slug: str) -> dict[str, list[int]]:
    """Circuit outline as raw X/Y.

    Sent unprojected because the frontend projects the same outline into three
    different boxes (page header, home reel, ghost replay) and all of them
    have to agree - so the projection lives in one place on the client rather
    than being baked at one size here.
    """
    track = cache.load_artefact(slug, "trackmap")
    if track.empty or not {"X", "Y"}.issubset(track.columns):
        return {"x": [], "y": []}
    return _outline(track)


def _outline(track: pd.DataFrame) -> dict[str, list[int]]:
    """X/Y rounded to whole position units.

    ``POSITION_UNITS_PER_M`` is 10, so a unit is 10 cm. The largest box any of
    this artwork is drawn into is 520 px wide for a circuit kilometres across,
    where one pixel is several metres - the discarded decimal was never
    reaching a screen, and it was a quarter of the payload.
    """
    return {
        "x": [int(round(float(v))) for v in track["X"]],
        "y": [int(round(float(v))) for v in track["Y"]],
    }


# --------------------------------------------------------------------------
# Root, theme
# --------------------------------------------------------------------------

@app.get("/api/status")
def status():
    """Liveness, on a path the built frontend can never shadow.

    ``/`` belongs to the app once ``frontend/dist`` exists, so the service's
    own health check cannot live there.
    """
    return {"status": "online", "service": "ApexTrace REST API", "docs": "/docs"}


@app.get("/api/theme")
def get_theme():
    """Design tokens and Plotly config, so the client never hardcodes them.

    Every value here has exactly one definition, in ``pitwall/viz/theme.py``
    or ``pitwall/config.py``. Duplicating any of them into CSS or TypeScript
    is how a chart and the panel behind it end up different shades of the same
    intended colour.
    """
    return {
        "colours": {
            "surface": theme.SURFACE,
            "panel": theme.PANEL,
            "panel_hi": theme.PANEL_HI,
            "ink_primary": theme.INK_PRIMARY,
            "ink_secondary": theme.INK_SECONDARY,
            "ink_muted": theme.INK_MUTED,
            "gridline": theme.GRIDLINE,
            "baseline": theme.BASELINE,
            "accent": theme.ACCENT,
            "accent_text": theme.ACCENT_TEXT,
            "accent_dim": theme.ACCENT_DIM,
            "accent_hover": theme.ACCENT_HOVER,
            "ref": theme.REF_COLOUR,
            "cmp": theme.CMP_COLOUR,
            "timing_session_best": theme.TIMING_SESSION_BEST,
            "timing_personal_best": theme.TIMING_PERSONAL_BEST,
            "timing_slower": theme.TIMING_SLOWER,
        },
        "series": list(theme.SERIES),
        "compound_colours": dict(config.COMPOUND_COLOURS),
        "session_labels": dict(config.SESSION_LABELS),
        "race_sessions": list(config.RACE_SESSIONS),
        "plotly_config": theme.PLOTLY_CONFIG,
        "fuel_effect_s_per_kg": config.FUEL_EFFECT_S_PER_KG,
    }


# --------------------------------------------------------------------------
# Manifest and circuits
# --------------------------------------------------------------------------

# ``config.FEATURED_SESSIONS`` names its target as a Streamlit page path.
_PAGE_ROUTES = {
    "pages/1_Corner_Analysis.py": "/corner-analysis",
    "pages/2_Race_Arc.py": "/race-arc",
}


@app.get("/api/manifest")
def get_manifest():
    manifest = cache.load_manifest()
    if manifest.empty:
        return {"sessions": [], "years": [], "featured": []}

    featured = [
        {
            "slug": item["slug"],
            "route": _PAGE_ROUTES.get(item["page"], "/"),
            "title": item["title"],
            "blurb": item["blurb"],
            "params": item["params"],
        }
        for item in cache.featured_sessions()
    ]
    return {
        "sessions": records(manifest),
        "years": sorted((int(y) for y in manifest["year"].unique()), reverse=True),
        "featured": featured,
    }


@app.get("/api/circuits")
def get_circuits():
    """One outline per distinct circuit, for the home page's hero reel."""
    gallery = cache.load_circuit_gallery()
    return {
        "circuits": [{"name": name, **_outline(track)}
                     for name, track in gallery.items()]
    }


@app.get("/api/opener")
def get_opener(prefer: str = Query("", description="Comma-separated session types")):
    """The session to open on when the URL does not say otherwise.

    ``prefer`` is what keeps Race Arc from landing on a qualifying session it
    cannot analyse - the same job ``prefer_sessions`` does in the Streamlit
    session picker.
    """
    wanted = tuple(s for s in prefer.split(",") if s) or None
    key = cache.featured_key(wanted)
    if key is None:
        return {"slug": None}
    return {"slug": key.slug, "year": key.year, "round": key.round,
            "session": key.session}


# --------------------------------------------------------------------------
# Session detail
# --------------------------------------------------------------------------

@app.get("/api/session")
def get_session(slug: str = Query(..., description="e.g. 2024/12_Q")):
    """Everything a page needs about a session that is not a chart."""
    _session_key(slug)
    meta = _meta(slug)
    is_race = str(meta["session"]) in config.RACE_SESSIONS

    telemetry = cache.load_telemetry(slug)
    results = cache.load_artefact(slug, "results")
    laps = cache.load_laps(slug)

    drivers = cache.driver_options(telemetry, results)

    # Compound comes from the lap table rather than the telemetry artefact,
    # matching what the lap selector labelled laps with before.
    compound_by_driver: dict[str, dict[float, str]] = {}
    if not laps.empty and "Compound" in laps.columns:
        for drv, frame in laps.groupby("Driver", observed=True):
            compound_by_driver[str(drv)] = dict(
                zip(frame["LapNumber"].astype(float),
                    frame["Compound"].astype(str))
            )

    driver_laps: dict[str, list[dict]] = {}
    if not telemetry.empty:
        wanted = ["LapTime_s", "LapKind", "CovStart", "CovEnd"]
        have = [c for c in wanted if c in telemetry.columns]
        for drv, frame in telemetry.groupby("Driver", observed=True):
            grouped = frame.groupby("LapNumber")[have].first()
            # Races and sprints: chronological, natural for choosing which
            # stint to compare. Qualifying: fastest first, the order
            # ``store.get_lap`` defaults to.
            grouped = (grouped.sort_index() if is_race
                       else grouped.sort_values("LapTime_s"))
            cpd = compound_by_driver.get(str(drv), {})
            driver_laps[str(drv)] = [
                {
                    "lap": int(lap_no),
                    "time_s": jsonable(row.get("LapTime_s")),
                    "compound": cpd.get(float(lap_no)),
                    "kind": str(row.get("LapKind", "flying")),
                    "cov_start": jsonable(row.get("CovStart", 0.0)),
                    "cov_end": jsonable(row.get("CovEnd", 1.0)),
                }
                for lap_no, row in grouped.iterrows()
            ]

    summary, reasons = cache.load_lap_availability(slug)

    return {
        "slug": slug,
        "meta": jsonable(meta.to_dict()),
        "session_label": config.SESSION_LABELS.get(str(meta["session"]),
                                                   str(meta["session"])),
        "is_race": is_race,
        "has_telemetry": not telemetry.empty,
        "drivers": drivers,
        "driver_laps": driver_laps,
        "trackmap": {**_trackmap_xy(slug),
                     "corners": jsonable(corner_labels_data(cache.load_artefact(slug, "corners")))},
        "results": records(results),
        "availability": {"summary": jsonable(summary), "reasons": records(reasons)},
    }


# --------------------------------------------------------------------------
# Home
# --------------------------------------------------------------------------

@app.get("/api/home")
def get_home(slug: str = Query(...)):
    """The Home page's derived tables and proof-strip figures."""
    _session_key(slug)
    meta = _meta(slug)
    laps = cache.load_laps(slug)
    results = cache.load_artefact(slug, "results")
    weather = cache.load_artefact(slug, "weather")
    track = cache.load_artefact(slug, "trackmap")

    fastest = None
    if not laps.empty and laps["LapTime_s"].notna().any():
        row = laps.loc[laps["LapTime_s"].idxmin()]
        fastest = {"driver": str(row["Driver"]),
                   "lap_time": cache.fmt_laptime(row["LapTime_s"])}

    track_temp = None
    if not weather.empty and "TrackTemp" in weather.columns:
        track_temp = {
            "mean": jsonable(weather["TrackTemp"].mean()),
            "swing": jsonable(weather["TrackTemp"].iloc[-1]
                              - weather["TrackTemp"].iloc[0]),
        }

    # ---- classification -------------------------------------------------
    classification: list[dict] = []
    classification_columns: list[str] = []
    if not results.empty:
        cols = {"Position": "Pos", "Abbreviation": "Driver",
                "FullName": "Name", "TeamName": "Team"}
        show = results[[c for c in cols if c in results.columns]].rename(columns=cols)
        if "Q3_s" in results.columns and results["Q3_s"].notna().any():
            show["Q1"] = results["Q1_s"].map(cache.fmt_laptime)
            show["Q2"] = results["Q2_s"].map(cache.fmt_laptime)
            show["Q3"] = results["Q3_s"].map(cache.fmt_laptime)
        elif "Points" in results.columns:
            show["Points"] = results["Points"]
        if "Pos" in show.columns:
            show["Pos"] = pd.to_numeric(show["Pos"], errors="coerce").astype("Int64")
        classification_columns = list(show.columns)
        classification = records(show)

    # ---- fastest lap per driver ----------------------------------------
    # Every row here *is* a driver's own best lap, so the top row is the only
    # purple one - which is exactly what a timing screen shows.
    fastest_per_driver: list[dict] = []
    if not laps.empty and laps["LapTime_s"].notna().any():
        best = (laps.dropna(subset=["LapTime_s"])
                    .sort_values("LapTime_s")
                    .groupby("Driver", as_index=False)
                    .first()
                    .sort_values("LapTime_s")
                    .head(20))
        gaps = best["LapTime_s"] - best["LapTime_s"].iloc[0]
        fastest_per_driver = [
            {
                "Driver": str(d),
                "Lap time": cache.fmt_laptime(t),
                "Gap": "—" if i == 0 else f"+{g:.3f}",
                "Tyre": str(c),
                "Status": "Session best" if i == 0 else "Personal best",
            }
            for i, (d, t, c, g) in enumerate(
                zip(best["Driver"], best["LapTime_s"], best["Compound"], gaps))
        ]

    return {
        "slug": slug,
        "meta": jsonable(meta.to_dict()),
        "session_label": config.SESSION_LABELS.get(str(meta["session"]),
                                                   str(meta["session"])),
        "fastest": fastest,
        "track_temp": track_temp,
        "classification": classification,
        "classification_columns": classification_columns,
        "fastest_per_driver": fastest_per_driver,
        "circuit_lead": cache.circuit_key(track, cache.load_circuit_gallery()),
    }


# --------------------------------------------------------------------------
# Corner analysis
# --------------------------------------------------------------------------

def _display_names(name_a: str, name_b: str,
                   lap_a: int, lap_b: int) -> tuple[str, str]:
    """The labels the charts and tables use for the two laps.

    Comparing a driver against themselves needs the lap number to tell the two
    traces apart, and comparing the *same* lap needs an explicit Ref/Cmp tag.
    """
    display_a = f"{name_a} L{lap_a}" if name_a == name_b else name_a
    display_b = f"{name_b} L{lap_b}" if name_a == name_b else name_b
    if display_a == display_b:
        display_a += " (Ref)"
        display_b += " (Cmp)"
    return display_a, display_b


def _resolve_laps(slug: str, driver_a: str, driver_b: str,
                  lap_a: float | None, lap_b: float | None):
    telemetry = cache.load_telemetry(slug)
    if telemetry.empty:
        raise HTTPException(404, "No telemetry stored for this session")
    frame_a = store.get_lap(telemetry, driver_a, lap_a)
    frame_b = store.get_lap(telemetry, driver_b, lap_b)
    if frame_a.empty or frame_b.empty:
        raise HTTPException(404, "One of the selected laps has no stored telemetry")
    return frame_a, frame_b


@app.get("/api/corner-analysis")
def get_corner_analysis(
    slug: str = Query(...),
    driver1: str = Query(...),
    driver2: str = Query(...),
    lap1: float | None = Query(None),
    lap2: float | None = Query(None),
):
    _session_key(slug)
    # Checked before any lap is resolved: where the markers are broken there is
    # no comparison to show, and build_segments would return a tidy-looking
    # tiling built on them rather than fail. Refusing with the reason is the
    # same contract as the audited-filtering rule - a gap that is reported is
    # recoverable, one that is silently wrong is not.
    issues = corner_data_issues(cache.load_artefact(slug, "corners"))
    if issues:
        raise HTTPException(
            409,
            "Corner analysis is unavailable for this session because "
            + "; ".join(issues)
            + ". Lap times, strategy and degradation are unaffected.",
        )

    frame_a, frame_b = _resolve_laps(slug, driver1, driver2, lap1, lap2)
    segments = cache.load_segments(slug)

    lap_a_num = int(frame_a["LapNumber"].iloc[0])
    lap_b_num = int(frame_b["LapNumber"].iloc[0])
    display_a, display_b = _display_names(driver1, driver2, lap_a_num, lap_b_num)

    comparison = compare_corners(frame_a, frame_b, segments,
                                 name_a=display_a, name_b=display_b)
    summary = summarise_comparison(comparison)

    # ``compare_corners`` suffixes its per-driver columns with the display
    # names, so the column set is data-dependent. Normalise to stable keys
    # here rather than making the client reconstruct the suffixes.
    def col(base: str, suffix: str):
        name = f"{base}_{suffix}"
        return comparison[name] if name in comparison.columns else pd.Series(
            [None] * len(comparison), index=comparison.index)

    table = pd.DataFrame({
        "label": comparison["label"],
        "kind": comparison["kind"],
        "delta_s": comparison["delta_s"],
        "cum_delta_s": (comparison["cum_delta_s"]
                        if "cum_delta_s" in comparison.columns
                        else comparison["delta_s"].cumsum()),
        "comparable": comparison.get("comparable", True),
        "v_min_a": col("v_min", display_a),
        "v_min_b": col("v_min", display_b),
        "v_min_diff": comparison.get("v_min_diff"),
        "brake_m_a": col("brake_m", display_a),
        "brake_m_b": col("brake_m", display_b),
        "brake_m_diff": comparison.get("brake_m_diff"),
    })

    t_a = frame_a["LapTime_s"].iloc[0]
    t_b = frame_b["LapTime_s"].iloc[0]
    has_gap = bool(pd.notna(t_a) and pd.notna(t_b))

    laps_df = cache.load_laps(slug)
    h2h = (head_to_head(laps_df, driver1, driver2)
           if driver1 != driver2 and not laps_df.empty else pd.DataFrame())

    sector_fractions = []
    for driver, frame in ((driver1, frame_a), (driver2, frame_b)):
        timed = laps_df[(laps_df["Driver"] == driver)
                        & (laps_df["LapNumber"] == frame["LapNumber"].iloc[0])]
        if timed.empty:
            continue
        s1, s2 = timed.iloc[0][["Sector1Time_s", "Sector2Time_s"]]
        elapsed = frame["t"].to_numpy(dtype=float)
        distance = frame["Distance"].to_numpy(dtype=float)
        length = float(frame["LapLength"].iloc[0])
        if (pd.notna(s1) and pd.notna(s2) and length > 0
                and np.isfinite(elapsed).all() and np.isfinite(distance).all()
                and elapsed[0] <= s1 < s1 + s2 <= elapsed[-1]):
            sector_fractions = [float(np.interp(t, elapsed, distance) / length)
                                for t in (s1, s1 + s2)]
            break

    return {
        "driver_a": driver1,
        "driver_b": driver2,
        "lap_a": lap_a_num,
        "lap_b": lap_b_num,
        "display_a": display_a,
        "display_b": display_b,
        "time_a": jsonable(t_a),
        "time_b": jsonable(t_b),
        "has_gap": has_gap,
        "gap": jsonable(t_b - t_a) if has_gap else None,
        "summary": jsonable(summary),
        "segments": records(table),
        # The ghost replay places each car at the distance its own telemetry
        # says it had reached; that is the `t` channel and nothing else.
        "ghost": {
            "t_a": [jsonable(v) for v in frame_a["t"].to_numpy()],
            "t_b": [jsonable(v) for v in frame_b["t"].to_numpy()],
        },
        "sector_fractions": sector_fractions,
        "head_to_head": records(h2h),
    }


# --------------------------------------------------------------------------
# Race arc
# --------------------------------------------------------------------------

# Bounds for the two fuel sliders. They are wide enough to hold anything the
# UI can send and anything a season could plausibly use, and narrow enough to
# refuse a request rather than serve it: a bare `float` accepted "nan" and
# "inf", which fell through the fuel correction into a 500.
MAX_FUEL_EFFECT_S_PER_KG = 1.0
MAX_FUEL_KG = 200.0


@app.get("/api/race-arc")
def get_race_arc(
    slug: str = Query(...),
    fuel_effect: float = Query(config.FUEL_EFFECT_S_PER_KG,
                               ge=0.0, le=MAX_FUEL_EFFECT_S_PER_KG),
    fuel_kg: float | None = Query(None, gt=0.0, le=MAX_FUEL_KG),
):
    _session_key(slug)
    meta = _meta(slug)
    year = int(meta["year"])
    total_laps = int(meta["total_laps"])
    is_race = str(meta["session"]) in config.RACE_SESSIONS
    if fuel_kg is None:
        fuel_kg = config.race_fuel_kg(year)

    laps = cache.load_laps(slug)
    if laps.empty:
        raise HTTPException(404, "No lap data available for this session")

    prepared, rejections = cache.load_prepared(
        slug, year, total_laps, fuel_effect, fuel_kg)
    stints, deg_summary = cache.load_stint_fits(
        slug, year, total_laps, fuel_effect, fuel_kg)

    # ---- degradation ----------------------------------------------------
    deg_block = {
        "summary": records(deg_summary),
        "stints": records(stints),
        "rejections": records(rejections),
        "n_prepared": int(len(prepared)),
        "n_all_laps": int(len(laps)),
        "n_cliffs": int(stints["has_cliff"].sum()) if not stints.empty else 0,
    }

    # ---- evolution ------------------------------------------------------
    evo_block: dict[str, Any] = {"available": False, "result": None,
                                 "naive_gain": None, "has_progression": False}
    if not is_race:
        progression = evolution.session_best_progression(laps)
        evo_block["has_progression"] = not progression.empty
        if not progression.empty:
            evo_block["session_best_gain"] = jsonable(
                progression["session_best_s"].iloc[0]
                - progression["session_best_s"].iloc[-1])
    elif not prepared.empty:
        result = cache.load_evolution(slug, year, total_laps, fuel_effect, fuel_kg)
        if result is not None:
            naive = evolution.naive_evolution(prepared, total_laps=total_laps)
            naive_gain = (float(naive["evolution_s"].iloc[0]
                                - naive["evolution_s"].iloc[-1])
                          if not naive.empty else float("nan"))
            evo_block = {
                "available": True,
                "result": {
                    "degradation": records(result["degradation"]),
                    "n_laps": int(result["n_laps"]),
                    "n_drivers": int(result["n_drivers"]),
                    "r_squared": jsonable(result["r_squared"]),
                    "total_gain_s": jsonable(result["total_gain_s"]),
                },
                "naive_gain": jsonable(naive_gain),
                "has_progression": False,
            }

    # ---- strategy -------------------------------------------------------
    strat_block: dict[str, Any] = {}
    if is_race:
        stints_raw = strategy.stint_table(laps)
        pace = strategy.race_pace(prepared)
        loss = strategy.pit_loss(laps)

        # The undercut sliders open on what this race actually measured
        # rather than on a round number.
        default_deg = (float(deg_summary["deg_s_per_lap"].mean())
                       if not deg_summary.empty else 0.10)
        offsets = (degradation.compound_offsets(deg_summary)
                   if not deg_summary.empty else pd.DataFrame())
        default_advantage = 0.8
        if not offsets.empty and "offset_s" in offsets.columns:
            adv = float(abs(offsets["offset_s"].min()))
            if 0.1 <= adv <= 2.5:
                default_advantage = adv

        strat_block = {
            "stints": records(stints_raw),
            "n_stints": int(len(stints_raw)),
            "pace": records(pace),
            "pace_display": [
                {
                    "Driver": str(r["Driver"]),
                    "Laps": int(r["laps"]),
                    "Median": cache.fmt_laptime(r["median_s"]),
                    "Gap": "—" if i == 0 else f"+{r['gap_to_best_s']:.3f}",
                }
                for i, (_, r) in enumerate(pace.iterrows())
            ],
            "pit_loss": jsonable(loss),
            "gap_drivers": pace["Driver"].astype(str).tolist() if not pace.empty else [],
            "default_deg_rate": jsonable(default_deg),
            "default_advantage": jsonable(default_advantage),
        }

    return {
        "slug": slug,
        "year": year,
        "total_laps": total_laps,
        "is_race": is_race,
        "fuel_effect": fuel_effect,
        "fuel_kg": fuel_kg,
        "degradation": deg_block,
        "evolution": evo_block,
        "strategy": strat_block,
    }


@app.get("/api/undercut")
def get_undercut(
    gap_s: float = Query(1.5),
    advantage: float = Query(0.8),
    deg_rate: float = Query(0.10),
):
    table = strategy.undercut_gain(
        gap_to_rival_s=gap_s,
        fresh_tyre_advantage_s=advantage,
        deg_s_per_lap=deg_rate,
    )
    return {
        "table": records(table),
        "breakeven_lap": strategy.breakeven_lap(table),
        "max_gain": jsonable(strategy.max_undercut_gain(table)),
    }


# Chart routes live in their own module; imported last so it can reuse the
# helpers above without a circular import.
from api import charts  # noqa: E402,F401

app.include_router(charts.router)


# --------------------------------------------------------------------------
# The built frontend
#
# Mounted last, so every /api route above is matched first. Present only when
# `npm run build` has been run: in development Vite serves the app on :5173 and
# proxies /api here, so there is nothing to mount and nothing to go stale.
# --------------------------------------------------------------------------

_DIST = REPO_ROOT / "frontend" / "dist"

if _DIST.is_dir():
    from fastapi.responses import FileResponse  # noqa: E402
    from fastapi.staticfiles import StaticFiles  # noqa: E402

    _DIST_REAL = _DIST.resolve()

    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        """Serve the built app, falling back to index.html for client routes.

        ``/corner-analysis`` is a route the browser owns, not a file on disk,
        so a hard refresh there has to return the shell rather than a 404.
        """
        # Containment is checked after resolving, never by reading the string:
        # `Path(base) / "/etc/passwd"` discards the base entirely, so an
        # absolute path escapes without needing a single `..` in it.
        candidate = (_DIST_REAL / path).resolve()
        if path and candidate.is_relative_to(_DIST_REAL) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_DIST_REAL / "index.html")

else:
    @app.get("/", include_in_schema=False)
    def no_build():
        """A bare API with no built frontend still has to say where to go."""
        return {
            "status": "online",
            "service": "ApexTrace REST API",
            "docs": "/docs",
            "frontend": "not built - run `npm run build` in frontend/, "
                        "or `scripts/run_dev.py` for the dev server on :5173",
        }
