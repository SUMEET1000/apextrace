"""Race strategy: stints, pace, measured pit loss and the undercut."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import (  # noqa: E402
    caption,
    fmt_laptime,
    load_laps,
    page_setup,
    session_header,
    session_picker,
)
from pitwall import degradation, strategy  # noqa: E402
from pitwall.viz import theme  # noqa: E402
from pitwall.viz.charts import (  # noqa: E402
    gap_chart,
    race_pace_box,
    stint_chart,
    undercut_chart,
)

page_setup("Race Strategy")

slug, meta = session_picker(key_prefix="strat")
if slug is None:
    st.stop()

session_header(meta)

if meta["session"] != "R":
    st.info("Strategy analysis needs a **Race** session. Pick one in the sidebar.")
    st.stop()

laps = load_laps(slug)
if laps.empty:
    st.warning("No lap data for this session.")
    st.stop()

year = int(meta["year"])
total_laps = int(meta["total_laps"])

prepared, _ = degradation.prepare(laps, year=year, total_laps=total_laps)
stints_raw = strategy.stint_table(laps)
pace = strategy.race_pace(prepared)
loss = strategy.pit_loss(laps)
deg_summary = degradation.compound_summary(degradation.fit_all_stints(prepared))

# ---------------------------------------------------------------- headline

c1, c2, c3, c4 = st.columns(4)
c1.metric("Pit loss", f"{loss.get('pit_loss_s', float('nan')):.1f} s",
          f"in-lap {loss.get('in_lap_s', 0):.1f} + out-lap {loss.get('out_lap_s', 0):.1f}",
          delta_color="off",
          help="Measured as the excess of in- and out-laps over each driver's own "
               "clean pace, so it nets out how quick the car was to begin with.")
c2.metric("Pit stops", int(loss.get("n_stops", 0)))
if not pace.empty:
    c3.metric("Best race pace", pace["Driver"].iloc[0],
              f"{fmt_laptime(pace['median_s'].iloc[0])} median", delta_color="off")
c4.metric("Stints", len(stints_raw))

st.divider()

# ---------------------------------------------------------------- stints

st.subheader("Stint timeline")
st.plotly_chart(stint_chart(stints_raw), width="stretch", config=theme.PLOTLY_CONFIG)
caption(
    "Each bar is a stint, labelled with the compound's initial as well as coloured "
    "by it. Drivers are ordered by the lap they reached, so retirements sort to "
    "the bottom."
)

st.divider()

# ---------------------------------------------------------------- pace

left, right = st.columns([3, 2], gap="large")

with left:
    st.subheader("Race pace")
    st.plotly_chart(race_pace_box(prepared, pace), width="stretch",
                    config=theme.PLOTLY_CONFIG)
    caption(
        "Distribution of clean, fuel-corrected lap times, fastest median first. "
        "A box rather than a bar because consistency is part of race pace — a tall "
        "box means a driver who was quick sometimes."
    )

with right:
    st.subheader("Pace ranking")
    if pace.empty:
        st.info("Not enough clean laps.")
    else:
        view = pd.DataFrame({
            "Driver": pace["Driver"],
            "Laps": pace["laps"],
            "Median": [fmt_laptime(v) for v in pace["median_s"]],
            "Gap": ["—" if i == 0 else f"+{g:.3f}"
                    for i, g in enumerate(pace["gap_to_best_s"])],
        })
        st.dataframe(view, width="stretch", hide_index=True, height=430)

st.divider()

# ---------------------------------------------------------------- gaps

st.subheader("Gap to leader")
all_drivers = pace["Driver"].tolist() if not pace.empty else []
chosen = st.multiselect("Drivers", all_drivers, default=all_drivers[:5])
st.plotly_chart(gap_chart(strategy.gap_evolution(laps), chosen),
                width="stretch", config=theme.PLOTLY_CONFIG)
caption(
    "Cumulative time behind the race leader. Vertical steps are pit stops; a line "
    "converging on zero is a driver closing in."
)

st.divider()

# ---------------------------------------------------------------- undercut

st.subheader("Undercut calculator")

st.markdown(
    f"<div style='background:{theme.PANEL};border-radius:10px;padding:14px 18px;"
    f"color:{theme.INK_SECONDARY};line-height:1.6'>"
    "<b style='color:#fff'>The pit loss cancels out, and that is the point.</b> "
    "You box and immediately concede the pit loss; a few laps later your rival boxes "
    "and concedes exactly the same. What is left is the time your fresher tyre took "
    "out of them in between. Charging the driver the full pit loss — the intuitive "
    "version — makes every undercut look impossible, because a ~20 s stop dwarfs any "
    "tyre advantage. Pit loss still decides what traffic you rejoin into, but not "
    "this comparison."
    "</div>",
    unsafe_allow_html=True,
)
st.write("")

default_deg = (float(deg_summary["deg_s_per_lap"].mean())
               if not deg_summary.empty else 0.10)

u1, u2, u3 = st.columns(3)
gap_s = u1.slider("Gap to rival (s)", 0.0, 8.0, 1.5, 0.1,
                  help="How far behind you are before stopping.")
advantage = u2.slider("Fresh-tyre advantage (s/lap)", 0.1, 2.5, 0.8, 0.1,
                      help="How much quicker a new tyre is on its first lap.")
deg_rate = u3.slider("Degradation (s/lap)", 0.01, 0.40, round(default_deg, 2), 0.01,
                     help=f"Defaults to this race's measured mean of "
                          f"{default_deg:.3f} s/lap.")

table = strategy.undercut_gain(
    gap_to_rival_s=gap_s, fresh_tyre_advantage_s=advantage, deg_s_per_lap=deg_rate,
)
breakeven = strategy.breakeven_lap(table)
max_gain = strategy.max_undercut_gain(table)

m1, m2 = st.columns([1, 2])
with m1:
    if breakeven:
        st.metric("Undercut works after", f"{breakeven} laps",
                  f"max gain {max_gain:.2f} s", delta_color="off")
    else:
        st.metric("Undercut works after", "never",
                  f"max gain {max_gain:.2f} s < {gap_s:.1f} s gap", delta_color="off")
with m2:
    st.plotly_chart(undercut_chart(table, gap_s), width="stretch",
                    config=theme.PLOTLY_CONFIG)

caption(
    "The per-lap gain decays as the new tyre ages, floored at zero — a tyre that has "
    "used up its edge stops gaining rather than handing time back. Where the curve "
    "crosses the dashed line, the undercut has worked."
)
