"""One shared visual language for every chart in the app.

Colour decisions are made here once and consumed by role everywhere else, so
the four analysis pages read as one product rather than four projects.

Palette provenance
------------------
Series colours are the validated dark-mode categorical palette, checked
against this app's own surface (#0E1117) rather than assumed:

    Lightness band    PASS   all 8 inside L 0.48-0.67
    Chroma floor      PASS   all 8 >= 0.10
    CVD separation    PASS   worst adjacent dE 8.4 (protanopia)
    Normal vision     PASS   worst adjacent dE 19.3
    Contrast          PASS   all 8 >= 3:1

Tyre compounds are a deliberate exception. The official Pirelli colours fail
that same check - SOFT (red) against INTERMEDIATE (green) collapses to dE 3.5
under deuteranopia, and HARD is pure white with zero chroma. They are kept
anyway, because every F1 viewer already reads them and substituting invented
colours would make the tool worse for the people using it. The mitigation is
that compound colour is never the only channel: every compound mark is
accompanied by its name in text, so the colour is a recognition aid rather
than the encoding. Nothing in the app asks a reader to distinguish two
compounds by hue alone.
"""

from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio

from pitwall.config import COMPOUND_COLOURS

# --------------------------------------------------------------------------
# Surfaces and ink
# --------------------------------------------------------------------------

SURFACE = "#080808"        # near-black canvas, matches the app chrome
PANEL = "#121316"          # raised panel
PANEL_HI = "#1A1C21"       # hover / active panel
INK_PRIMARY = "#FFFFFF"
INK_SECONDARY = "#AFAFAF"
INK_MUTED = "#7C818A"      # axis labels, ticks
GRIDLINE = "#1E2024"
BASELINE = "#2A2D33"

# --------------------------------------------------------------------------
# Racing accent
# --------------------------------------------------------------------------
#
# Formula 1's own red, used for UI furniture only - never as a data colour,
# so an accent can never be mistaken for a series. It measures 4.03:1 against
# the canvas, which clears the 3:1 bar for marks and rules but not the 4.5:1
# bar for small text, so a brighter step is used wherever the accent has to
# carry words.

ACCENT = "#E10600"         # fills, rules, active states      (4.03:1)
ACCENT_TEXT = "#FF2D0A"    # small uppercase labels           (5.37:1)
ACCENT_DIM = "#5A0A05"     # inactive / track-behind states

# --------------------------------------------------------------------------
# Series identity - fixed order, assigned in sequence, never cycled
# --------------------------------------------------------------------------

SERIES = [
    "#3987e5",  # 1 blue
    "#d95926",  # 2 orange
    "#199e70",  # 3 aqua
    "#c98500",  # 4 yellow
    "#d55181",  # 5 magenta
    "#008300",  # 6 green
    "#9085e9",  # 7 violet
    "#e66767",  # 8 red
]

# The two-lap comparison is a reference-vs-challenger job, so it takes the
# first two slots rather than team colours. Team colours would collide
# outright for two drivers from the same team; the team is shown as a text
# label instead, where it cannot be misread.
REF_COLOUR = SERIES[0]
CMP_COLOUR = SERIES[1]

# Diverging pair for signed quantities (who is faster where). Two hues that
# read as opposite, with a neutral grey midpoint so "no difference" reads as
# nothing at all.
DIVERGING = [
    [0.0, "#184f95"],   # reference clearly ahead
    [0.25, "#3987e5"],
    [0.5, "#4a4a46"],   # neutral - no meaningful difference
    [0.75, "#e66767"],
    [1.0, "#b03030"],   # comparison clearly ahead
]

# --------------------------------------------------------------------------
# Domain colours
# --------------------------------------------------------------------------

def compound_colour(compound: str) -> str:
    """Official Pirelli colour for a compound. Defined once, in config."""
    return COMPOUND_COLOURS.get(str(compound).upper(), COMPOUND_COLOURS["UNKNOWN"])


def series_colour(i: int) -> str:
    """Categorical slot by position. Never cycles past the palette."""
    return SERIES[i % len(SERIES)]


def team_colour(raw: str | None) -> str | None:
    """FastF1 team colour as a hex string, or None when unavailable."""
    if not raw or str(raw).lower() in {"nan", "none", ""}:
        return None
    value = str(raw).strip()
    return value if value.startswith("#") else f"#{value}"


# --------------------------------------------------------------------------
# Plotly template
# --------------------------------------------------------------------------

FONT_FAMILY = 'system-ui, -apple-system, "Segoe UI", sans-serif'

_AXIS = dict(
    gridcolor=GRIDLINE,
    linecolor=BASELINE,
    zerolinecolor=BASELINE,
    tickfont=dict(color=INK_MUTED, size=11),
    title=dict(font=dict(color=INK_SECONDARY, size=12)),
    showline=True,
    ticks="outside",
    ticklen=4,
    tickcolor=BASELINE,
)

PITWALL_TEMPLATE = go.layout.Template(
    layout=dict(
        paper_bgcolor=SURFACE,
        plot_bgcolor=SURFACE,
        font=dict(family=FONT_FAMILY, color=INK_SECONDARY, size=12),
        title=dict(font=dict(color=INK_PRIMARY, size=15), x=0, xanchor="left"),
        xaxis=_AXIS,
        yaxis=_AXIS,
        colorway=SERIES,
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            font=dict(color=INK_SECONDARY, size=11),
            orientation="h",
            yanchor="bottom", y=1.01,
            xanchor="left", x=0,
        ),
        hoverlabel=dict(
            bgcolor=PANEL,
            bordercolor=BASELINE,
            font=dict(family=FONT_FAMILY, color=INK_PRIMARY, size=12),
        ),
        margin=dict(l=56, r=24, t=48, b=44),
    )
)

pio.templates["pitwall"] = PITWALL_TEMPLATE


def apply(fig: go.Figure, *, height: int | None = None,
          title: str | None = None) -> go.Figure:
    """Apply the shared template and the layout rules every chart follows."""
    fig.update_layout(template="pitwall", hovermode="x unified")
    if height is not None:
        fig.update_layout(height=height)
    if title is not None:
        fig.update_layout(title=title)
    return fig


# Charts are read, not decorated: strip the plot-manipulation toolbar down to
# what a reader actually uses.
PLOTLY_CONFIG = {
    "displaylogo": False,
    "modeBarButtonsToRemove": [
        "select2d", "lasso2d", "autoScale2d", "toggleSpikelines",
    ],
    "displayModeBar": "hover",
}
