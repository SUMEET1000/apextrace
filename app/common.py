"""Shared app plumbing: cached loaders, session selection, deep links.

This is the only place Streamlit meets the analysis library. Caching lives
here rather than in ``pitwall.store`` so the library stays importable from
tests and notebooks.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pitwall import store  # noqa: E402
from pitwall.config import SESSION_LABELS  # noqa: E402
from pitwall.corners import build_segments  # noqa: E402
from pitwall.ingest import SessionKey  # noqa: E402
from pitwall.viz import theme  # noqa: E402

PAGE_ICON = "\U0001F3CE"


def page_setup(title: str) -> None:
    st.set_page_config(page_title=f"{title} · Pit Wall",
                       page_icon=PAGE_ICON, layout="wide")
    st.markdown(
        f"""
        <style>
          .stApp {{ background: {theme.SURFACE}; }}
          [data-testid="stMetricValue"] {{ font-variant-numeric: tabular-nums; }}
          .pw-caption {{ color: {theme.INK_MUTED}; font-size: 0.82rem;
                         margin: -0.5rem 0 1.1rem 0; line-height: 1.45; }}
          .pw-kicker {{ color: {theme.INK_MUTED}; font-size: 0.75rem;
                        letter-spacing: 0.12em; text-transform: uppercase; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def caption(text: str) -> None:
    """A one-line plain-English note under a chart: what it shows, what to look for."""
    st.markdown(f'<div class="pw-caption">{text}</div>', unsafe_allow_html=True)


# --------------------------------------------------------------------------
# Cached loaders
# --------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def load_manifest() -> pd.DataFrame:
    return store.read_manifest()


@st.cache_data(show_spinner=False)
def load_artefact(slug: str, name: str) -> pd.DataFrame:
    return store.read_artefact(store.key_from_slug(slug), name)


@st.cache_data(show_spinner="Loading telemetry…")
def load_telemetry(slug: str) -> pd.DataFrame:
    return store.read_telemetry(store.key_from_slug(slug))


@st.cache_data(show_spinner=False)
def load_laps(slug: str) -> pd.DataFrame:
    """Lap table with timedeltas restored - the schema the models expect."""
    return store.read_laps(store.key_from_slug(slug))


@st.cache_data(show_spinner=False)
def load_segments(slug: str) -> pd.DataFrame:
    """Corner + straight tiling for a session, built once and cached."""
    telemetry = load_telemetry(slug)
    corners = load_artefact(slug, "corners")
    if telemetry.empty:
        return pd.DataFrame()
    return build_segments(corners, float(telemetry["LapLength"].median()))


# --------------------------------------------------------------------------
# Session selection (shared by every page, with deep links)
# --------------------------------------------------------------------------

def session_picker(*, key_prefix: str = "sel") -> tuple[str, pd.Series] | tuple[None, None]:
    """Sidebar year/event/session picker backed by the manifest.

    Selections are mirrored into the URL so a particular view can be shared
    as a link - the single biggest thing that makes an analysis tool actually
    get passed around.
    """
    manifest = load_manifest()
    if manifest.empty:
        st.error(
            "No sessions have been built yet. Run:\n\n"
            "```\npython scripts/build_dataset.py --years 2024 --sessions Q R\n```"
        )
        return None, None

    params = st.query_params
    with st.sidebar:
        st.markdown('<div class="pw-kicker">Session</div>', unsafe_allow_html=True)

        years = sorted(manifest["year"].unique(), reverse=True)
        default_year = int(params.get("year", years[0]))
        year = st.selectbox("Season", years,
                            index=years.index(default_year) if default_year in years else 0,
                            key=f"{key_prefix}_year")

        in_year = manifest[manifest["year"] == year].sort_values("round")
        events = in_year[["round", "event_name"]].drop_duplicates()
        labels = [f"R{r.round:02d}  {r.event_name}" for r in events.itertuples()]
        default_round = int(params.get("round", events["round"].iloc[0]))
        round_list = events["round"].tolist()
        idx = round_list.index(default_round) if default_round in round_list else 0
        chosen = st.selectbox("Event", labels, index=idx, key=f"{key_prefix}_event")
        rnd = round_list[labels.index(chosen)]

        available = in_year[in_year["round"] == rnd]["session"].tolist()
        default_session = params.get("session", available[0])
        session = st.radio(
            "Session",
            available,
            index=available.index(default_session) if default_session in available else 0,
            format_func=lambda s: SESSION_LABELS.get(s, s),
            horizontal=True,
            key=f"{key_prefix}_session",
        )

    key = SessionKey(int(year), int(rnd), str(session))
    st.query_params.update({"year": str(year), "round": str(rnd), "session": session})

    row = manifest[manifest["slug"] == key.slug]
    if row.empty:
        st.error(f"Session {key.slug} is in the picker but missing from the manifest.")
        return None, None
    return key.slug, row.iloc[0]


def session_header(meta: pd.Series) -> None:
    st.markdown('<div class="pw-kicker">Pit Wall · F1 Telemetry Analysis</div>',
                unsafe_allow_html=True)
    st.title(f"{meta['event_name']} {int(meta['year'])}")
    st.markdown(
        f"<span style='color:{theme.INK_SECONDARY}'>"
        f"{SESSION_LABELS.get(meta['session'], meta['session'])} · "
        f"{meta['location']}, {meta['country']}</span>",
        unsafe_allow_html=True,
    )


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
