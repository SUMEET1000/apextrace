"""The circuit map, coloured by where one driver is gaining on the other.

This is the view that turns a lap-time gap into a place. A reader who knows
the circuit can see the answer without reading a single number.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from pitwall.transforms import delta_time
from pitwall.viz import theme


def _rotate(x: np.ndarray, y: np.ndarray, degrees: float) -> tuple[np.ndarray, np.ndarray]:
    t = np.deg2rad(degrees)
    return x * np.cos(t) - y * np.sin(t), x * np.sin(t) + y * np.cos(t)


def speed_delta_map(
    track: pd.DataFrame,
    lap_a: pd.DataFrame,
    lap_b: pd.DataFrame,
    *,
    name_a: str,
    name_b: str,
    corners: pd.DataFrame | None = None,
    height: int = 620,
) -> go.Figure:
    """Circuit outline coloured by the rate at which the gap is changing.

    Colour encodes *where time is changing hands*, not the running total: the
    derivative of the delta curve. A cumulative gap would paint the whole
    second half of the lap with whatever happened at one corner.

    Diverging scale on a signed quantity, with a neutral grey midpoint so
    "neither driver is gaining here" reads as nothing.
    """
    if track.empty:
        return go.Figure()

    n = min(len(track), len(lap_a), len(lap_b))
    x = track["X"].to_numpy()[:n]
    y = track["Y"].to_numpy()[:n]

    delta = delta_time(lap_a, lap_b)[:n]
    # Rate of change of the gap, smoothed over ~2% of the lap so the colour
    # shows corner-scale trends rather than sample noise.
    window = max(3, n // 50)
    kernel = np.ones(window) / window
    rate = np.gradient(delta)
    rate = np.convolve(rate, kernel, mode="same")

    limit = float(np.percentile(np.abs(rate), 98)) or 1e-6

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x, y=y, mode="markers",
        marker=dict(
            size=8, color=rate, colorscale=theme.DIVERGING,
            cmin=-limit, cmax=limit,
            # Horizontal bar along the bottom: a vertical colorbar renders
            # its title rotated, which makes a two-ended label unreadable.
            colorbar=dict(
                orientation="h",
                title=dict(text="who is pulling away here",
                           font=dict(color=theme.INK_MUTED, size=11), side="top"),
                tickmode="array",
                tickvals=[-limit * 0.92, 0, limit * 0.92],
                ticktext=[f"{name_b} gaining", "even", f"{name_a} gaining"],
                tickfont=dict(color=theme.INK_SECONDARY, size=11),
                outlinewidth=0, thickness=10, len=0.55,
                x=0.5, xanchor="center", y=-0.02, yanchor="top",
            ),
        ),
        customdata=np.stack([track["Distance"].to_numpy()[:n], delta], axis=-1),
        hovertemplate=("%{customdata[0]:.0f} m<br>"
                       "running gap %{customdata[1]:+.3f} s<extra></extra>"),
        showlegend=False,
    ))

    if corners is not None and not corners.empty and {"X", "Y"}.issubset(corners.columns):
        rotation = float(corners["Rotation"].iloc[0]) if "Rotation" in corners else 0.0
        cx, cy = _rotate(corners["X"].to_numpy(dtype=float),
                         corners["Y"].to_numpy(dtype=float), rotation)
        fig.add_trace(go.Scatter(
            x=cx, y=cy, mode="text",
            text=corners["CornerLabel"].astype(str),
            textfont=dict(color=theme.INK_MUTED, size=10),
            hoverinfo="skip", showlegend=False,
        ))

    theme.apply(fig, height=height)
    fig.update_layout(hovermode="closest", margin=dict(l=8, r=8, t=16, b=76))
    # A circuit map is a map: equal aspect, no axes.
    fig.update_xaxes(visible=False, showgrid=False)
    fig.update_yaxes(visible=False, showgrid=False,
                     scaleanchor="x", scaleratio=1)
    return fig


def speed_map(track: pd.DataFrame, lap: pd.DataFrame, *,
              height: int = 620, corners: pd.DataFrame | None = None) -> go.Figure:
    """Circuit outline coloured by absolute speed - a single-lap view.

    Sequential magnitude, so a single hue light-to-dark rather than the
    diverging scale used for signed differences.
    """
    if track.empty:
        return go.Figure()
    n = min(len(track), len(lap))
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=track["X"].to_numpy()[:n], y=track["Y"].to_numpy()[:n], mode="markers",
        marker=dict(
            size=8, color=lap["Speed"].to_numpy()[:n],
            colorscale=[[0.0, "#cde2fb"], [0.5, "#3987e5"], [1.0, "#0d366b"]],
            colorbar=dict(
                title=dict(text="km/h", font=dict(color=theme.INK_SECONDARY, size=11)),
                tickfont=dict(color=theme.INK_MUTED, size=10),
                outlinewidth=0, thickness=12, len=0.6,
            ),
        ),
        hovertemplate="%{marker.color:.0f} km/h<extra></extra>",
        showlegend=False,
    ))
    theme.apply(fig, height=height)
    fig.update_layout(hovermode="closest", margin=dict(l=8, r=8, t=32, b=8))
    fig.update_xaxes(visible=False, showgrid=False)
    fig.update_yaxes(visible=False, showgrid=False, scaleanchor="x", scaleratio=1)
    return fig
