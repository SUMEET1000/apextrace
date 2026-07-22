"""Figures for the degradation, evolution and strategy pages.

House rule throughout: **no dual y-axes**. Where two quantities of different
units need to be read together (lap time and track temperature), they are
stacked as separate panels on a shared x-axis. Two arbitrary scalings on one
frame invite comparisons the data does not support.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from pitwall.viz import theme


def _rgba(hex_colour: str, alpha: float) -> str:
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


# --------------------------------------------------------------- degradation

def degradation_scatter(laps: pd.DataFrame, stints: pd.DataFrame,
                        *, height: int = 480) -> go.Figure:
    """Fuel-corrected lap time against tyre age, one panel per compound.

    Faceting by compound rather than colouring by it means the reader never
    has to separate two compounds by hue - which matters here, because the
    official soft and intermediate colours are not distinguishable under
    red/green colour blindness.
    """
    if laps.empty:
        return go.Figure()

    compounds = [c for c in laps["Compound"].dropna().unique()]
    compounds.sort(key=lambda c: -len(laps[laps["Compound"] == c]))
    if not compounds:
        return go.Figure()

    fig = make_subplots(rows=1, cols=len(compounds), shared_yaxes=True,
                        subplot_titles=compounds, horizontal_spacing=0.03)

    for i, compound in enumerate(compounds, start=1):
        subset = laps[laps["Compound"] == compound]
        colour = theme.compound_colour(compound)
        fig.add_trace(go.Scatter(
            x=subset["TyreLife"], y=subset["LapTime_corrected_s"],
            mode="markers", name=compound, showlegend=False,
            marker=dict(size=5, color=_rgba(colour, 0.45),
                        line=dict(width=0)),
            hovertemplate=("%{customdata}<br>tyre age %{x:.0f} laps"
                           "<br>%{y:.3f} s<extra></extra>"),
            customdata=subset["Driver"],
        ), row=1, col=i)

        fit = stints[stints["Compound"] == compound] if not stints.empty else pd.DataFrame()
        if not fit.empty:
            weights = 1.0 / fit["std_err"].clip(lower=1e-6) ** 2
            slope = float((fit["deg_s_per_lap"] * weights).sum() / weights.sum())
            intercept = float((fit["intercept_s"] * weights).sum() / weights.sum())
            age = np.linspace(subset["TyreLife"].min(), subset["TyreLife"].max(), 50)
            fig.add_trace(go.Scatter(
                x=age, y=intercept + slope * age, mode="lines",
                line=dict(color=colour, width=2.5), showlegend=False,
                hovertemplate=f"{slope:+.3f} s/lap<extra></extra>",
            ), row=1, col=i)

        fig.update_xaxes(title_text="Tyre age (laps)", row=1, col=i)

    fig.update_yaxes(title_text="Fuel-corrected lap time (s)", row=1, col=1)
    theme.apply(fig, height=height)
    fig.update_layout(hovermode="closest")
    for annotation in fig.layout.annotations[:len(compounds)]:
        annotation.update(font=dict(color=theme.INK_SECONDARY, size=12))
    return fig


def degradation_bars(summary: pd.DataFrame, *, height: int = 340) -> go.Figure:
    """Degradation rate per compound with 95% confidence intervals.

    The interval is the point of the chart: a rate without one invites the
    reader to treat a six-lap stint as though it were as certain as a
    twenty-five-lap one.
    """
    if summary.empty:
        return go.Figure()

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=summary["Compound"], y=summary["deg_s_per_lap"],
        marker=dict(color=[theme.compound_colour(c) for c in summary["Compound"]]),
        error_y=dict(
            type="data", symmetric=False,
            array=summary["ci_high"] - summary["deg_s_per_lap"],
            arrayminus=summary["deg_s_per_lap"] - summary["ci_low"],
            color=theme.INK_SECONDARY, thickness=1.5, width=6,
        ),
        customdata=np.stack([summary["n_stints"], summary["n_laps"]], axis=-1),
        hovertemplate=("<b>%{x}</b><br>%{y:.3f} s/lap"
                       "<br>%{customdata[0]} stints, %{customdata[1]} laps<extra></extra>"),
        showlegend=False,
    ))
    fig.update_yaxes(title_text="Degradation (s per lap)", rangemode="tozero")
    theme.apply(fig, height=height)
    fig.update_layout(hovermode="closest", bargap=0.45)
    return fig


# ----------------------------------------------------------------- evolution

def evolution_curve(curve: pd.DataFrame, naive: pd.DataFrame | None = None,
                    *, height: int = 420) -> go.Figure:
    """Track evolution with its confidence band, against the naive estimate."""
    if curve.empty:
        return go.Figure()

    fig = go.Figure()
    band = _rgba(theme.SERIES[0], 0.18)
    fig.add_trace(go.Scatter(
        x=np.concatenate([curve["progress"], curve["progress"][::-1]]),
        y=np.concatenate([curve["ci_high"], curve["ci_low"][::-1]]),
        fill="toself", fillcolor=band, line=dict(width=0),
        hoverinfo="skip", showlegend=False,
    ))
    fig.add_trace(go.Scatter(
        x=curve["progress"], y=curve["evolution_s"], mode="lines",
        name="Pooled model (tyre & fuel removed)",
        line=dict(color=theme.SERIES[0], width=2.5),
        hovertemplate="%{y:+.3f} s at %{x:.0%} distance<extra></extra>",
    ))

    if naive is not None and not naive.empty:
        fig.add_trace(go.Scatter(
            x=naive["progress"], y=naive["evolution_s"], mode="lines",
            name="Naive trend (tyre & fuel confounded)",
            line=dict(color=theme.SERIES[1], width=2, dash="dash"),
            hovertemplate="%{y:+.3f} s<extra></extra>",
        ))

    fig.add_hline(y=0, line=dict(color=theme.BASELINE, width=1))
    fig.update_xaxes(title_text="Session progress", tickformat=".0%")
    fig.update_yaxes(title_text="Lap time vs session start (s)")
    theme.apply(fig, height=height)
    return fig


def evolution_with_temperature(curve: pd.DataFrame, weather: pd.DataFrame,
                               *, height: int = 520) -> go.Figure:
    """Evolution above, track temperature below, on a shared x-axis.

    Deliberately two panels rather than one frame with two y-axes: seconds
    and degrees have no common scale, and overlaying them would let the
    apparent correlation be set by whatever ranges happened to be chosen.
    """
    if curve.empty:
        return go.Figure()

    has_weather = (not weather.empty and "TrackTemp" in weather.columns
                   and "Time_s" in weather.columns)
    rows = 2 if has_weather else 1
    fig = make_subplots(
        rows=rows, cols=1, shared_xaxes=True, vertical_spacing=0.09,
        row_heights=[0.62, 0.38] if has_weather else [1.0],
        subplot_titles=(["Track evolution (s gained)", "Track temperature (°C)"]
                        if has_weather else ["Track evolution (s gained)"]),
    )

    fig.add_trace(go.Scatter(
        x=np.concatenate([curve["progress"], curve["progress"][::-1]]),
        y=np.concatenate([curve["ci_high"], curve["ci_low"][::-1]]),
        fill="toself", fillcolor=_rgba(theme.SERIES[0], 0.18),
        line=dict(width=0), hoverinfo="skip", showlegend=False,
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=curve["progress"], y=curve["evolution_s"], mode="lines",
        name="Track evolution", line=dict(color=theme.SERIES[0], width=2.5),
        hovertemplate="%{y:+.3f} s<extra></extra>", showlegend=False,
    ), row=1, col=1)

    if has_weather:
        w = weather.dropna(subset=["TrackTemp"]).copy()
        span = w["Time_s"].max() - w["Time_s"].min()
        w["progress"] = (w["Time_s"] - w["Time_s"].min()) / (span if span else 1)
        fig.add_trace(go.Scatter(
            x=w["progress"], y=w["TrackTemp"], mode="lines",
            name="Track temp", line=dict(color=theme.SERIES[3], width=2),
            hovertemplate="%{y:.1f} °C<extra></extra>", showlegend=False,
        ), row=2, col=1)
        fig.update_yaxes(title_text="°C", row=2, col=1)

    fig.update_xaxes(title_text="Session progress", tickformat=".0%", row=rows, col=1)
    fig.update_yaxes(title_text="Seconds", row=1, col=1)
    theme.apply(fig, height=height)
    for annotation in fig.layout.annotations[:rows]:
        annotation.update(font=dict(color=theme.INK_SECONDARY, size=12),
                          x=0, xanchor="left")
    return fig


# ------------------------------------------------------------------ strategy

def stint_chart(stints: pd.DataFrame, *, height: int = 640) -> go.Figure:
    """Stint timeline: one row per driver, bars coloured and labelled by compound."""
    if stints.empty:
        return go.Figure()

    order = (stints.groupby("Driver", observed=True)["end_lap"].max()
                   .sort_values(ascending=False).index.tolist())

    fig = go.Figure()
    seen: set[str] = set()
    for row in stints.itertuples():
        compound = str(row.Compound)
        fig.add_trace(go.Bar(
            y=[row.Driver], x=[row.laps], base=[row.start_lap - 1],
            orientation="h", name=compound,
            legendgroup=compound, showlegend=compound not in seen,
            marker=dict(color=theme.compound_colour(compound),
                        line=dict(color=theme.SURFACE, width=2)),
            # Compound named in text on the bar, so the reading never depends
            # on telling two official tyre colours apart.
            text=compound[0] if row.laps >= 4 else "",
            textposition="inside", insidetextanchor="middle",
            textfont=dict(color=theme.SURFACE, size=10),
            hovertemplate=(f"<b>{row.Driver}</b><br>{compound}<br>"
                           f"laps {row.start_lap:.0f}–{row.end_lap:.0f} "
                           f"({row.laps} laps)<extra></extra>"),
        ))
        seen.add(compound)

    fig.update_layout(barmode="stack")
    fig.update_yaxes(categoryorder="array", categoryarray=order)
    fig.update_xaxes(title_text="Lap")
    theme.apply(fig, height=height)
    fig.update_layout(hovermode="closest")
    return fig


def race_pace_box(laps: pd.DataFrame, pace: pd.DataFrame,
                  *, height: int = 520) -> go.Figure:
    """Distribution of clean fuel-corrected lap times per driver, fastest first.

    A box rather than a bar: race pace is a distribution, and consistency is
    part of what the reader is looking for.
    """
    if laps.empty or pace.empty:
        return go.Figure()

    order = pace["Driver"].tolist()
    fig = go.Figure()
    for driver in order:
        subset = laps[laps["Driver"] == driver]
        fig.add_trace(go.Box(
            y=subset["LapTime_corrected_s"], name=driver,
            marker=dict(color=theme.SERIES[0], size=4),
            line=dict(width=1.4), fillcolor=_rgba(theme.SERIES[0], 0.22),
            boxpoints=False, showlegend=False,
            hovertemplate=f"<b>{driver}</b><br>%{{y:.3f}} s<extra></extra>",
        ))
    fig.update_yaxes(title_text="Fuel-corrected lap time (s)")
    fig.update_xaxes(categoryorder="array", categoryarray=order)
    theme.apply(fig, height=height)
    fig.update_layout(hovermode="closest")
    return fig


def gap_chart(gaps: pd.DataFrame, drivers: list[str], *, height: int = 480) -> go.Figure:
    """Gap to the leader over the race for a chosen handful of drivers."""
    if gaps.empty or not drivers:
        return go.Figure()
    fig = go.Figure()
    for i, driver in enumerate(drivers[:8]):
        subset = gaps[gaps["Driver"] == driver]
        fig.add_trace(go.Scatter(
            x=subset["LapNumber"], y=subset["gap_s"], mode="lines",
            name=driver, line=dict(color=theme.series_colour(i), width=2),
            hovertemplate=f"<b>{driver}</b><br>lap %{{x:.0f}}: +%{{y:.1f}} s<extra></extra>",
        ))
    fig.update_xaxes(title_text="Lap")
    fig.update_yaxes(title_text="Gap to leader (s)", autorange="reversed")
    theme.apply(fig, height=height)
    return fig


def undercut_chart(table: pd.DataFrame, gap_s: float, *, height: int = 400) -> go.Figure:
    """Cumulative undercut gain against the gap that has to be closed."""
    if table.empty:
        return go.Figure()
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=table["laps_after_stop"], y=table["cumulative_gain_s"],
        mode="lines+markers", name="Cumulative gain from fresh tyres",
        line=dict(color=theme.SERIES[0], width=2.5), marker=dict(size=6),
        hovertemplate="after %{x} laps: %{y:.2f} s gained<extra></extra>",
    ))
    fig.add_hline(
        y=gap_s, line=dict(color=theme.SERIES[1], width=2, dash="dash"),
        annotation_text=f"gap to rival {gap_s:.1f} s",
        annotation_position="top left",
        annotation_font=dict(color=theme.SERIES[1], size=11),
    )
    fig.update_xaxes(title_text="Laps after the stop", dtick=2)
    fig.update_yaxes(title_text="Time gained (s)", rangemode="tozero")
    theme.apply(fig, height=height)
    return fig
