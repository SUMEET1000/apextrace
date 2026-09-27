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

def degradation_scatter_data(laps: pd.DataFrame, stints: pd.DataFrame) -> dict:
    if laps.empty:
        return dict(panels=[], x_unit="tyre age (laps)", y_unit="s",
                    finding="No tyre-wear laps are available.")
    compounds = [c for c in laps["Compound"].dropna().unique()]
    compounds.sort(key=lambda c: -len(laps[laps["Compound"] == c]))
    panels = []
    for compound in compounds:
        subset = laps[laps["Compound"] == compound]
        panel = dict(compound=compound, age=subset["TyreLife"].to_numpy(),
                     lap_time_s=subset["LapTime_corrected_s"].to_numpy(),
                     drivers=subset["Driver"].to_numpy(), fit=None)
        fit = stints[stints["Compound"] == compound] if not stints.empty else pd.DataFrame()
        if not fit.empty:
            weights = 1.0 / fit["std_err"].clip(lower=1e-6) ** 2
            slope = float((fit["deg_s_per_lap"] * weights).sum() / weights.sum())
            intercept = float((fit["intercept_s"] * weights).sum() / weights.sum())
            age = np.linspace(subset["TyreLife"].min(), subset["TyreLife"].max(), 50)
            panel["fit"] = dict(age=age, lap_time_s=intercept + slope * age,
                                slope_s_per_lap=slope)
        panels.append(panel)
    return dict(panels=panels, x_unit="tyre age (laps)", y_unit="s",
                finding=(f"{panels[0]['compound']} has a measured wear slope of "
                         f"{panels[0]['fit']['slope_s_per_lap']:.3f} s/lap."
                         if panels and panels[0]["fit"] else
                         "No tyre-wear slope is available."))

def degradation_bars_data(summary: pd.DataFrame) -> dict:
    if summary.empty:
        return dict(compounds=[], rate=[], lower=[], upper=[], n_stints=[], n_laps=[],
                    x_unit="compound", y_unit="s/lap",
                    finding="No degradation estimate is available.")
    return dict(compounds=summary["Compound"].tolist(),
                rate=summary["deg_s_per_lap"].to_numpy(),
                lower=summary["ci_low"].to_numpy(), upper=summary["ci_high"].to_numpy(),
                n_stints=summary["n_stints"].to_numpy(),
                n_laps=summary["n_laps"].to_numpy(),
                x_unit="compound", y_unit="s/lap",
                finding=(f"{summary.iloc[0]['Compound']} tyres lose "
                         f"{summary.iloc[0]['deg_s_per_lap']:.3f} s per lap on average."
                         if not summary.empty else "No degradation estimate is available."))

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

    data = degradation_scatter_data(laps, stints)
    compounds = [panel["compound"] for panel in data["panels"]]
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

    for index, panel in enumerate(data["panels"]):
        compound = panel["compound"]
        row, i = divmod(index, n_cols)
        row, i = row + 1, i + 1
        colour = theme.compound_colour(compound)
        fig.add_trace(go.Scatter(
            x=panel["age"], y=panel["lap_time_s"],
            mode="markers", name=compound, showlegend=False,
            marker=dict(size=5, color=_rgba(colour, 0.45),
                        line=dict(width=0)),
            hovertemplate=("%{customdata}<br>tyre age %{x:.0f} laps"
                           "<br>%{y:.3f} s<extra></extra>"),
            customdata=panel["drivers"],
        ), row=row, col=i)

        if panel["fit"]:
            fit = panel["fit"]
            fig.add_trace(go.Scatter(
                x=fit["age"], y=fit["lap_time_s"], mode="lines",
                line=dict(color=colour, width=2.5), showlegend=False,
                hovertemplate=f"{fit['slope_s_per_lap']:+.3f} s/lap<extra></extra>",
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

    data = degradation_bars_data(summary)
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=data["compounds"], y=data["rate"],
        marker=dict(color=[theme.compound_colour(c) for c in data["compounds"]]),
        error_y=dict(
            type="data", symmetric=False,
            array=data["upper"] - data["rate"],
            arrayminus=data["rate"] - data["lower"],
            color=theme.INK_SECONDARY, thickness=1.5, width=6,
        ),
        customdata=np.stack([data["n_stints"], data["n_laps"]], axis=-1),
        hovertemplate=("<b>%{x}</b><br>%{y:.3f} s/lap"
                       "<br>%{customdata[0]} stints, %{customdata[1]} laps<extra></extra>"),
        showlegend=False,
    ))
    fig.update_yaxes(title_text="Degradation (s per lap)", rangemode="tozero")
    theme.apply(fig, height=height)
    fig.update_layout(hovermode="closest", bargap=0.45)
    return fig


# ----------------------------------------------------------------- evolution

def evolution_curve_data(curve: pd.DataFrame,
                         naive: pd.DataFrame | None = None) -> dict:
    if curve.empty:
        return dict(progress=[], evolution_s=[], lower=[], upper=[], naive=None,
                    x_unit="session fraction", y_unit="s",
                    finding="Track evolution is unavailable.")
    data = dict(progress=curve["progress"].to_numpy(),
                evolution_s=curve["evolution_s"].to_numpy(),
                lower=curve["ci_low"].to_numpy(), upper=curve["ci_high"].to_numpy(),
                naive=(dict(progress=naive["progress"].to_numpy(),
                            evolution_s=naive["evolution_s"].to_numpy())
                       if naive is not None and not naive.empty else None),
                x_unit="session fraction", y_unit="s")
    data["finding"] = (f"The track changed lap time by {data['evolution_s'][-1] - data['evolution_s'][0]:+.3f} s across the session."
                       if len(curve) else "Track evolution is unavailable.")
    return data

def evolution_curve(curve: pd.DataFrame, naive: pd.DataFrame | None = None,
                    *, height: int = 420) -> go.Figure:
    """Track evolution with its confidence band, against the naive estimate."""
    if curve.empty:
        return go.Figure()

    data = evolution_curve_data(curve, naive)
    fig = go.Figure()
    band = _rgba(theme.SERIES[0], 0.18)
    fig.add_trace(go.Scatter(
        x=np.concatenate([data["progress"], data["progress"][::-1]]),
        y=np.concatenate([data["upper"], data["lower"][::-1]]),
        fill="toself", fillcolor=band, line=dict(width=0),
        hoverinfo="skip", showlegend=False,
    ))
    fig.add_trace(go.Scatter(
        x=data["progress"], y=data["evolution_s"], mode="lines",
        name="Pooled model (tyre & fuel removed)",
        line=dict(color=theme.SERIES[0], width=2.5),
        hovertemplate="%{y:+.3f} s at %{x:.0%} distance<extra></extra>",
    ))

    if data["naive"] is not None:
        fig.add_trace(go.Scatter(
            x=data["naive"]["progress"], y=data["naive"]["evolution_s"], mode="lines",
            name="Naive trend (tyre & fuel confounded)",
            line=dict(color=theme.SERIES[1], width=2, dash="dash"),
            hovertemplate="%{y:+.3f} s<extra></extra>",
        ))

    fig.add_hline(y=0, line=dict(color=theme.BASELINE, width=1))
    fig.update_xaxes(title_text="Session progress", tickformat=".0%")
    fig.update_yaxes(title_text="Lap time vs session start (s)")
    theme.apply(fig, height=height)
    return fig


def evolution_with_temperature_data(curve: pd.DataFrame,
                                    weather: pd.DataFrame) -> dict:
    data = evolution_curve_data(curve)
    has_weather = (not weather.empty and "TrackTemp" in weather.columns
                   and "Time_s" in weather.columns)
    data["temperature"] = None
    if has_weather:
        origin = weather["Time_s"].min()
        span = weather["Time_s"].max() - origin
        valid = weather.dropna(subset=["TrackTemp"])
        data["temperature"] = dict(progress=(valid["Time_s"] - origin).to_numpy()
                                   / (span if span else 1),
                                   celsius=valid["TrackTemp"].to_numpy())
    data["temperature_unit"] = "°C"
    return data


def evolution_with_temperature(curve: pd.DataFrame, weather: pd.DataFrame,
                               *, height: int = 520) -> go.Figure:
    """Evolution above, track temperature below, on a shared x-axis.

    Deliberately two panels rather than one frame with two y-axes: seconds
    and degrees have no common scale, and overlaying them would let the
    apparent correlation be set by whatever ranges happened to be chosen.
    """
    if curve.empty:
        return go.Figure()

    data = evolution_with_temperature_data(curve, weather)
    has_weather = data["temperature"] is not None
    rows = 2 if has_weather else 1
    fig = make_subplots(
        rows=rows, cols=1, shared_xaxes=True, vertical_spacing=0.09,
        row_heights=[0.62, 0.38] if has_weather else [1.0],
        subplot_titles=(["Track evolution (s gained)", "Track temperature (°C)"]
                        if has_weather else ["Track evolution (s gained)"]),
    )

    fig.add_trace(go.Scatter(
        x=np.concatenate([data["progress"], data["progress"][::-1]]),
        y=np.concatenate([data["upper"], data["lower"][::-1]]),
        fill="toself", fillcolor=_rgba(theme.SERIES[0], 0.18),
        line=dict(width=0), hoverinfo="skip", showlegend=False,
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=data["progress"], y=data["evolution_s"], mode="lines",
        name="Track evolution", line=dict(color=theme.SERIES[0], width=2.5),
        hovertemplate="%{y:+.3f} s<extra></extra>", showlegend=False,
    ), row=1, col=1)

    if has_weather:
        # The span is measured before the drop. Taken after it, a missing
        # first reading moved every surviving observation along the axis -
        # a reading at 60 s of a 120 s session jumped from 50% to 0%.
        fig.add_trace(go.Scatter(
            x=data["temperature"]["progress"], y=data["temperature"]["celsius"], mode="lines",
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


def session_best_curve_data(progression: pd.DataFrame) -> dict:
    if progression.empty:
        return dict(minutes=[], lap_time_s=[], best_s=[], x_unit="min", y_unit="s",
                    finding="No timed laps are available.")
    data = dict(minutes=progression["session_minutes"].to_numpy(),
                lap_time_s=progression["lap_time_s"].to_numpy(),
                best_s=progression["session_best_s"].to_numpy(),
                x_unit="min", y_unit="s")
    data["finding"] = (f"The session best finished at {data['best_s'][-1]:.3f} s."
                       if len(progression) else "No timed laps are available.")
    return data


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

    data = session_best_curve_data(progression)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=data["minutes"], y=data["lap_time_s"],
        mode="markers", name="Individual laps",
        marker=dict(size=5, color=theme.INK_MUTED, opacity=0.5),
        hovertemplate="%{y:.3f} s<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=data["minutes"], y=data["best_s"],
        mode="lines", name="Session best",
        line=dict(color=theme.SERIES[0], width=2.5),
        hovertemplate="best %{y:.3f} s<extra></extra>",
    ))
    fig.update_xaxes(title_text="Minutes into session")
    fig.update_yaxes(title_text="Lap time (s)")
    theme.apply(fig, height=height)
    return fig


# ------------------------------------------------------------------ strategy

def stint_chart_data(stints: pd.DataFrame) -> dict:
    if stints.empty:
        return dict(order=[], stints=[], x_unit="lap", y_unit="driver",
                    finding="No stint history is available.")
    order = (stints.groupby("Driver", observed=True)["end_lap"].max()
                   .sort_values(ascending=False).index.tolist())
    rows = [dict(driver=row.Driver, compound=str(row.Compound),
                 start_lap=row.start_lap, end_lap=row.end_lap,
                 extent=row.end_lap - row.start_lap + 1, laps=row.laps)
            for row in stints.itertuples()]
    return dict(order=order, stints=rows, x_unit="lap", y_unit="driver",
                finding=f"{len(rows)} tyre stints are recorded across {len(order)} drivers.")

def stint_chart(stints: pd.DataFrame, *, height: int = 640) -> go.Figure:
    """Stint timeline: one row per driver, bars coloured and labelled by compound."""
    if stints.empty:
        return go.Figure()

    data = stint_chart_data(stints)
    order = data["order"]

    fig = go.Figure()
    seen: set[str] = set()
    for row in data["stints"]:
        compound = row["compound"]
        # Width is the stint's lap extent, not how many of its laps the
        # timing feed happened to report. Using the count drew a stint
        # observed on laps 1,2,4,5 as ending at 4, contradicting the hover
        # text beneath it.
        extent = row["extent"]
        fig.add_trace(go.Bar(
            y=[row["driver"]], x=[extent], base=[row["start_lap"] - 1],
            orientation="h", name=compound,
            legendgroup=compound, showlegend=compound not in seen,
            marker=dict(color=theme.compound_colour(compound),
                        line=dict(color=theme.SURFACE, width=2)),
            # Compound named in text on the bar, so the reading never depends
            # on telling two official tyre colours apart.
            text=compound[0] if extent >= 4 else "",
            textposition="inside", insidetextanchor="middle",
            textfont=dict(color=theme.SURFACE, size=10),
            hovertemplate=(f"<b>{row['driver']}</b><br>{compound}<br>"
                           f"laps {row['start_lap']:.0f}–{row['end_lap']:.0f} "
                           f"({row['laps']} laps)<extra></extra>"),
        ))
        seen.add(compound)

    fig.update_layout(barmode="stack")
    fig.update_yaxes(categoryorder="array", categoryarray=order)
    fig.update_xaxes(title_text="Lap")
    theme.apply(fig, height=height)
    fig.update_layout(hovermode="closest")
    return fig


def box_statistics(samples) -> dict:
    values = np.asarray(samples, dtype=float)
    values = values[np.isfinite(values)]
    if not len(values):
        return dict(q1=None, median=None, q3=None, lo=None, hi=None, outliers=[])
    q1, median, q3 = np.percentile(values, [25, 50, 75], method="hazen")
    iqr = q3 - q1
    inside = values[(values >= q1 - 1.5 * iqr) & (values <= q3 + 1.5 * iqr)]
    return dict(q1=float(q1), median=float(median), q3=float(q3),
                lo=float(inside.min()), hi=float(inside.max()),
                outliers=values[(values < inside.min()) | (values > inside.max())])


def race_pace_box_data(laps: pd.DataFrame, pace: pd.DataFrame) -> dict:
    if laps.empty or pace.empty:
        return dict(order=[], boxes=[], x_unit="driver", y_unit="s",
                    finding="No clean race-pace laps are available.")
    order = pace["Driver"].tolist()
    boxes = []
    for driver in order:
        samples = laps.loc[laps["Driver"] == driver, "LapTime_corrected_s"].to_numpy()
        boxes.append(dict(driver=driver, samples=samples, **box_statistics(samples)))
    fastest = min((box for box in boxes if box["median"] is not None),
                  key=lambda box: box["median"], default=None)
    return dict(order=order, boxes=boxes, x_unit="driver", y_unit="s",
                finding=(f"{fastest['driver']} has the fastest median fuel-corrected lap "
                         f"at {fastest['median']:.3f} s." if fastest else
                         "No clean race-pace laps are available."))


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

    data = race_pace_box_data(laps, pace)
    order = data["order"]
    styles = theme.team_styles(results, order)
    fig = go.Figure()
    for box in data["boxes"]:
        driver = box["driver"]
        colour, dash = styles.get(driver, (theme.SERIES[0], "solid"))
        fig.add_trace(go.Box(
            y=box["samples"], name=driver,
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


def gap_chart_data(gaps: pd.DataFrame, drivers: list[str]) -> dict:
    if gaps.empty or not drivers:
        return dict(series=[], x_unit="lap", y_unit="s", y_direction="reversed",
                    finding="Choose drivers to compare their gap to the leader.")
    chosen = drivers[:8]
    series = [dict(driver=driver,
                   lap=gaps.loc[gaps["Driver"] == driver, "LapNumber"].to_numpy(),
                   gap_s=gaps.loc[gaps["Driver"] == driver, "gap_s"].to_numpy())
              for driver in chosen]
    finishes = [(row["driver"], float(row["gap_s"][-1])) for row in series
                if len(row["gap_s"]) and np.isfinite(row["gap_s"][-1])]
    closest = min(finishes, key=lambda item: item[1]) if finishes else None
    return dict(series=series, x_unit="lap", y_unit="s", y_direction="reversed",
                finding=(f"{closest[0]} ends closest to the leader among the selected drivers "
                         f"at +{closest[1]:.1f} s."
                         if closest else "No selected driver has a recorded final gap."))


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
    data = gap_chart_data(gaps, drivers)
    chosen = [row["driver"] for row in data["series"]]
    styles = theme.team_styles(results, chosen)
    fig = go.Figure()
    for i, row in enumerate(data["series"]):
        driver = row["driver"]
        colour, dash = styles.get(driver, (theme.series_colour(i), "solid"))
        fig.add_trace(go.Scatter(
            x=row["lap"], y=row["gap_s"], mode="lines",
            name=driver, line=dict(color=colour, width=2, dash=dash),
            hovertemplate=f"<b>{driver}</b><br>lap %{{x:.0f}}: +%{{y:.1f}} s<extra></extra>",
        ))
    fig.update_xaxes(title_text="Lap")
    fig.update_yaxes(title_text="Gap to leader (s)", autorange="reversed")
    theme.apply(fig, height=height)
    return fig


def position_chart_data(laps: pd.DataFrame) -> dict:
    if laps.empty or "Position" not in laps.columns:
        return dict(series=[], x_unit="lap", y_unit="position",
                    y_direction="reversed", finding="No position history is available.")
    have = laps.dropna(subset=["Position", "LapNumber"])
    order = (have.sort_values("LapNumber").groupby("Driver", observed=True)
                 ["Position"].last().sort_values().index.tolist())
    series = []
    for driver in order:
        subset = have[have["Driver"] == driver].sort_values("LapNumber")
        series.append(dict(driver=driver, lap=subset["LapNumber"].to_numpy(),
                           position=subset["Position"].to_numpy()))
    return dict(series=series, x_unit="lap", y_unit="position",
                y_direction="reversed",
                finding=(f"{order[0]} finished highest among drivers with position data."
                         if order else "No position history is available."))


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

    data = position_chart_data(laps)
    if not data["series"]:
        return go.Figure()

    # Finishing order, so the legend reads like a classification.
    order = [row["driver"] for row in data["series"]]
    styles = theme.team_styles(results, order)

    fig = go.Figure()
    for i, row in enumerate(data["series"]):
        driver = row["driver"]
        colour, dash = styles.get(driver, (theme.series_colour(i), "solid"))
        fig.add_trace(go.Scatter(
            x=row["lap"], y=row["position"], mode="lines",
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


def lap_by_lap_data(h2h: pd.DataFrame, *, name_a: str, name_b: str) -> dict:
    lap_times = []
    for name, suffix in ((name_a, "a"), (name_b, "b")):
        col = f"LapTime_s_{suffix}"
        if col not in h2h:
            continue
        pits = h2h[h2h[f"pit_{suffix}"].astype(bool)] if f"pit_{suffix}" in h2h else h2h.iloc[:0]
        lap_times.append(dict(driver=name, suffix=suffix,
                              lap=h2h["LapNumber"].to_numpy(),
                              time_s=h2h[col].to_numpy(),
                              pit_lap=pits["LapNumber"].to_numpy(),
                              pit_time_s=pits[col].to_numpy()))
    delta = h2h.dropna(subset=["delta_s"])
    finite_gap = h2h[np.isfinite(pd.to_numeric(h2h["cumulative_s"], errors="coerce"))] if not h2h.empty else h2h
    last_gap = float(finite_gap.iloc[-1]["cumulative_s"]) if not finite_gap.empty else 0.0
    return dict(lap_times=lap_times, delta=dict(lap=delta["LapNumber"].to_numpy(),
                                               seconds=delta["delta_s"].to_numpy()),
                cumulative=dict(lap=h2h["LapNumber"].to_numpy(),
                                seconds=h2h["cumulative_s"].to_numpy()),
                x_unit="lap", y_unit="s",
                finding=(f"Through lap {int(finite_gap.iloc[-1]['LapNumber'])}, {name_b} was "
                         f"{abs(last_gap):.3f} s {'ahead of' if last_gap < 0 else 'behind' if last_gap > 0 else 'level with'} "
                         f"{name_a} on summed lap times."
                         if not finite_gap.empty else
                         f"{len(delta)} comparable lap time pairs are available for {name_a} and {name_b}."))


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

    data = lap_by_lap_data(h2h, name_a=name_a, name_b=name_b)
    colour_a, colour_b = theme.series_colour(0), theme.series_colour(1)
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.07,
        row_heights=[0.44, 0.28, 0.28],
        subplot_titles=("Lap time (s)",
                        f"Per-lap delta (s)  ·  {name_b} − {name_a}",
                        f"Cumulative gap (s)  ·  {name_b} − {name_a}"),
    )

    for row in data["lap_times"]:
        name, suffix = row["driver"], row["suffix"]
        colour = colour_a if suffix == "a" else colour_b
        # Line style carries identity as well as colour, matching the trace
        # panel on the same page.
        fig.add_trace(go.Scatter(
            x=row["lap"], y=row["time_s"], mode="lines+markers", name=name,
            line=dict(color=colour, width=2,
                      dash="solid" if suffix == "a" else "dash"),
            marker=dict(size=4),
            hovertemplate=f"<b>{name}</b><br>lap %{{x:.0f}}: %{{y:.3f}} s<extra></extra>",
        ), row=1, col=1)

        if len(row["pit_lap"]):
            fig.add_trace(go.Scatter(
                x=row["pit_lap"], y=row["pit_time_s"], mode="markers",
                name=f"{name} pit",
                marker=dict(color=colour, size=11, symbol="triangle-down",
                            line=dict(color="#ffffff", width=1)),
                hovertemplate=f"<b>{name}</b> pit lap %{{x:.0f}}<extra></extra>",
                showlegend=False,
            ), row=1, col=1)

    # Direction is the second channel: bars above the line are laps the
    # reference won, below are laps the compared driver won, so the reading
    # never rests on colour alone.
    fig.add_trace(go.Bar(
        x=data["delta"]["lap"], y=data["delta"]["seconds"], name="Per-lap delta",
        marker_color=[colour_a if v > 0 else colour_b for v in data["delta"]["seconds"]],
        hovertemplate="lap %{x:.0f}: %{y:+.3f} s<extra></extra>", showlegend=False,
    ), row=2, col=1)

    fig.add_trace(go.Scatter(
        x=data["cumulative"]["lap"], y=data["cumulative"]["seconds"], mode="lines",
        name="Cumulative", line=dict(color=theme.SERIES[3], width=2.5),
        hovertemplate="lap %{x:.0f}: %{y:+.2f} s<extra></extra>", showlegend=False,
    ), row=3, col=1)

    for row in (1, 2, 3):
        fig.update_yaxes(title_text="s", row=row, col=1)
    fig.update_xaxes(title_text="Lap", row=3, col=1)
    theme.apply(fig, height=height)
    return fig


def undercut_chart_data(table: pd.DataFrame, gap_s: float) -> dict:
    if table.empty:
        return dict(laps=[], gain_s=[], gap_s=gap_s, ahead=[],
                    x_unit="laps after stop", y_unit="s",
                    finding="No undercut window is available.")
    laps = table["laps_after_stop"].to_numpy()
    gain = table["cumulative_gain_s"].to_numpy()
    ahead = table["ahead"].to_numpy()
    first = next((int(lap) for lap, yes in zip(laps, ahead) if yes), None)
    return dict(laps=laps, gain_s=gain, gap_s=gap_s, ahead=ahead,
                x_unit="laps after stop", y_unit="s",
                finding=(f"The undercut closes a {gap_s:.1f} s gap after {first} laps."
                         if first is not None else
                         f"The undercut does not close a {gap_s:.1f} s gap in this window."))


def undercut_chart(table: pd.DataFrame, gap_s: float, *, height: int = 400) -> go.Figure:
    """Cumulative undercut gain against the gap that has to be closed."""
    if table.empty:
        return go.Figure()
    data = undercut_chart_data(table, gap_s)
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=data["laps"], y=data["gain_s"],
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
