"""Figures for the degradation, evolution and strategy pages.

House rule throughout: **no dual y-axes**. Where two quantities of different
units need to be read together (lap time and track temperature), they are
stacked as separate panels on a shared x-axis. Two arbitrary scalings on one
frame invite comparisons the data does not support.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from pitwall.config import DEGRADATION_FACET_COLUMNS
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

    # Wrapped into a grid rather than one long row: see
    # config.DEGRADATION_FACET_COLUMNS for why a four-panel strip is unreadable
    # on a phone.
    n_cols = min(len(compounds), DEGRADATION_FACET_COLUMNS)
    n_rows = math.ceil(len(compounds) / n_cols)
    # Every panel carries its own x-axis title, so a second row needs room for
    # that title, its tick labels and the next panel's heading between them -
    # a tight gap puts the lower compound's name on top of the upper one's axis.
    fig = make_subplots(rows=n_rows, cols=n_cols, shared_yaxes=True,
                        subplot_titles=compounds, horizontal_spacing=0.03,
                        vertical_spacing=0.15 if n_rows > 1 else 0.0)

    for index, compound in enumerate(compounds):
        row, i = divmod(index, n_cols)
        row, i = row + 1, i + 1
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
        ), row=row, col=i)

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
            ), row=row, col=i)

        fig.update_xaxes(title_text="Tyre age (laps)", row=row, col=i)

    for row in range(1, n_rows + 1):
        fig.update_yaxes(title_text="Fuel-corrected lap time (s)", row=row, col=1)
    # A second row needs vertical room of its own, or the panels compress into
    # strips; the caller's `height` is the height of one row of facets.
    theme.apply(fig, height=int(height * (1 + 0.72 * (n_rows - 1))))
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


def session_best_curve(progression: pd.DataFrame, *,
                       height: int = 440) -> go.Figure:
    """Every lap of a session against the running session best.

    The qualifying counterpart to :func:`evolution_curve`. A session with no
    staggered pit stops cannot identify the pooled model, so what is honestly
    available is the observed best-so-far, not a decomposition of it - hence a
    step line over the raw laps rather than a fitted curve with an interval.

    Expects the output of ``evolution.session_best_progression``.
    """
    if progression.empty:
        return go.Figure()

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
    theme.apply(fig, height=height)
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
                  *, results: pd.DataFrame | None = None,
                  height: int = 520) -> go.Figure:
    """Distribution of clean fuel-corrected lap times per driver, fastest first.

    A box rather than a bar: race pace is a distribution, and consistency is
    part of what the reader is looking for.

    Boxes carry team colour where the results artefact supplies one. A box has
    no dash property, so the second driver of a team is drawn **hollow** rather
    than filled - a shape difference, readable without hue - and the driver
    code is on the axis under every box regardless.
    """
    if laps.empty or pace.empty:
        return go.Figure()

    order = pace["Driver"].tolist()
    styles = theme.team_styles(results, order)
    fig = go.Figure()
    for driver in order:
        subset = laps[laps["Driver"] == driver]
        colour, dash = styles.get(driver, (theme.SERIES[0], "solid"))
        fig.add_trace(go.Box(
            y=subset["LapTime_corrected_s"], name=driver,
            marker=dict(color=colour, size=4),
            line=dict(width=1.4),
            fillcolor=_rgba(colour, 0.22 if dash == "solid" else 0.0),
            boxpoints=False, showlegend=False,
            hovertemplate=f"<b>{driver}</b><br>%{{y:.3f}} s<extra></extra>",
        ))
    fig.update_yaxes(title_text="Fuel-corrected lap time (s)")
    fig.update_xaxes(categoryorder="array", categoryarray=order)
    theme.apply(fig, height=height)
    fig.update_layout(hovermode="closest")
    return fig


def gap_chart(gaps: pd.DataFrame, drivers: list[str],
              *, results: pd.DataFrame | None = None,
              height: int = 480) -> go.Figure:
    """Gap to the leader over the race for a chosen handful of drivers.

    Lines take team colour where the results artefact supplies one, falling
    back to the categorical palette. Teammates share a colour exactly, so the
    second one of a pair is dashed.
    """
    if gaps.empty or not drivers:
        return go.Figure()
    chosen = drivers[:8]
    styles = theme.team_styles(results, chosen)
    fig = go.Figure()
    for i, driver in enumerate(chosen):
        subset = gaps[gaps["Driver"] == driver]
        colour, dash = styles.get(driver, (theme.series_colour(i), "solid"))
        fig.add_trace(go.Scatter(
            x=subset["LapNumber"], y=subset["gap_s"], mode="lines",
            name=driver, line=dict(color=colour, width=2, dash=dash),
            hovertemplate=f"<b>{driver}</b><br>lap %{{x:.0f}}: +%{{y:.1f}} s<extra></extra>",
        ))
    fig.update_xaxes(title_text="Lap")
    fig.update_yaxes(title_text="Gap to leader (s)", autorange="reversed")
    theme.apply(fig, height=height)
    return fig


def position_chart(laps: pd.DataFrame, *, results: pd.DataFrame | None = None,
                   height: int = 560) -> go.Figure:
    """Track position lap by lap, P1 at the top - the classic race spaghetti.

    Structurally the sibling of :func:`gap_chart`: the same lines over the same
    x-axis, but position rather than seconds, so overtakes read as crossings
    instead of as convergence. Reversed y-axis because P1 belongs at the top;
    an ordinary axis would put the winner at the bottom of the chart.

    Every driver is drawn - the whole point is the crossings, and choosing a
    handful would hide the ones the reader has not thought to ask about.
    """
    if laps.empty or "Position" not in laps.columns:
        return go.Figure()

    have = laps.dropna(subset=["Position", "LapNumber"])
    if have.empty:
        return go.Figure()

    # Finishing order, so the legend reads like a classification.
    order = (have.sort_values("LapNumber").groupby("Driver", observed=True)
                 ["Position"].last().sort_values().index.tolist())
    styles = theme.team_styles(results, order)

    fig = go.Figure()
    for i, driver in enumerate(order):
        subset = have[have["Driver"] == driver].sort_values("LapNumber")
        colour, dash = styles.get(driver, (theme.series_colour(i), "solid"))
        fig.add_trace(go.Scatter(
            x=subset["LapNumber"], y=subset["Position"], mode="lines",
            name=driver, line=dict(color=colour, width=2, dash=dash),
            hovertemplate=f"<b>{driver}</b><br>lap %{{x:.0f}}: P%{{y:.0f}}<extra></extra>",
        ))

    fig.update_xaxes(title_text="Lap")
    # tick0 anchors the labels on P1: without it the axis starts counting from
    # zero and offers the reader a "P0" that does not exist.
    fig.update_yaxes(title_text="Position", autorange="reversed",
                     tick0=1, dtick=2, tickprefix="P")
    theme.apply(fig, height=height)
    fig.update_layout(hovermode="closest")
    return fig


def lap_by_lap(h2h: pd.DataFrame, *, name_a: str, name_b: str,
               height: int = 700) -> go.Figure:
    """Two drivers lap by lap: times, the per-lap delta, the running total.

    Three stacked panels on one x-axis rather than any of it overlaid. All
    three are seconds, but they do not share a scale - the cumulative series
    spans an order of magnitude more than the per-lap one, and drawing them
    together would flatten the detail that makes the per-lap panel readable.

    Pit laps are marked rather than dropped. They are the outliers that
    explain most sudden steps in the cumulative gap, so hiding them would
    make the chart look like a pace story when it is a strategy one.
    """
    if h2h.empty:
        return go.Figure()

    colour_a, colour_b = theme.series_colour(0), theme.series_colour(1)
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.07,
        row_heights=[0.44, 0.28, 0.28],
        subplot_titles=("Lap time (s)",
                        f"Per-lap delta (s)  ·  {name_b} − {name_a}",
                        f"Cumulative gap (s)  ·  {name_b} − {name_a}"),
    )

    for name, suffix, colour in ((name_a, "a", colour_a), (name_b, "b", colour_b)):
        col = f"LapTime_s_{suffix}"
        if col not in h2h.columns:
            continue
        # Line style carries identity as well as colour, matching the trace
        # panel on the same page.
        fig.add_trace(go.Scatter(
            x=h2h["LapNumber"], y=h2h[col], mode="lines+markers", name=name,
            line=dict(color=colour, width=2,
                      dash="solid" if suffix == "a" else "dash"),
            marker=dict(size=4),
            hovertemplate=f"<b>{name}</b><br>lap %{{x:.0f}}: %{{y:.3f}} s<extra></extra>",
        ), row=1, col=1)

        pit_col = f"pit_{suffix}"
        if pit_col in h2h.columns:
            pits = h2h[h2h[pit_col].astype(bool)]
            if not pits.empty:
                fig.add_trace(go.Scatter(
                    x=pits["LapNumber"], y=pits[col], mode="markers",
                    name=f"{name} pit",
                    marker=dict(color=colour, size=11, symbol="triangle-down",
                                line=dict(color="#ffffff", width=1)),
                    hovertemplate=f"<b>{name}</b> pit lap %{{x:.0f}}<extra></extra>",
                    showlegend=False,
                ), row=1, col=1)

    # Direction is the second channel: bars above the line are laps the
    # reference won, below are laps the compared driver won, so the reading
    # never rests on colour alone.
    delta = h2h.dropna(subset=["delta_s"])
    fig.add_trace(go.Bar(
        x=delta["LapNumber"], y=delta["delta_s"], name="Per-lap delta",
        marker_color=[colour_a if v > 0 else colour_b for v in delta["delta_s"]],
        hovertemplate="lap %{x:.0f}: %{y:+.3f} s<extra></extra>", showlegend=False,
    ), row=2, col=1)

    fig.add_trace(go.Scatter(
        x=h2h["LapNumber"], y=h2h["cumulative_s"], mode="lines",
        name="Cumulative", line=dict(color=theme.SERIES[3], width=2.5),
        hovertemplate="lap %{x:.0f}: %{y:+.2f} s<extra></extra>", showlegend=False,
    ), row=3, col=1)

    for row in (1, 2, 3):
        fig.update_yaxes(title_text="s", row=row, col=1)
    fig.update_xaxes(title_text="Lap", row=3, col=1)
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
