"""The signature view: two laps stacked channel by channel against distance.

Five panels share one x-axis in metres, with corner markers drawn through all
of them so a feature in the speed trace can be read straight down into the
delta. Stacked panels on a shared axis are used rather than a second y-axis:
speed in km/h and time in seconds have no common scale, and overlaying them
would invite comparisons between two arbitrary scalings.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from pitwall.transforms import delta_time
from pitwall.viz import theme


def _corner_shapes(segments: pd.DataFrame) -> list[dict]:
    """Vertical corner markers spanning every panel."""
    shapes = []
    corners = segments[segments["kind"] == "corner"]
    for row in corners.itertuples():
        shapes.append(dict(
            type="line", xref="x", yref="paper",
            x0=row.apex_m, x1=row.apex_m, y0=0, y1=1,
            line=dict(color=theme.GRIDLINE, width=1, dash="dot"),
            layer="below",
        ))
    return shapes


def trace_panel_data(lap_a: pd.DataFrame, lap_b: pd.DataFrame | None,
                     segments: pd.DataFrame, *, name_a: str,
                     name_b: str | None = None) -> dict:
    laps = [(lap_a, name_a)]
    if lap_b is not None and name_b is not None:
        laps.append((lap_b, name_b))
    drivers = []
    for lap, name in laps:
        covered = lap["Speed"].notna().to_numpy()
        drivers.append(dict(
            name=name, distance=lap["Distance"].to_numpy(),
            speed=lap["Speed"].to_numpy(), throttle=lap["Throttle"].to_numpy(),
            brake=np.where(covered, lap["Brake"].astype(float), np.nan),
            gear=np.where(covered, lap["nGear"].astype(float), np.nan),
            brake_state=np.where(lap["Brake"].to_numpy().astype(bool), "on", "off"),
        ))
    brake = lap_a["Brake"].to_numpy().astype(bool)
    distance = drivers[0]["distance"]
    edges = np.diff(brake.astype(int))
    starts = list(np.flatnonzero(edges == 1) + 1)
    ends = list(np.flatnonzero(edges == -1) + 1)
    if brake[0]:
        starts.insert(0, 0)
    if brake[-1]:
        ends.append(len(brake) - 1)
    if len(drivers) == 2:
        difference = np.abs(drivers[0]["speed"] - drivers[1]["speed"])
        strongest = int(np.nanargmax(difference)) if np.isfinite(difference).any() else None
        finding = (f"{name_a} and {name_b} differ by up to "
                   f"{difference[strongest]:.0f} km/h near {distance[strongest]:.0f} m."
                   if strongest is not None else "No comparable speed samples are available.")
    else:
        finding = f"{name_a}'s speed and controls over the lap."
    return dict(drivers=drivers,
                delta=delta_time(lap_a, lap_b) if len(laps) == 2 else None,
                brake_zones=[[distance[s], distance[e]] for s, e in zip(starts, ends)],
                corners=segments.loc[segments["kind"] == "corner",
                                     ["apex_m", "label"]].to_dict("records"),
                x_unit="m", y_units={"speed": "km/h", "throttle": "%",
                                      "brake": "on/off", "gear": "gear", "delta": "s"},
                finding=finding)


def trace_panel(
    lap_a: pd.DataFrame,
    lap_b: pd.DataFrame | None,
    segments: pd.DataFrame,
    *,
    name_a: str,
    name_b: str | None = None,
    height: int = 820,
) -> go.Figure:
    """Speed / throttle / brake / gear / delta-time, stacked on shared distance.

    ``lap_a`` is the reference. The delta panel is omitted when only one lap
    is supplied.
    """
    show_delta = lap_b is not None and name_b is not None
    data = trace_panel_data(lap_a, lap_b, segments, name_a=name_a, name_b=name_b)
    rows = 5 if show_delta else 4
    titles = ["Speed (km/h)", "Throttle (%)", "Brake", "Gear"]
    heights = [0.40, 0.22, 0.19, 0.19]
    if show_delta:
        titles.append(f"Cumulative delta (s) — below zero means {name_b} ahead")
        heights = [0.30, 0.16, 0.13, 0.13, 0.28]

    fig = make_subplots(
        rows=rows, cols=1, shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=heights,
        subplot_titles=titles,
    )

    laps = [(data["drivers"][0], name_a, theme.REF_COLOUR, "solid")]
    if show_delta:
        laps.append((data["drivers"][1], name_b, theme.CMP_COLOUR, "dash"))

    for lap, name, colour, dash in laps:
        d = lap["distance"]
        common = dict(x=d, mode="lines", legendgroup=name,
                      line=dict(color=colour, width=2, dash=dash))
        # The discrete channels below are edge-held outside a partial lap's
        # covered span rather than NaN, because the compact on-disk dtypes
        # cannot hold NaN. Speed is continuous and *is* restored to NaN, so it
        # is the authority on what the car actually drove; without this mask a
        # stretch of track the lap never reached reads as a held gear and a
        # confident foot off the brake.
        # Only the first panel carries the legend entry; the same colour and
        # dash identify the driver in every panel below it.
        fig.add_trace(go.Scatter(
            y=lap["speed"], name=name, showlegend=True,
            hovertemplate=f"<b>{name}</b>  %{{y:.0f}} km/h<extra></extra>", **common
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            y=lap["throttle"], name=name, showlegend=False,
            hovertemplate=f"{name}  %{{y:.0f}}%<extra></extra>", **common
        ), row=2, col=1)
        fig.add_trace(go.Scatter(
            y=lap["brake"],
            name=name, showlegend=False,
            line_shape="hv",
            hovertemplate=f"{name}  %{{customdata}}<extra></extra>",
            customdata=lap["brake_state"],
            **{k: v for k, v in common.items() if k != "line"},
            line=dict(color=colour, width=1.6, dash=dash),
        ), row=3, col=1)
        fig.add_trace(go.Scatter(
            y=lap["gear"],
            name=name, showlegend=False,
            line_shape="hv",
            hovertemplate=f"{name}  gear %{{y:.0f}}<extra></extra>",
            **{k: v for k, v in common.items() if k != "line"},
            line=dict(color=colour, width=1.6, dash=dash),
        ), row=4, col=1)

    # Braking zones as shaded bands on the speed panel - where the car is
    # slowing is the context every other channel is read against.
    d_a = data["drivers"][0]["distance"]
    brake_shapes = [
        dict(type="rect", xref="x", yref="y domain",
             x0=start, x1=end, y0=0, y1=1,
             fillcolor="rgba(230,103,103,0.10)", line_width=0, layer="below")
        for start, end in data["brake_zones"]
    ]

    if show_delta:
        delta = data["delta"]
        fig.add_trace(go.Scatter(
            x=d_a, y=delta, mode="lines", name="Delta", showlegend=False,
            line=dict(color=theme.INK_SECONDARY, width=2),
            fill="tozeroy", fillcolor="rgba(195,194,183,0.10)",
            hovertemplate="%{y:+.3f} s<extra></extra>",
        ), row=5, col=1)
        fig.add_hline(y=0, line=dict(color=theme.BASELINE, width=1), row=5, col=1)

    fig.update_layout(shapes=_corner_shapes(segments) + brake_shapes)

    # Corner numbers along the top of the speed panel.
    for row in data["corners"]:
        fig.add_annotation(
            x=row["apex_m"], y=1.0, xref="x", yref="y domain",
            text=row["label"], showarrow=False, yanchor="bottom",
            font=dict(color=theme.INK_MUTED, size=9), row=1, col=1,
        )

    fig.update_xaxes(title_text="Lap distance (m)", row=rows, col=1)
    fig.update_yaxes(rangemode="tozero", row=2, col=1)
    # An on/off channel gets named ticks rather than 0 and 1, and a little
    # padding so neither state is drawn on the panel edge.
    fig.update_yaxes(tickmode="array", tickvals=[0, 1], ticktext=["off", "on"],
                     range=[-0.12, 1.12], row=3, col=1)
    fig.update_yaxes(dtick=1, row=4, col=1)

    theme.apply(fig, height=height)
    # The legend sits right, clear of the corner numbers that run along the
    # top of the speed panel from the left.
    fig.update_layout(
        hovermode="x unified",
        margin=dict(l=56, r=24, t=72, b=48),
        legend=dict(xanchor="right", x=1.0, yanchor="bottom", y=1.035),
    )
    for annotation in fig.layout.annotations[:rows]:
        annotation.update(font=dict(color=theme.INK_SECONDARY, size=12), x=0, xanchor="left")
    return fig


def corner_delta_bars_data(comparison: pd.DataFrame, *, name_a: str, name_b: str) -> dict:
    if comparison.empty:
        return dict(labels=[], delta_s=[], faster=[], x_unit="segment", y_unit="s",
                    finding="No comparable segments are available.")
    values = comparison["delta_s"].to_numpy()
    gain = round(float(comparison["delta_s"].sum()), 3)
    winner = name_a if gain > 0 else name_b if gain < 0 else None
    return dict(labels=comparison["label"].tolist(), delta_s=values,
                faster=[name_a if v > 0 else name_b for v in values],
                x_unit="segment", y_unit="s",
                finding=(f"{winner} gained {abs(gain):.3f} s across the segments against "
                         f"{name_b if winner == name_a else name_a}." if winner else
                         f"The segments are even at 0.000 s between {name_a} and {name_b}."))


def corner_delta_bars(comparison: pd.DataFrame, *, name_a: str, name_b: str,
                      height: int = 460) -> go.Figure:
    """Time gained or lost in each segment - the corner-by-corner verdict.

    Each bar is painted in the colour of whichever driver was **faster** in
    that segment, using the same two colours they carry in the trace panel.
    Colour therefore follows the entity, not the sign, and the chart stays
    readable alongside the traces. Bar direction carries the sign as well, so
    nothing depends on hue alone.
    """
    data = corner_delta_bars_data(comparison, name_a=name_a, name_b=name_b)
    # delta_s > 0 means B lost time there, i.e. A was faster.
    colours = [theme.REF_COLOUR if v > 0 else theme.CMP_COLOUR for v in data["delta_s"]]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=data["labels"], y=data["delta_s"], marker=dict(color=colours),
        customdata=[[winner, abs(v)] for winner, v in zip(data["faster"], data["delta_s"])],
        hovertemplate=("<b>%{x}</b><br>%{customdata[0]} faster by "
                       "%{customdata[1]:.3f} s<extra></extra>"),
        showlegend=False,
    ))
    # A legend proxy for each driver, so identity is never colour-alone.
    for name, colour in ((name_a, theme.REF_COLOUR), (name_b, theme.CMP_COLOUR)):
        fig.add_trace(go.Bar(
            x=[None], y=[None], name=f"{name} faster",
            marker=dict(color=colour), showlegend=True, hoverinfo="skip",
        ))

    fig.add_hline(y=0, line=dict(color=theme.BASELINE, width=1))
    fig.update_yaxes(title_text="Time delta (s)")
    fig.update_xaxes(tickangle=-45)
    theme.apply(fig, height=height)
    # Rotated labels need room, or "Straight to T1" is clipped to "ght to T1".
    fig.update_layout(hovermode="closest", bargap=0.25, barmode="overlay",
                      margin=dict(l=64, r=24, t=48, b=120))
    return fig
