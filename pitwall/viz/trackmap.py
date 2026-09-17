"""The circuit map, coloured by where one driver is gaining on the other.

This is the view that turns a lap-time gap into a place. A reader who knows
the circuit can see the answer without reading a single number.

Drawn as a **ribbon of mini-sectors**, the way a broadcast graphic draws it,
rather than as one marker per telemetry sample. Plotly cannot colour a single
line per vertex, so the choice is a scatter of dots shaped like a track, one
trace per grid point (~1000 traces, unusable), or short constant-coloured
lengths of track. The last is both the cheap option and the familiar one -
see ``config.TRACKMAP_MINI_SECTORS`` for the bin count and why.

Full-resolution detail is not lost to the binning: a transparent hover trace
carrying every sample is drawn on top, so the readout is still per-point.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.colors import sample_colorscale

from pitwall.config import TRACKMAP_MINI_SECTORS
from pitwall.transforms import delta_time
from pitwall.viz import theme

# Ribbon geometry. The glow is a single wide, dark line laid under the
# coloured ribbon - the same job `brand.circuit_svg` gives its feGaussianBlur:
# lift the track off the carbon-weave canvas so the outline reads as one
# continuous object rather than as a chain of separate coloured pieces.
RIBBON_WIDTH = 7
GLOW_WIDTH = RIBBON_WIDTH * 3
GLOW_COLOUR = "rgba(0,0,0,0.85)"


def _rotate(x: np.ndarray, y: np.ndarray, degrees: float) -> tuple[np.ndarray, np.ndarray]:
    t = np.deg2rad(degrees)
    return x * np.cos(t) - y * np.sin(t), x * np.sin(t) + y * np.cos(t)


def _smooth(values: np.ndarray, window: int) -> np.ndarray:
    """Boxcar mean that steps over gaps instead of spreading them.

    A partial lap is NaN outside its covered span (see ``decode_grid``), and a
    plain ``np.convolve`` turns each NaN into ``window`` NaNs - so smoothing a
    lap 1 trace would blank a further ~2% of *real* track either side of the
    gap. Averaging over only the finite samples in each window keeps the
    covered span covered.

    Coverage is preserved exactly in both directions: the result is NaN
    wherever the input was, so a window that overhangs the gap cannot bleed a
    colour onto track the car never reached either.
    """
    finite = np.isfinite(values)
    filled = np.where(finite, values, 0.0)
    kernel = np.ones(window)
    total = np.convolve(filled, kernel, mode="same")
    count = np.convolve(finite.astype(float), kernel, mode="same")
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(finite & (count > 0), total / count, np.nan)


def _ribbon(fig: go.Figure, x: np.ndarray, y: np.ndarray, values: np.ndarray,
            colourscale: list, vmin: float, vmax: float) -> None:
    """Draw the outline as mini-sectors, each a constant colour.

    Consecutive bins share their boundary sample, so the ribbon is continuous
    rather than a dashed line of separate pieces, and the final bin closes back
    onto the start/finish point.

    A bin with no finite value in it - a stretch of track a partial lap never
    covered - is left unpainted, showing the dark glow beneath. Inventing a
    colour for it would put a driver's pace on track they were not on.
    """
    n = len(x)
    bins = min(TRACKMAP_MINI_SECTORS, n)
    if bins < 2:
        return

    fig.add_trace(go.Scatter(
        x=np.append(x, x[0]), y=np.append(y, y[0]), mode="lines",
        line=dict(color=GLOW_COLOUR, width=GLOW_WIDTH, shape="spline"),
        hoverinfo="skip", showlegend=False,
    ))

    edges = np.linspace(0, n, bins + 1).astype(int)
    span = (vmax - vmin) or 1e-9
    for lo, hi in zip(edges[:-1], edges[1:]):
        if hi <= lo:
            continue
        chunk = values[lo:hi]
        finite = np.isfinite(chunk)
        if not finite.any():
            continue
        value = float(chunk[finite].mean())
        position = float(np.clip((value - vmin) / span, 0.0, 1.0))
        colour = sample_colorscale(colourscale, [position], colortype="rgb")[0]
        # Take one sample past the bin so this length of track meets the next.
        if hi < n:
            seg_x, seg_y = x[lo:hi + 1], y[lo:hi + 1]
        else:
            seg_x, seg_y = np.append(x[lo:], x[0]), np.append(y[lo:], y[0])
        fig.add_trace(go.Scatter(
            x=seg_x, y=seg_y, mode="lines",
            line=dict(color=colour, width=RIBBON_WIDTH, shape="spline"),
            hoverinfo="skip", showlegend=False,
        ))


def _start_finish(fig: go.Figure, x: np.ndarray, y: np.ndarray) -> None:
    """Mark the line the lap is measured from, and which way the cars go."""
    fig.add_trace(go.Scatter(
        x=[x[0]], y=[y[0]], mode="markers+text",
        marker=dict(symbol="square", size=11, color=theme.INK_PRIMARY,
                    line=dict(color=theme.SURFACE, width=2)),
        text=["S/F"], textposition="top center",
        textfont=dict(color=theme.INK_SECONDARY, size=10),
        hovertemplate="start / finish line<extra></extra>", showlegend=False,
    ))

    # One arrow, a short way into the lap, so "which way round" never has to be
    # inferred from the hover readout. Placed far enough along that it is not
    # sitting on top of the S/F marker.
    i = max(1, len(x) // 24)
    j = min(len(x) - 1, i * 2)
    fig.add_annotation(
        x=x[j], y=y[j], ax=x[i], ay=y[i],
        xref="x", yref="y", axref="x", ayref="y",
        showarrow=True, arrowhead=2, arrowsize=1.4, arrowwidth=2,
        arrowcolor=theme.INK_SECONDARY, text="",
    )


def _corner_labels(fig: go.Figure, corners: pd.DataFrame | None) -> None:
    if corners is None or corners.empty or not {"X", "Y"}.issubset(corners.columns):
        return
    rotation = float(corners["Rotation"].iloc[0]) if "Rotation" in corners else 0.0
    cx, cy = _rotate(corners["X"].to_numpy(dtype=float),
                     corners["Y"].to_numpy(dtype=float), rotation)
    fig.add_trace(go.Scatter(
        x=cx, y=cy, mode="text",
        text=corners["CornerLabel"].astype(str),
        textfont=dict(color=theme.INK_MUTED, size=10),
        hoverinfo="skip", showlegend=False,
    ))


# One frame for every map view. The circuit has to sit in the same place at
# the same size whichever view is showing, or flicking the radio reads as the
# map jumping rather than as the colouring changing. The bottom margin is the
# room the horizontal colourbar hangs in - see `speed_delta_map`.
MAP_MARGIN = dict(l=8, r=8, t=16, b=76)


def _map_layout(fig: go.Figure, height: int) -> go.Figure:
    theme.apply(fig, height=height)
    fig.update_layout(hovermode="closest", margin=MAP_MARGIN)
    # A circuit map is a map: equal aspect, no axes.
    #
    # `constrain="domain"` is what makes that aspect *stable*, and it is not
    # optional. Plotly's default for a `scaleanchor`ed axis is
    # `constrain="range"`: it keeps the whole plot rectangle and pads out the
    # range of whichever axis has slack. That makes the outline's size and
    # position a function of the pixel box the browser happened to measure -
    # so the circuit shrinks and drifts off-centre while the S/F marker, the
    # direction arrow and the corner labels keep their fixed pixel sizes and
    # stop lining up with it. Shrinking the *domain* instead fits the plot
    # area to the circuit's own aspect and centres it, leaving the data ranges
    # alone, so the map draws identically at every container width.
    fig.update_xaxes(visible=False, showgrid=False, constrain="domain")
    fig.update_yaxes(visible=False, showgrid=False,
                     scaleanchor="x", scaleratio=1, constrain="domain")
    return fig


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
        return _map_layout(go.Figure(), height)

    n = min(len(track), len(lap_a), len(lap_b))
    x = track["X"].to_numpy()[:n]
    y = track["Y"].to_numpy()[:n]

    delta = delta_time(lap_a, lap_b)[:n]
    # Rate of change of the gap, smoothed over ~2% of the lap so the colour
    # shows corner-scale trends rather than sample noise.
    window = max(3, n // 50)
    rate = _smooth(np.gradient(delta), window)

    # Where neither lap covers the track there is no gap to describe. The
    # scale has to be set from the samples that exist, or one NaN makes every
    # limit NaN and the colour lookup fails outright.
    known = np.isfinite(rate)
    limit = float(np.nanpercentile(np.abs(rate), 98)) if known.any() else 0.0
    if not np.isfinite(limit) or limit == 0.0:
        limit = 1e-6

    fig = go.Figure()
    _ribbon(fig, x, y, rate, theme.DIVERGING, -limit, limit)

    # Full-resolution readout, laid invisibly over the ribbon so the binning
    # costs no hover detail, and carrying the colourbar - a line trace cannot.
    # Only the samples both laps actually recorded: a hover reading "running
    # gap NaN s" over unpainted track is worse than no hover at all.
    readable = known & np.isfinite(delta)
    fig.add_trace(go.Scatter(
        x=x[readable], y=y[readable], mode="markers",
        marker=dict(
            size=9, opacity=0, color=rate[readable], colorscale=theme.DIVERGING,
            cmin=-limit, cmax=limit, showscale=True,
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
        customdata=np.stack([track["Distance"].to_numpy()[:n][readable],
                             delta[readable]], axis=-1),
        hovertemplate=("%{customdata[0]:.0f} m<br>"
                       "running gap %{customdata[1]:+.3f} s<extra></extra>"),
        showlegend=False,
    ))

    _start_finish(fig, x, y)
    _corner_labels(fig, corners)
    return _map_layout(fig, height)


def speed_map(track: pd.DataFrame, lap: pd.DataFrame, *,
              height: int = 620, corners: pd.DataFrame | None = None) -> go.Figure:
    """Circuit outline coloured by absolute speed - a single-lap view.

    Sequential magnitude, so a single hue light-to-dark rather than the
    diverging scale used for signed differences.
    """
    if track.empty:
        return _map_layout(go.Figure(), height)
    n = min(len(track), len(lap))
    x = track["X"].to_numpy()[:n]
    y = track["Y"].to_numpy()[:n]
    speed = lap["Speed"].to_numpy(dtype="float64")[:n]
    scale = [[0.0, "#cde2fb"], [0.5, "#3987e5"], [1.0, "#0d366b"]]
    # A partial lap is NaN off its covered span, and a lap that is NaN
    # throughout would otherwise hand a NaN scale to the colour lookup.
    known = np.isfinite(speed)
    if not known.any():
        return _map_layout(go.Figure(), height)
    lo, hi = float(speed[known].min()), float(speed[known].max())

    fig = go.Figure()
    _ribbon(fig, x, y, speed, scale, lo, hi)
    fig.add_trace(go.Scatter(
        x=x[known], y=y[known], mode="markers",
        marker=dict(
            size=9, opacity=0, color=speed[known], colorscale=scale,
            cmin=lo, cmax=hi, showscale=True,
            # Same bar, same edge, same size as the delta map's. A vertical
            # bar here would eat width the other view keeps, changing the
            # shape of the plot rectangle - and the circuit is fitted to that
            # rectangle, so the map would resize on every radio toggle.
            colorbar=dict(
                orientation="h",
                title=dict(text="km/h",
                           font=dict(color=theme.INK_MUTED, size=11), side="top"),
                tickfont=dict(color=theme.INK_SECONDARY, size=11),
                outlinewidth=0, thickness=10, len=0.55,
                x=0.5, xanchor="center", y=-0.02, yanchor="top",
            ),
        ),
        hovertemplate="%{marker.color:.0f} km/h<extra></extra>",
        showlegend=False,
    ))
    _start_finish(fig, x, y)
    _corner_labels(fig, corners)
    return _map_layout(fig, height)
