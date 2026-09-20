"""Cached loaders — the API's equivalent of ``app/common.py``.

Caching lives here rather than in ``pitwall.store`` for the same reason it
lived in ``app/common.py``: the library stays importable from tests and
notebooks with no cache semantics attached.

The cache bounds are ported deliberately and are load-bearing. ``lru_cache``
takes the place of ``st.cache_data``; ``maxsize`` takes the place of
``max_entries``. See each loader for why its number is what it is.

**Single worker only.** These caches are per-process, so running uvicorn with
``--workers N`` would give each worker its own copy — N times the memory for
no extra hit rate, on the one loader that holds ~74 MB per entry.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
import pandas as pd

from pitwall import config, store
from pitwall.corners import build_segments
from pitwall.ingest import SessionKey
from pitwall.transforms import telemetry_coverage


# --------------------------------------------------------------------------
# Artefact loaders
# --------------------------------------------------------------------------

@lru_cache(maxsize=1)
def load_manifest() -> pd.DataFrame:
    return store.read_manifest()


@lru_cache(maxsize=256)
def load_artefact(slug: str, name: str) -> pd.DataFrame:
    return store.read_artefact(store.key_from_slug(slug), name)


# ``maxsize`` because this is the one loader whose entries are large: a race
# holds ~74 MB decoded, so an unbounded cache grows by that much for every
# session anyone browses to and never gives it back.
#
# Two, not four. Render's free tier is a 512 MB box that also holds Python,
# pandas and FastAPI; four decoded frames is ~296 MB of it. See DECISIONS.md
# ADR-001. tests/test_api.py pins the bound so it cannot drift back.
@lru_cache(maxsize=2)
def load_telemetry(slug: str) -> pd.DataFrame:
    return store.read_telemetry(store.key_from_slug(slug))


@lru_cache(maxsize=64)
def load_laps(slug: str) -> pd.DataFrame:
    """Lap table with timedeltas restored - the schema the models expect."""
    return store.read_laps(store.key_from_slug(slug))


@lru_cache(maxsize=64)
def load_lap_availability(slug: str) -> tuple[dict, pd.DataFrame]:
    """Which of a session's laps a lap selector can offer, and why the rest cannot.

    Reads the *encoded* telemetry artefact and keeps only the two identifying
    columns: the reconciliation needs nothing else, and decoding a race's full
    traces here would duplicate a ~10 MB frame in the cache for a row count.
    """
    key = store.key_from_slug(slug)
    stored = store.read_artefact(key, "telemetry")
    if not stored.empty:
        stored = stored[["Driver", "LapNumber"]]
    return telemetry_coverage(
        load_laps(slug), stored,
        stores_all_laps=config.LAPS_PER_DRIVER.get(
            key.session, config.LAPS_PER_DRIVER_DEFAULT) == 0,
    )


@lru_cache(maxsize=64)
def load_segments(slug: str) -> pd.DataFrame:
    """Corner + straight tiling for a session, built once and cached."""
    telemetry = load_telemetry(slug)
    corners = load_artefact(slug, "corners")
    if telemetry.empty:
        return pd.DataFrame()
    return build_segments(corners, float(telemetry["LapLength"].median()))


# --------------------------------------------------------------------------
# Circuit gallery
# --------------------------------------------------------------------------

def _outline_signature(track: pd.DataFrame, points: int = 200) -> np.ndarray:
    """A trackmap reduced to a position- and scale-free sample of its outline.

    Comparable point-for-point across seasons because every trackmap is stored
    on the same distance grid: row *i* is the same fraction of a lap from the
    start/finish line, in the same direction, whichever year built it.
    """
    x = track["X"].to_numpy(dtype="float64")
    y = track["Y"].to_numpy(dtype="float64")
    x, y = x - x.mean(), y - y.mean()
    scale = max(np.ptp(x), np.ptp(y)) or 1.0
    idx = np.linspace(0, len(x) - 1, points).astype(int)
    return np.stack([x[idx] / scale, y[idx] / scale], axis=1)


@lru_cache(maxsize=1)
def load_circuit_gallery() -> dict[str, pd.DataFrame]:
    """One trackmap per distinct circuit, in calendar order.

    The home page's hero reel. Distinct is decided on the outline rather than
    on `location`, because that column is a spelling and not an identity - see
    ``config.CIRCUIT_MATCH_TOL``. Matching on it put Miami and Monaco into the
    reel twice each, which reads as a bug whatever the labels say. The first
    calendar entry wins, so a circuit keeps the name of its earliest season.
    """
    manifest = load_manifest()
    if manifest.empty:
        return {}
    firsts = manifest.sort_values(["year", "round"]).drop_duplicates("location")
    gallery: dict[str, pd.DataFrame] = {}
    seen: list[np.ndarray] = []
    for row in firsts.itertuples():
        track = load_artefact(str(row.slug), "trackmap")
        if track.empty or not {"X", "Y"}.issubset(track.columns) or len(track) < 3:
            continue
        signature = _outline_signature(track)
        if any(np.abs(signature - other).mean() < config.CIRCUIT_MATCH_TOL
               for other in seen):
            continue
        seen.append(signature)
        gallery[str(row.location)] = track
    return gallery


def circuit_key(track: pd.DataFrame,
                gallery: dict[str, pd.DataFrame]) -> str | None:
    """Which gallery entry is this trackmap, or None if it is not in there.

    Matched on the outline for the same reason the gallery is built on it: a
    session at "Miami Gardens" has to resolve to the gallery's "Miami", or the
    reel silently stops opening on the circuit the page is describing.
    """
    if track is None or track.empty or not {"X", "Y"}.issubset(track.columns) \
            or len(track) < 3:
        return None
    signature = _outline_signature(track)
    for name, other in gallery.items():
        if np.abs(signature - _outline_signature(other)).mean() \
                < config.CIRCUIT_MATCH_TOL:
            return name
    return None


# --------------------------------------------------------------------------
# Cached models
#
# Tyre Degradation, Track Evolution and Race Strategy all start from the same
# ``degradation.prepare`` call, and Tyre Degradation and Race Strategy both go
# on to fit every stint. Uncached, that ran on each request *and* on every
# widget interaction - a slider tick refitted all stints before it could
# redraw. Keying on the slug plus the stated assumptions means the three views
# share one entry at the default settings.
#
# ``maxsize`` is what keeps this bounded: the fuel sliders are continuous, so
# an unbounded cache would retain a full lap table per slider position.
# --------------------------------------------------------------------------

@lru_cache(maxsize=24)
def load_prepared(slug: str, year: int, total_laps: int,
                  fuel_effect_s_per_kg: float,
                  fuel_kg: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    """``degradation.prepare`` for a session: (clean fuel-corrected laps, audit).

    Callers pass the fuel assumptions explicitly rather than relying on the
    defaults, so that a view using the defaults and a view using sliders left
    at their default positions land on the *same* cache entry instead of
    computing the identical answer twice.
    """
    from pitwall import degradation

    return degradation.prepare(
        load_laps(slug), year=year, total_laps=total_laps,
        fuel_effect_s_per_kg=fuel_effect_s_per_kg, fuel_kg=fuel_kg,
    )


@lru_cache(maxsize=24)
def load_stint_fits(slug: str, year: int, total_laps: int,
                    fuel_effect_s_per_kg: float,
                    fuel_kg: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Per-stint degradation fits and their per-compound pooled summary."""
    from pitwall import degradation

    prepared, _ = load_prepared(
        slug, year, total_laps, fuel_effect_s_per_kg, fuel_kg,
    )
    stints = degradation.fit_all_stints(prepared)
    return stints, degradation.compound_summary(stints)


@lru_cache(maxsize=24)
def load_evolution(slug: str, year: int, total_laps: int,
                   fuel_effect_s_per_kg: float, fuel_kg: float) -> dict | None:
    """The pooled track-evolution fit, minus its unserialisable model object.

    ``fit_evolution`` returns the statsmodels results wrapper under ``model``.
    Nothing downstream of the API can use it and it cannot be sent over the
    wire, so it is dropped here rather than at every call site.
    """
    from pitwall import evolution

    prepared, _ = load_prepared(
        slug, year, total_laps, fuel_effect_s_per_kg, fuel_kg,
    )
    if prepared.empty:
        return None
    result = evolution.fit_evolution(prepared, total_laps=total_laps)
    if result is None:
        return None
    return {k: v for k, v in result.items() if k != "model"}


# --------------------------------------------------------------------------
# Shared helpers, ported unchanged from app/common.py
# --------------------------------------------------------------------------

def featured_sessions() -> list[dict]:
    """The entries of ``config.FEATURED_SESSIONS`` this dataset actually has.

    The curated list names sessions by slug; a dataset built with a different
    set of rounds simply has fewer of them, and must not break for it.
    """
    manifest = load_manifest()
    if manifest.empty:
        return []
    built = set(manifest["slug"].astype(str))
    return [f for f in config.FEATURED_SESSIONS if f["slug"] in built]


def featured_key(prefer_sessions: tuple[str, ...] | None = None) -> SessionKey | None:
    """The session the app opens on when the URL does not say otherwise.

    ``prefer_sessions`` is what keeps a page from opening on a session it
    cannot analyse. The curated list leads with a qualifying session because
    Corner Analysis is the best first impression, but Race Arc stops dead on
    anything but a race - landing there greets a first-time visitor with a
    "pick a Race session" notice and an otherwise empty page.
    """
    available = featured_sessions()
    if not available:
        return None
    keys = []
    for entry in available:
        try:
            keys.append(store.key_from_slug(entry["slug"]))
        except Exception:
            # A malformed slug in the curated list is a bad default, not a
            # fatal one - the picker's own first entry is still a working
            # answer, so skip the entry rather than give up on the list.
            continue
    if not keys:
        return None
    if prefer_sessions:
        for key in keys:
            if key.session in prefer_sessions:
                return key
    return keys[0]


def driver_options(telemetry: pd.DataFrame, results: pd.DataFrame) -> list[str]:
    """Drivers with stored telemetry, ordered by session classification."""
    if telemetry.empty:
        return []
    have = set(telemetry["Driver"].astype(str).unique())
    if not results.empty and "Abbreviation" in results.columns:
        ordered = [d for d in results.sort_values("Position")["Abbreviation"].astype(str)
                   if d in have]
        ordered += sorted(have - set(ordered))
        return ordered
    return sorted(have)


def fmt_laptime(seconds: float) -> str:
    """90.123 -> 1:30.123, the way lap times are actually read."""
    if pd.isna(seconds):
        return "—"
    minutes, rest = divmod(float(seconds), 60)
    return f"{int(minutes)}:{rest:06.3f}"
