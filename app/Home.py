"""Pit Wall - entry point and session overview."""

from __future__ import annotations

import pandas as pd
import streamlit as st

import brand
from common import (
    caption,
    fmt_laptime,
    load_artefact,
    load_laps,
    page_setup,
    session_picker,
)
from pitwall.config import SESSION_LABELS
from pitwall.viz import theme

page_setup("Home")

slug, meta = session_picker()
if slug is None:
    st.stop()

results = load_artefact(slug, "results")
laps = load_laps(slug)
weather = load_artefact(slug, "weather")
track = load_artefact(slug, "trackmap")

# ------------------------------------------------------------------- hero

session_name = SESSION_LABELS.get(meta["session"], meta["session"])
fastest = laps.loc[laps["LapTime_s"].idxmin()] if not laps.empty else None

brand.hero(
    title=str(meta["event_name"]).replace(" Grand Prix", "<br>Grand Prix"),
    subtitle=(
        f"{session_name} &nbsp;·&nbsp; {meta['location']}, {meta['country']} "
        f"&nbsp;·&nbsp; {int(meta['year'])}<br>"
        "Corner-by-corner telemetry, tyre degradation and track evolution "
        "from the official Formula 1 timing feed."
    ),
    kicker_text=f"Round {int(meta['round']):02d} · {session_name}",
    art=brand.circuit_svg(track, width=330, height=210),
)

# ---------------------------------------------------------------- headline

c1, c2, c3, c4 = st.columns(4)
c1.metric("Fastest lap",
          fmt_laptime(fastest["LapTime_s"]) if fastest is not None else "—",
          fastest["Driver"] if fastest is not None else None, delta_color="off")
c2.metric("Drivers", int(meta["n_drivers"]))
c3.metric("Laps recorded", f"{int(meta['n_laps']):,}")
if not weather.empty and "TrackTemp" in weather.columns:
    swing = weather["TrackTemp"].iloc[-1] - weather["TrackTemp"].iloc[0]
    c4.metric("Track temp", f"{weather['TrackTemp'].mean():.1f}°C",
              f"{swing:+.1f}°C over session", delta_color="off")
else:
    c4.metric("Track temp", "—")

brand.kerb()

# ---------------------------------------------------------- classification

left, right = st.columns([3, 2], gap="large")

with left:
    brand.kicker("Classification")
    if results.empty:
        st.info("No results available for this session.")
    else:
        table = results.copy()
        cols = {"Position": "Pos", "Abbreviation": "Driver", "FullName": "Name",
                "TeamName": "Team"}
        show = table[[c for c in cols if c in table.columns]].rename(columns=cols)
        if "Q3_s" in table.columns and table["Q3_s"].notna().any():
            show["Q1"] = table["Q1_s"].map(fmt_laptime)
            show["Q2"] = table["Q2_s"].map(fmt_laptime)
            show["Q3"] = table["Q3_s"].map(fmt_laptime)
        elif "Points" in table.columns:
            show["Points"] = table["Points"]
        if "Pos" in show.columns:
            show["Pos"] = pd.to_numeric(show["Pos"], errors="coerce").astype("Int64")
        st.dataframe(show.set_index("Pos") if "Pos" in show else show,
                     width="stretch", height=520)

with right:
    brand.kicker("Fastest lap per driver")
    if laps.empty:
        st.info("No lap data.")
    else:
        best = (laps.dropna(subset=["LapTime_s"])
                    .sort_values("LapTime_s")
                    .groupby("Driver", as_index=False)
                    .first()
                    .sort_values("LapTime_s")
                    .head(20))
        gaps = best["LapTime_s"] - best["LapTime_s"].iloc[0]
        st.dataframe(
            pd.DataFrame({
                "Driver": best["Driver"].to_numpy(),
                "Lap time": [fmt_laptime(v) for v in best["LapTime_s"]],
                "Gap": ["—" if i == 0 else f"+{g:.3f}" for i, g in enumerate(gaps)],
                "Tyre": best["Compound"].to_numpy(),
            }),
            width="stretch", hide_index=True, height=520,
        )
        caption("Tyre compound is shown as text, not colour alone — the official "
                "compound colours are indistinguishable under red/green colour "
                "blindness.")

brand.kerb()

# ------------------------------------------------------------- what's here

brand.kicker("The analysis")

cards = [
    ("01", "Corner Analysis",
     "Two drivers, corner by corner: braking points, apex speed, throttle "
     "application, and the seconds each corner is worth."),
    ("02", "Tyre Degradation",
     "Fuel-corrected pace against tyre age, per compound, with confidence "
     "intervals and cliff detection."),
    ("03", "Track Evolution",
     "How much of the pace gain was the circuit rubbering in — separated "
     "from tyre wear and fuel burn."),
    ("04", "Race Strategy",
     "Stints, race pace, measured pit loss, and an undercut calculator."),
]
for col, (num, title, body) in zip(st.columns(4), cards):
    with col:
        st.markdown(
            f'<div class="pw-card"><div class="pw-card-num">{num}</div>'
            f'<div class="pw-card-title">{title}</div>'
            f'<div class="pw-card-body">{body}</div></div>',
            unsafe_allow_html=True,
        )

brand.flag_strip()

st.markdown(
    f"<div style='color:{theme.INK_MUTED};font-size:.78rem'>"
    f"Data: FastF1 — official Formula 1 timing feed · "
    f"telemetry resampled to {int(meta['grid_points'])} points per lap · "
    f"validated against official sector times to ±3.2 m."
    f"</div>",
    unsafe_allow_html=True,
)
