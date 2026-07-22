"""Tyre degradation: how fast each compound gives up lap time."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import brand  # noqa: E402
from common import (  # noqa: E402
    caption,
    load_artefact,
    load_laps,
    page_setup,
    session_header,
    session_picker,
)
from pitwall import degradation  # noqa: E402
from pitwall.config import FUEL_EFFECT_S_PER_KG, race_fuel_kg  # noqa: E402
from pitwall.viz import theme  # noqa: E402
from pitwall.viz.charts import degradation_bars, degradation_scatter  # noqa: E402

page_setup("Tyre Degradation")

slug, meta = session_picker(key_prefix="deg")
if slug is None:
    st.stop()

_track = load_artefact(slug, "trackmap")
session_header(meta, "Tyre Degradation", track=_track)

if meta["session"] != "R":
    st.info(
        "Degradation is measured over a race stint. Pick a **Race** session in "
        "the sidebar — a qualifying session has no long runs to fit."
    )
    st.stop()

laps = load_laps(slug)
if laps.empty:
    st.warning("No lap data for this session.")
    st.stop()

year = int(meta["year"])
total_laps = int(meta["total_laps"])

# ---------------------------------------------------------------- assumptions

with st.sidebar:
    brand.kicker("Model assumptions")
    fuel_effect = st.slider(
        "Fuel effect (s per kg)", 0.020, 0.045, FUEL_EFFECT_S_PER_KG, 0.001,
        help="Lap time gained per kg of fuel burned. Community estimates sit "
             "around 0.030–0.035 and vary by circuit.",
    )
    fuel_kg = st.slider(
        "Starting fuel (kg)", 40.0, 120.0, float(race_fuel_kg(year)), 5.0,
        help="The 2026 regulations cut race fuel substantially.",
    )

prepared, rejections = degradation.prepare(
    laps, year=year, total_laps=total_laps,
    fuel_effect_s_per_kg=fuel_effect, fuel_kg=fuel_kg,
)

if prepared.empty:
    st.warning("No laps survived cleaning for this session.")
    st.stop()

stints = degradation.fit_all_stints(prepared)
summary = degradation.compound_summary(stints)

# ---------------------------------------------------------------- headline

cols = st.columns(max(len(summary), 1) + 1)
for col, row in zip(cols, summary.itertuples()):
    ci = f"95% CI {row.ci_low:.3f} – {row.ci_high:.3f}"
    col.metric(f"{row.Compound.title()} degradation",
               f"{row.deg_s_per_lap:.3f} s/lap", ci, delta_color="off",
               help=f"{row.n_stints} stints, {row.n_laps} laps.")
cols[-1].metric("Clean laps used", f"{len(prepared):,}",
                f"{len(prepared) / max(len(laps), 1):.0%} of all laps",
                delta_color="off")

if not summary.empty and len(summary) > 1:
    softest = summary.iloc[0]
    hardest = summary.iloc[-1]
    brand.verdict(
        f"The <b>{softest.Compound.lower()}</b> gives up "
        f"<b>{softest.deg_s_per_lap:.3f} s/lap</b> and the "
        f"<b>{hardest.Compound.lower()}</b> "
        f"<b>{hardest.deg_s_per_lap:.3f} s/lap</b> — a difference of "
        f"{abs(softest.deg_s_per_lap - hardest.deg_s_per_lap):.3f} s per lap "
        f"of stint length."
    )

brand.kerb()

# ---------------------------------------------------------------- charts

st.subheader("Pace against tyre age")
st.plotly_chart(degradation_scatter(prepared, stints),
                width="stretch", config=theme.PLOTLY_CONFIG)
caption(
    "Each point is one clean lap, fuel-corrected to end-of-race weight; the line "
    "is the inverse-variance weighted fit across all stints on that compound. "
    "Compounds are shown in separate panels rather than by colour alone."
)

left, right = st.columns([2, 3], gap="large")

with left:
    st.subheader("Degradation rate")
    st.plotly_chart(degradation_bars(summary), width="stretch",
                    config=theme.PLOTLY_CONFIG)
    caption("Bars show the pooled rate; whiskers are 95% confidence intervals. "
            "A short stint carries a wide interval and is weighted accordingly.")

with right:
    st.subheader("What was excluded, and why")
    if rejections.empty:
        st.success("Every lap passed the cleaning filters.")
    else:
        st.dataframe(
            rejections.rename(columns={"reason": "Reason", "count": "Laps",
                                       "pct_of_input": "% of all laps"}),
            width="stretch", hide_index=True,
        )
    caption(
        "Traffic, safety cars and pit laps distort lap time for reasons that have "
        "nothing to do with the tyre. Every exclusion is listed rather than "
        "applied silently."
    )

brand.kerb()

# ---------------------------------------------------------------- per stint

st.subheader("Stint by stint")

cliffs = stints[stints["has_cliff"]] if not stints.empty else pd.DataFrame()
if not cliffs.empty:
    st.markdown(
        f"<span style='color:{theme.INK_SECONDARY}'>"
        f"<b style='color:{theme.INK_PRIMARY}'>{len(cliffs)}</b> of {len(stints)} stints "
        f"show a statistically better quadratic fit with upward curvature — "
        f"degradation accelerating rather than holding a constant rate, which is "
        f"what a tyre 'cliff' looks like in the data.</span>",
        unsafe_allow_html=True,
    )

if stints.empty:
    st.info("No stint had enough clean laps to fit.")
else:
    table = pd.DataFrame({
        "Driver": stints["Driver"],
        "Stint": stints["Stint"].astype(int),
        "Tyre": stints["Compound"],
        "Laps": stints["n_laps"],
        "Deg (s/lap)": stints["deg_s_per_lap"].round(3),
        "95% CI low": stints["ci_low"].round(3),
        "95% CI high": stints["ci_high"].round(3),
        "R²": stints["r_squared"].round(2),
        "Cliff": stints["has_cliff"],
    })
    st.dataframe(table, width="stretch", hide_index=True, height=460)
    caption(
        "Fitted with HC3 robust standard errors — lap-time scatter is not constant "
        "through a stint, and the naive errors would overstate confidence. "
        "Stints shorter than five clean laps are not fitted at all."
    )
