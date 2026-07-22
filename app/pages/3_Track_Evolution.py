"""Track evolution: separating a rubbering-in circuit from tyre and fuel."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import (  # noqa: E402
    caption,
    load_artefact,
    load_laps,
    page_setup,
    session_header,
    session_picker,
)
from pitwall import degradation, evolution  # noqa: E402
from pitwall.viz import theme  # noqa: E402
from pitwall.viz.charts import evolution_curve, evolution_with_temperature  # noqa: E402

page_setup("Track Evolution")

slug, meta = session_picker(key_prefix="evo")
if slug is None:
    st.stop()

session_header(meta)

laps = load_laps(slug)
weather = load_artefact(slug, "weather")
if laps.empty:
    st.warning("No lap data for this session.")
    st.stop()

year = int(meta["year"])
total_laps = int(meta["total_laps"])

# ---------------------------------------------------------------- the problem

with st.expander("Why this needs a model, not a trend line", expanded=False):
    st.markdown(
        """
Within a single stint, tyre age and session time are the same column of
numbers — lap 12 of a stint is both *12 laps of wear* and *12 laps later in
the race*. From one stint alone, "the tyre got slower" and "the track got
faster" cannot be told apart, and fitting a trend through lap times measures
their sum, not track evolution.

What breaks the tie is that **drivers do not pit at the same time**. Across
the field a 10-lap-old tyre shows up on lap 15 for one driver and lap 40 for
another, so pooling all drivers decorrelates tyre age from session time and
both effects become separately estimable:

```
corrected_laptime ~ C(Driver) + C(Compound):TyreLife + spline(progress)
```

* `C(Driver)` absorbs raw pace differences between cars
* `C(Compound):TyreLife` absorbs degradation, per compound
* `spline(progress)` is everything left that depends only on *when* in the
  session it is — and that is track evolution

Fuel is removed beforehand rather than fitted, because fuel load is almost a
perfect linear function of lap number and would otherwise be swallowed by the
evolution term.
        """
    )

# ---------------------------------------------------------------- qualifying

if meta["session"] != "R":
    st.subheader("Session best over time")
    progression = evolution.session_best_progression(laps)
    if progression.empty:
        st.info("No timing data to plot.")
    else:
        import plotly.graph_objects as go
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=progression["session_minutes"], y=progression["lap_time_s"],
            mode="markers", name="Individual laps",
            marker=dict(size=5, color=theme.INK_MUTED, opacity=0.5),
            hovertemplate="%{y:.3f} s<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=progression["session_minutes"], y=progression["session_best_s"],
            mode="lines", name="Session best",
            line=dict(color=theme.SERIES[0], width=2.5),
            hovertemplate="best %{y:.3f} s<extra></extra>",
        ))
        fig.update_xaxes(title_text="Minutes into session")
        fig.update_yaxes(title_text="Lap time (s)")
        theme.apply(fig, height=460)
        st.plotly_chart(fig, width="stretch", config=theme.PLOTLY_CONFIG)
        gain = (progression["session_best_s"].iloc[0]
                - progression["session_best_s"].iloc[-1])
        caption(
            f"The session best improved by {gain:.3f} s. In qualifying everyone runs "
            f"fresh rubber and low fuel, so this descriptive view is the honest one — "
            f"the pooled model needs the varied stint lengths only a race provides."
        )
    st.stop()

# ---------------------------------------------------------------- race model

prepared, _ = degradation.prepare(laps, year=year, total_laps=total_laps)
result = evolution.fit_evolution(prepared, total_laps=total_laps)

if result is None:
    st.warning(
        "This session does not support the pooled model — it needs at least "
        "40 clean laps across 4 drivers with varied stint timing."
    )
    st.stop()

naive = evolution.naive_evolution(prepared, total_laps=total_laps)
naive_gain = (naive["evolution_s"].iloc[0] - naive["evolution_s"].iloc[-1]
              if not naive.empty else float("nan"))

gain = result["total_gain_s"]
# Positive means the circuit got quicker. The naive trend usually comes out
# the other way, because degradation dominates the raw lap times.
wrong_direction = (naive_gain < 0) != (gain < 0)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Track evolution", f"{gain:+.3f} s",
          "faster by the end" if gain > 0 else "slower by the end",
          delta_color="off")
c2.metric("Naive estimate", f"{naive_gain:+.3f} s",
          "wrong direction" if wrong_direction else f"off by {abs(naive_gain - gain):.3f} s",
          delta_color="off",
          help="A trend through lap times alone, which confounds track "
               "evolution with tyre degradation and fuel burn.")
c3.metric("Model fit", f"R² {result['r_squared']:.3f}",
          f"{result['n_laps']:,} laps · {result['n_drivers']} drivers",
          delta_color="off")
c4.metric("Spline knots", "4", "on session progress", delta_color="off")

verdict = (
    f"A naive trend through the same laps reports "
    f"<b style='color:{theme.INK_PRIMARY}'>{naive_gain:+.3f} s</b> — "
    + ("the opposite direction. Degradation dominates the raw lap times, so the "
       "circuit appears to be getting slower even while it is genuinely rubbering in."
       if wrong_direction else
       "a different figure, because tyre wear and fuel burn are folded into it.")
)
st.markdown(
    f"<div style='background:{theme.PANEL};border-radius:10px;padding:14px 18px;"
    f"color:{theme.INK_SECONDARY};line-height:1.6'>"
    f"With tyre age and fuel accounted for, the circuit itself was worth "
    f"<b style='color:{theme.INK_PRIMARY}'>{abs(gain):.3f} s</b> of lap time by the "
    f"end of the race. {verdict}</div>",
    unsafe_allow_html=True,
)

st.divider()

st.subheader("Evolution curve")
st.plotly_chart(evolution_curve(result["curve"], naive),
                width="stretch", config=theme.PLOTLY_CONFIG)
caption(
    "A falling line means the track is getting quicker. The shaded band is the "
    "95% confidence interval on the fitted curve. The dashed line is the naive "
    "estimate, shown to make the size of the confounding visible."
)

st.divider()

left, right = st.columns([3, 2], gap="large")

with left:
    st.subheader("Evolution against track temperature")
    st.plotly_chart(evolution_with_temperature(result["curve"], weather),
                    width="stretch", config=theme.PLOTLY_CONFIG)
    caption(
        "Two panels on a shared x-axis rather than two y-scales on one frame: "
        "seconds and degrees have no common scale, and overlaying them would let "
        "the apparent correlation be set by the axis ranges chosen."
    )

with right:
    st.subheader("Degradation implied by the model")
    deg = result["degradation"]
    if deg.empty:
        st.info("No compound terms estimated.")
    else:
        view = pd.DataFrame({
            "Compound": deg["Compound"],
            "Deg (s/lap)": deg["deg_s_per_lap"].round(3),
            "95% CI low": deg["ci_low"].round(3),
            "95% CI high": deg["ci_high"].round(3),
        })
        st.dataframe(view, width="stretch", hide_index=True)
    caption(
        "These come out of the pooled model as a by-product. They are estimated "
        "independently of the per-stint fits on the Tyre Degradation page — when "
        "two different methods agree, the assumptions behind both look safer."
    )
