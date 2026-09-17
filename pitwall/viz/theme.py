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

from typing import Sequence

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio

from pitwall.config import COMPOUND_COLOURS

# --------------------------------------------------------------------------
# Surfaces and ink
# --------------------------------------------------------------------------

# The greys are audited against the canvas the same way the series palette is,
# because they were not: the original set was picked to be unobtrusive and
# ended up unreadable. Measured against SURFACE:
#
#     was                  now
#     PANEL     1.08:1  ->  1.27:1   a card is a surface, not a suggestion
#     GRIDLINE  1.23:1  ->  3.13:1   WCAG 1.4.11 wants 3:1 for a UI boundary
#     BASELINE  1.45:1  ->  4.03:1   axis lines and rules, a step above grid
#
# GRIDLINE is the border token for every card, metric and rule in the app as
# well as the in-plot grid, so it is the one that had to clear 3:1; at 1.23:1
# a card edge was decoration that happened not to be visible. Raising PANEL
# costs a little border-against-panel contrast (2.46:1), which is why PANEL
# stops where it does rather than going further - the border's other side is
# the canvas, where it measures the full 3.13:1.

SURFACE = "#080808"        # near-black canvas, matches the app chrome
PANEL = "#202329"          # raised panel                     (1.27:1)
PANEL_HI = "#2A2E36"       # hover / active panel             (1.47:1)
INK_PRIMARY = "#FFFFFF"
INK_SECONDARY = "#AFAFAF"
INK_MUTED = "#7C818A"      # axis labels, ticks
GRIDLINE = "#5A5F6A"       # card borders, rules, in-plot grid (3.13:1)
BASELINE = "#6A707C"       # axis lines, zero lines, tick marks (4.03:1)

# --------------------------------------------------------------------------
# Racing accent
# --------------------------------------------------------------------------
#
# Formula 1's own red, used for UI furniture only - never as a data colour,
# so an accent can never be mistaken for a series. It measures 4.03:1 against
# the canvas, which clears the 3:1 bar for marks and rules but not the 4.5:1
# bar for small text, so a brighter step is used wherever the accent has to
# carry words.

ACCENT = "#E63946"         # fills, rules, active states
ACCENT_TEXT = "#FF4D5E"    # small uppercase labels
ACCENT_DIM = "#5A0A10"     # inactive / track-behind states

# Hover fill for a solid accent button. Deliberately a step *down* from ACCENT
# rather than up, which is the opposite of the invented #ff2109 it replaces.
# An accent button carries white label text, and on this hue brightness and
# label legibility trade directly against each other: #ff2109 put the label at
# 3.84:1, below the 4.5:1 small-text bar, so the hover state was less readable
# than the resting one. Deepening instead takes the label to 5.99:1 while the
# button itself still reads 3.34:1 against the canvas, clear of the 3:1 bar
# for a UI component.
ACCENT_HOVER = "#C90500"   # accent button hover              (3.34:1)

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

# --------------------------------------------------------------------------
# Broadcast timing semantics
# --------------------------------------------------------------------------
#
# Purple for a session best, green for a personal best, yellow for anything
# slower. This is the one colour convention every F1 viewer already owns, and
# it was missing entirely - lap times were shown in the same generic ink as
# every other number. Measured against SURFACE and against PANEL, since these
# appear as table text on a raised surface:
#
#     TIMING_SESSION_BEST    6.30:1 canvas   4.95:1 panel
#     TIMING_PERSONAL_BEST   8.42:1 canvas   6.62:1 panel
#     TIMING_SLOWER         17.12:1 canvas  13.46:1 panel
#
# The yellow is the broadcast yellow rather than a tint of Pirelli's medium
# gold (#F0C64B): the two must not be confusable, and these sit dE 34.8 apart,
# so "yellow" never has to mean both "medium tyre" and "slower than your best".
#
# As everywhere else in this app, colour is not the encoding. Every table that
# uses these also states the status in words, because three saturated hues are
# exactly the kind of thing a red/green deficiency collapses.
TIMING_SESSION_BEST = "#C06BF0"
TIMING_PERSONAL_BEST = "#3FBF5F"
TIMING_SLOWER = "#FFF200"

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


# A field-wide chart shows up to twenty drivers, and the categorical palette
# has eight slots. Team colour is what an F1 reader already uses to find a car,
# so it beats an arbitrary eighth-of-a-palette in every case except one:
# teammates share it exactly. That case takes a second, non-colour channel -
# the order below, applied in classification order within each team, so the
# pairing is deterministic rather than dependent on who is drawn first.
TEAMMATE_DASH = ("solid", "dash", "dot")


def team_styles(results: pd.DataFrame | None,
                drivers: Sequence[str]) -> dict[str, tuple[str, str]]:
    """Driver -> (team colour, dash pattern) for the drivers on one chart.

    Returns ``{}`` when the results artefact carries no usable team colour,
    which is the signal for a caller to fall back to the categorical series
    palette rather than to invent a mapping.

    The dash counter runs over *the drivers being charted*, not the whole
    field, so a driver whose teammate is not on the chart is drawn solid -
    there is nothing for them to collide with.
    """
    if results is None or results.empty:
        return {}
    if not {"Abbreviation", "TeamName", "TeamColor"}.issubset(results.columns):
        return {}

    wanted = set(map(str, drivers))
    rows = results[results["Abbreviation"].astype(str).isin(wanted)]
    if rows.empty:
        return {}
    if "Position" in rows.columns:
        rows = rows.sort_values("Position")

    styles: dict[str, tuple[str, str]] = {}
    seen: dict[str, int] = {}
    for row in rows.itertuples():
        colour = team_colour(row.TeamColor)
        if colour is None:
            continue
        team = str(row.TeamName)
        n = seen.get(team, 0)
        seen[team] = n + 1
        styles[str(row.Abbreviation)] = (
            colour, TEAMMATE_DASH[min(n, len(TEAMMATE_DASH) - 1)])
    return styles


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
        "autoScale2d", "toggleSpikelines",
    ],
    "displayModeBar": "hover",
    # Without this plotly.js writes a literal pixel width onto its own
    # container and never revisits it, so a chart is frozen at whatever it
    # measured on the frame it first drew - which is plotly's 700px default,
    # not the column it is in. Every chart then renders narrow until a window
    # resize; the track maps, the only figures with an aspect constraint, get
    # a wrong *scale* out of it rather than merely a wrong width.
    "responsive": True,
}
