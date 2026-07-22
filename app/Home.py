"""Pit Wall - entry point and session overview."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from common import (
    caption,
    fmt_laptime,
    load_artefact,
    load_telemetry,
    page_setup,
    session_header,
    session_picker,
)
from pitwall.config import SESSION_LABELS
from pitwall.viz import theme

page_setup("Home")

slug, meta = session_picker()
if slug is None:
    st.stop()

session_header(meta)

results = load_artefact(slug, "results")
laps = load_artefact(slug, "laps")
weather = load_artefact(slug, "weather")
telemetry = load_telemetry(slug)

# ---------------------------------------------------------------- headline

fastest = laps.loc[laps["LapTime_s"].idxmin()] if not laps.empty else None

c1, c2, c3, c4 = st.columns(4)
c1.metric("Fastest lap", fmt_laptime(fastest["LapTime_s"]) if fastest is not None else "—",
          fastest["Driver"] if fastest is not None else None)
c2.metric("Drivers", int(meta["n_drivers"]))
c3.metric("Laps recorded", int(meta["n_laps"]))
if not weather.empty and "TrackTemp" in weather.columns:
    c4.metric("Track temp", f"{weather['TrackTemp'].mean():.1f} °C",
              f"{weather['TrackTemp'].iloc[-1] - weather['TrackTemp'].iloc[0]:+.1f} °C over session")
else:
    c4.metric("Track temp", "—")

st.divider()

# ---------------------------------------------------------------- classification

left, right = st.columns([3, 2], gap="large")

with left:
    st.subheader("Classification")
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
    st.subheader("Fastest lap per driver")
    if laps.empty:
        st.info("No lap data.")
    else:
        best = (laps.dropna(subset=["LapTime_s"])
                    .sort_values("LapTime_s")
                    .groupby("Driver", as_index=False)
                    .first())
        best = best.sort_values("LapTime_s").head(20)
        best["Gap"] = best["LapTime_s"] - best["LapTime_s"].iloc[0]
        view = pd.DataFrame({
            "Driver": best["Driver"].to_numpy(),
            "Lap time": [fmt_laptime(v) for v in best["LapTime_s"]],
            "Gap": ["—" if i == 0 else f"+{g:.3f}" for i, g in enumerate(best["Gap"])],
            "Tyre": best["Compound"].to_numpy(),
        })
        st.dataframe(view, width="stretch", hide_index=True, height=520)
        caption("Tyre compound is shown as text, not colour alone — the official "
                "compound colours are not distinguishable for red/green colour blindness.")

st.divider()

# ---------------------------------------------------------------- next steps

st.subheader("Where to go next")
a, b, c, d = st.columns(4)
for col, (icon, title, body) in zip(
    (a, b, c, d),
    [("\U0001F3AF", "Corner Analysis",
      "Compare two drivers corner by corner: braking points, apex speed, and "
      "the seconds each corner is worth."),
     ("\U0001F6DE", "Tyre Degradation",
      "Fuel-corrected pace against tyre age, per compound, with confidence intervals."),
     ("\U0001F321", "Track Evolution",
      "How much of the session's pace gain was the track rubbering in, "
      "separated from tyre and fuel effects."),
     ("\U0001F527", "Race Strategy",
      "Stints, race pace, measured pit loss and an undercut calculator.")],
):
    with col:
        st.markdown(
            f"<div style='background:{theme.PANEL};border-radius:10px;padding:16px;"
            f"height:100%'><div style='font-size:1.4rem'>{icon}</div>"
            f"<div style='color:{theme.INK_PRIMARY};font-weight:600;margin:6px 0'>{title}</div>"
            f"<div style='color:{theme.INK_MUTED};font-size:0.82rem;line-height:1.45'>{body}</div>"
            "</div>",
            unsafe_allow_html=True,
        )

st.caption(
    f"Data: FastF1 (official F1 timing feed) · "
    f"{SESSION_LABELS.get(meta['session'], meta['session'])} · "
    f"telemetry resampled to {int(meta['grid_points'])} points per lap."
)
