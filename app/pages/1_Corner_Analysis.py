"""Corner-by-corner comparison of two drivers - the flagship view."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import brand  # noqa: E402
from common import (  # noqa: E402
    caption,
    driver_options,
    fmt_laptime,
    load_artefact,
    load_segments,
    load_telemetry,
    page_setup,
    session_header,
    session_picker,
)
from pitwall import store  # noqa: E402
from pitwall.corners import compare_corners, summarise_comparison  # noqa: E402
from pitwall.viz import theme  # noqa: E402
from pitwall.viz.traces import corner_delta_bars, trace_panel  # noqa: E402
from pitwall.viz.trackmap import speed_delta_map  # noqa: E402

page_setup("Corner Analysis")

slug, meta = session_picker(key_prefix="corner")
if slug is None:
    st.stop()

telemetry = load_telemetry(slug)
results = load_artefact(slug, "results")
corners = load_artefact(slug, "corners")
track = load_artefact(slug, "trackmap")
segments = load_segments(slug)

session_header(meta, "Corner Analysis", track=track)

if telemetry.empty:
    st.warning("No telemetry stored for this session.")
    st.stop()

drivers = driver_options(telemetry, results)
if len(drivers) < 2:
    st.warning("Need at least two drivers with telemetry to compare.")
    st.stop()

# ---------------------------------------------------------------- selection

params = st.query_params
preset = [d for d in str(params.get("drivers", "")).split(",") if d in drivers]

with st.sidebar:
    brand.kicker("Comparison")
    name_a = st.selectbox("Reference", drivers,
                          index=drivers.index(preset[0]) if preset else 0)
    others = [d for d in drivers if d != name_a]
    default_b = preset[1] if len(preset) > 1 and preset[1] in others else others[0]
    name_b = st.selectbox("Compare", others, index=others.index(default_b))

    def _lap_choice(driver: str, label: str) -> float | None:
        laps = (telemetry[telemetry["Driver"] == driver]
                .groupby("LapNumber")["LapTime_s"].first().sort_values())
        if len(laps) <= 1:
            return None
        options = list(laps.index)
        return st.selectbox(
            label, options, index=0,
            format_func=lambda n: f"Lap {int(n)} — {fmt_laptime(laps[n])}",
        )

    lap_a_no = _lap_choice(name_a, f"{name_a} lap")
    lap_b_no = _lap_choice(name_b, f"{name_b} lap")

st.query_params["drivers"] = f"{name_a},{name_b}"

lap_a = store.get_lap(telemetry, name_a, lap_a_no)
lap_b = store.get_lap(telemetry, name_b, lap_b_no)
if lap_a.empty or lap_b.empty:
    st.warning("One of the selected laps has no stored telemetry.")
    st.stop()

comparison = compare_corners(lap_a, lap_b, segments, name_a=name_a, name_b=name_b)
summary = summarise_comparison(comparison)

# ---------------------------------------------------------------- headline

t_a, t_b = lap_a["LapTime_s"].iloc[0], lap_b["LapTime_s"].iloc[0]
gap = t_b - t_a
faster, slower = (name_a, name_b) if gap > 0 else (name_b, name_a)

c1, c2, c3, c4 = st.columns(4)
c1.metric(f"{name_a} lap", fmt_laptime(t_a))
c2.metric(f"{name_b} lap", fmt_laptime(t_b), f"{gap:+.3f} s", delta_color="inverse")
c3.metric("Gained in corners", f"{summary['corner_delta_s']:+.3f} s",
          help=f"Total time {name_b} gains (−) or loses (+) inside the corner windows.")
c4.metric("Gained on straights", f"{summary['straight_delta_s']:+.3f} s",
          help="The remainder of the lap: power, drag and slipstream effects.")

st.markdown(
    f"<div style='background:{theme.PANEL};border-radius:10px;padding:14px 18px;"
    f"color:{theme.INK_SECONDARY};line-height:1.6'>"
    f"<b style='color:{theme.INK_PRIMARY}'>{faster}</b> is "
    f"<b style='color:{theme.INK_PRIMARY}'>{abs(gap):.3f} s</b> faster overall. "
    f"The corners account for <b style='color:{theme.INK_PRIMARY}'>"
    f"{summary['corner_delta_s']:+.3f} s</b> and the straights for "
    f"<b style='color:{theme.INK_PRIMARY}'>{summary['straight_delta_s']:+.3f} s</b>."
    "</div>",
    unsafe_allow_html=True,
)

brand.kerb()

# ---------------------------------------------------------------- map + biggest swings

map_col, list_col = st.columns([3, 2], gap="large")

with map_col:
    st.subheader("Where the time changes hands")
    st.plotly_chart(
        speed_delta_map(track, lap_a, lap_b, name_a=name_a, name_b=name_b,
                        corners=corners),
        width="stretch", config=theme.PLOTLY_CONFIG,
    )
    caption(
        "Each point is a place on the lap, coloured by which driver is pulling "
        "away there — not by the running total, so one big corner does not "
        "stain the rest of the lap. Grey means neither driver is gaining."
    )

with list_col:
    st.subheader("Biggest swings")
    # Same two hues as the track map beside it - blue where the compared
    # driver is gaining, red where the reference is - so the list and the map
    # can be read against each other without relearning the colours.
    for title, items, colour in (
        (f"{name_b} gains most", summary["biggest_gains"], "#3987e5"),
        (f"{name_b} loses most", summary["biggest_losses"], "#e66767"),
    ):
        brand.kicker(title)
        if not items:
            st.markdown(f"<div style='color:{theme.INK_MUTED}'>—</div>",
                        unsafe_allow_html=True)
        for item in items:
            st.markdown(
                f"<div style='display:flex;justify-content:space-between;"
                f"padding:7px 0;border-bottom:1px solid {theme.GRIDLINE}'>"
                f"<span style='color:{theme.INK_PRIMARY}'>{item['label']}</span>"
                f"<span style='color:{colour};font-variant-numeric:tabular-nums'>"
                f"{item['delta_s']:+.3f} s</span></div>",
                unsafe_allow_html=True,
            )
        st.write("")

brand.kerb()

# ---------------------------------------------------------------- traces

st.subheader("Telemetry")
st.plotly_chart(
    trace_panel(lap_a, lap_b, segments, name_a=name_a, name_b=name_b),
    width="stretch", config=theme.PLOTLY_CONFIG,
)
caption(
    f"{name_a} solid, {name_b} dashed — the line style carries the identity as well "
    f"as the colour. Dotted verticals mark corner apexes; the red bands are "
    f"{name_a}'s braking zones. In the bottom panel a falling line means "
    f"{name_b} is gaining."
)

brand.kerb()

# ---------------------------------------------------------------- per-corner table

st.subheader("Corner by corner")
st.plotly_chart(
    corner_delta_bars(comparison, name_a=name_a, name_b=name_b),
    width="stretch", config=theme.PLOTLY_CONFIG,
)
caption(
    "Time won or lost in every segment of the lap. Because corners and straights "
    "together tile the whole lap, these bars sum exactly to the lap-time gap "
    f"({comparison['delta_s'].sum():+.3f} s)."
)

only_corners = st.toggle("Corners only", value=True)
view = comparison[comparison["kind"] == "corner"] if only_corners else comparison

table = pd.DataFrame({
    "Segment": view["label"],
    "Δ time (s)": view["delta_s"].round(3),
    f"Min speed {name_a}": view["v_min_" + name_a].round(0),
    f"Min speed {name_b}": view["v_min_" + name_b].round(0),
    "Δ min speed": view["v_min_diff"].round(1),
    f"Brake point {name_a} (m)": view["brake_m_" + name_a].round(0),
    f"Brake point {name_b} (m)": view["brake_m_" + name_b].round(0),
    "Δ brake (m)": view["brake_m_diff"].round(0),
})
st.dataframe(
    table.style.format(precision=3, na_rep="—")
         .background_gradient(subset=["Δ time (s)"], cmap="RdBu_r"),
    width="stretch", hide_index=True, height=560,
)
caption(
    "A positive Δ brake means the compared driver braked later. Blanks are corners "
    "taken flat — no braking event to report."
)
