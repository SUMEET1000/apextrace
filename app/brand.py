"""Visual identity: the CSS design system and the racing imagery.

The look is modelled on motorsport-sale sites - near-black canvas, a single
hot accent, huge condensed uppercase display type, and small wide-tracked
labels - with Formula 1's own red in place of amber.

All imagery is **generated**, not stock: circuit outlines come from this
project's own telemetry, and the flag/kerb motifs are CSS gradients and inline
SVG. That means no external image requests, no licensing question, and
artwork that is genuinely specific to the session on screen.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from pitwall.viz import theme

# Display face for headings only. Body, labels and every chart stay in Inter,
# so data never has to be read through a display face.
FONT_IMPORT = (
    "@import url('https://fonts.googleapis.com/css2?"
    "family=Anton&family=Barlow+Condensed:wght@500;600;700&"
    "family=Inter:wght@400;500;600;700&display=swap');"
)

DISPLAY_STACK = "'Anton', 'Arial Narrow', 'Haettenschweiler', sans-serif"
LABEL_STACK = "'Barlow Condensed', 'Arial Narrow', sans-serif"
BODY_STACK = "'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif"


def css() -> str:
    """The whole design system, injected once per page."""
    t = theme
    return f"""
<style>
{FONT_IMPORT}

:root {{
  --canvas: {t.SURFACE};
  --panel: {t.PANEL};
  --panel-hi: {t.PANEL_HI};
  --accent: {t.ACCENT};
  --accent-text: {t.ACCENT_TEXT};
  --ink: {t.INK_PRIMARY};
  --ink-2: {t.INK_SECONDARY};
  --ink-3: {t.INK_MUTED};
  --line: {t.GRIDLINE};
  --rule: {t.BASELINE};
}}

/* ---------------------------------------------------------------- shell */

.stApp {{ background: var(--canvas); }}
html, body, [class*="css"] {{ font-family: {BODY_STACK}; }}

/* Trim Streamlit's default top padding so the hero can sit flush. */
.block-container {{ padding-top: 2.2rem !important; max-width: 1500px; }}
header[data-testid="stHeader"] {{ background: transparent; }}
#MainMenu, footer {{ visibility: hidden; }}
/* Streamlit's own Deploy/toolbar chrome would sit on top of the hero. */
[data-testid="stToolbar"], [data-testid="stDecoration"],
[data-testid="stAppDeployButton"] {{ display: none !important; }}

/* Sidebar nav: uppercase condensed, with the accent marking the active page. */
[data-testid="stSidebarNavLink"] span {{
  font-family: {LABEL_STACK}; text-transform: uppercase;
  letter-spacing: .1em; font-weight: 600; font-size: .92rem; }}
[data-testid="stSidebarNavLink"][aria-current="page"] {{
  background: rgba(225,6,0,.14) !important;
  box-shadow: inset 3px 0 0 var(--accent); }}

/* Carbon-weave canvas: two fine diagonal gradients. Subtle enough to read
   as texture rather than pattern, and costs no image request. */
.stApp::before {{
  content: ""; position: fixed; inset: 0; pointer-events: none; z-index: 0;
  background-image:
    repeating-linear-gradient(45deg,  rgba(255,255,255,.014) 0 2px, transparent 2px 4px),
    repeating-linear-gradient(-45deg, rgba(255,255,255,.014) 0 2px, transparent 2px 4px);
}}
.block-container {{ position: relative; z-index: 1; }}

/* ------------------------------------------------------------ typography */

h1, h2, h3 {{ font-family: {DISPLAY_STACK} !important;
  text-transform: uppercase; letter-spacing: .01em; color: var(--ink) !important;
  font-weight: 400 !important; line-height: .96 !important; }}
h1 {{ font-size: clamp(2.6rem, 6vw, 4.6rem) !important; margin: 0 0 .3rem 0 !important; }}
h2 {{ font-size: clamp(1.7rem, 3vw, 2.4rem) !important; }}
h3 {{ font-size: clamp(1.2rem, 2vw, 1.6rem) !important; }}

.pw-kicker {{
  font-family: {LABEL_STACK}; font-weight: 700; font-size: .78rem;
  letter-spacing: .22em; text-transform: uppercase; color: var(--accent-text);
  display: flex; align-items: center; gap: .6rem; margin-bottom: .5rem;
}}
.pw-kicker::before {{
  content: ""; width: 26px; height: 3px; background: var(--accent);
  display: inline-block;
}}
.pw-kicker--muted {{ color: var(--ink-3); }}
.pw-kicker--muted::before {{ background: var(--ink-3); }}

.pw-caption {{ color: var(--ink-3); font-size: .82rem; line-height: 1.5;
  margin: -.35rem 0 1.15rem 0; max-width: 78ch; }}

/* ------------------------------------------------------------- the hero */

.pw-hero {{
  position: relative; overflow: hidden; border-radius: 14px;
  padding: 2.6rem 2.4rem 2.2rem; margin-bottom: 1.4rem;
  background:
    radial-gradient(1100px 420px at 82% 12%, rgba(225,6,0,.20), transparent 62%),
    linear-gradient(105deg, #0c0d0f 0%, #121316 48%, #0a0a0b 100%);
  border: 1px solid var(--line);
}}
/* Speed lines raking across the hero. */
.pw-hero::after {{
  content: ""; position: absolute; inset: 0; pointer-events: none;
  background: repeating-linear-gradient(100deg,
    transparent 0 58px, rgba(255,255,255,.028) 58px 60px);
  mask-image: linear-gradient(90deg, transparent, #000 55%);
}}
.pw-hero > * {{ position: relative; z-index: 2; }}
.pw-hero-sub {{ color: var(--ink-2); font-size: 1.02rem; max-width: 62ch;
  line-height: 1.6; margin-top: .5rem; }}
.pw-hero-art {{ position: absolute; right: 2.2rem; top: 50%;
  transform: translateY(-50%); opacity: .95; z-index: 1; }}
/* The circuit outline is absolutely positioned, so on a narrow screen it
   runs straight through the headline. Drop it rather than let it obscure
   the text - it is decoration, the title is not. */
@media (max-width: 900px) {{
  .pw-hero-art {{ display: none; }}
  .pw-hero {{ padding: 1.8rem 1.4rem 1.5rem; }}
}}

/* Checkered finish strip. Pure CSS - two offset conic gradients. */
.pw-flag {{
  height: 12px; border-radius: 2px; margin: .2rem 0 1.3rem 0;
  background:
    conic-gradient(#fff 25%, transparent 0 50%, #fff 0 75%, transparent 0) 0 0/12px 12px,
    #0d0d0d;
  opacity: .55;
}}
/* Kerb stripe: the red/white rumble at a corner exit. */
.pw-kerb {{
  height: 6px; border-radius: 3px; margin: 1.6rem 0 1.2rem 0;
  background: repeating-linear-gradient(115deg,
    var(--accent) 0 16px, #f2f2f2 16px 32px);
  opacity: .82;
}}

/* -------------------------------------------------------------- surfaces */

.pw-card {{
  background: var(--panel); border: 1px solid var(--line);
  border-radius: 12px; padding: 1.1rem 1.2rem; height: 100%;
  transition: border-color .16s ease, transform .16s ease;
}}
.pw-card:hover {{ border-color: var(--accent); transform: translateY(-2px); }}
.pw-card-title {{ font-family: {LABEL_STACK}; font-weight: 700;
  text-transform: uppercase; letter-spacing: .1em; font-size: 1rem;
  color: var(--ink); margin: .55rem 0 .35rem; }}
.pw-card-body {{ color: var(--ink-3); font-size: .84rem; line-height: 1.5; }}
.pw-card-num {{ font-family: {DISPLAY_STACK}; font-size: 1.5rem;
  color: var(--accent); line-height: 1; }}

.pw-verdict {{
  background: linear-gradient(90deg, rgba(225,6,0,.13), rgba(225,6,0,0) 62%),
              var(--panel);
  border-left: 3px solid var(--accent); border-radius: 0 10px 10px 0;
  padding: 1rem 1.25rem; color: var(--ink-2); line-height: 1.65;
}}
.pw-verdict b {{ color: var(--ink); }}

/* Data rows in the "biggest swings" list. */
.pw-row {{ display: flex; justify-content: space-between; align-items: center;
  padding: .5rem 0; border-bottom: 1px solid var(--line); }}
.pw-row-label {{ font-family: {LABEL_STACK}; font-weight: 600;
  letter-spacing: .06em; text-transform: uppercase; color: var(--ink); }}
.pw-row-value {{ font-variant-numeric: tabular-nums; font-weight: 600; }}

/* ------------------------------------------------------ streamlit widgets */

[data-testid="stMetric"] {{
  background: var(--panel); border: 1px solid var(--line);
  border-radius: 10px; padding: .85rem 1rem;
  border-top: 2px solid var(--accent);
}}
[data-testid="stMetricValue"] {{
  font-family: {DISPLAY_STACK} !important; font-size: 1.85rem !important;
  color: var(--ink) !important; font-variant-numeric: tabular-nums; }}
[data-testid="stMetricLabel"] {{
  font-family: {LABEL_STACK} !important; text-transform: uppercase;
  letter-spacing: .12em; font-size: .74rem !important; color: var(--ink-3) !important; }}
/* Deltas are used as captions here ("1,006 laps · 20 drivers"), not as
   change indicators, so the up/down arrow would assert a direction that
   does not exist. */
[data-testid="stMetricDelta"] {{ font-size: .78rem !important; }}
[data-testid="stMetricDelta"] svg {{ display: none !important; }}

section[data-testid="stSidebar"] {{
  background: #0b0b0c; border-right: 1px solid var(--line); }}
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2 {{ font-size: 1.1rem !important; }}

.stTabs [data-baseweb="tab"] {{
  font-family: {LABEL_STACK}; text-transform: uppercase;
  letter-spacing: .1em; font-weight: 600; }}
.stTabs [aria-selected="true"] {{ color: var(--accent-text) !important; }}

.stButton > button, .stDownloadButton > button {{
  font-family: {LABEL_STACK}; text-transform: uppercase; font-weight: 700;
  letter-spacing: .12em; border-radius: 6px;
  background: var(--accent); color: #fff; border: none; }}
.stButton > button:hover {{ background: #ff2109; color: #fff; }}

div[data-testid="stSliderTickBarMin"], div[data-testid="stSliderTickBarMax"] {{
  color: var(--ink-3); }}

hr {{ border-color: var(--line) !important; }}
</style>
"""


def inject() -> None:
    st.markdown(css(), unsafe_allow_html=True)


# --------------------------------------------------------------------------
# Generated imagery
# --------------------------------------------------------------------------

def circuit_svg(track: pd.DataFrame, *, width: int = 300, height: int = 190,
                stroke: str = theme.ACCENT, glow: bool = True) -> str:
    """Inline SVG outline of the actual circuit, from this session's telemetry.

    Genuinely related artwork: the shape is the lap the drivers on screen
    just drove, not a stock graphic.
    """
    if track is None or track.empty or not {"X", "Y"}.issubset(track.columns):
        return ""

    x = track["X"].to_numpy(dtype="float64")
    y = track["Y"].to_numpy(dtype="float64")
    if len(x) < 3:
        return ""

    # Fit into the viewbox, preserving aspect and flipping Y for screen space.
    pad = 10
    span_x, span_y = np.ptp(x) or 1, np.ptp(y) or 1
    scale = min((width - 2 * pad) / span_x, (height - 2 * pad) / span_y)
    px = (x - x.min()) * scale + pad
    py = (height - pad) - (y - y.min()) * scale
    px += (width - (span_x * scale + 2 * pad)) / 2

    step = max(1, len(px) // 260)  # keep the path small
    points = " ".join(f"{a:.1f},{b:.1f}" for a, b in zip(px[::step], py[::step]))

    filter_def = ""
    filter_attr = ""
    if glow:
        filter_def = (
            '<defs><filter id="pwglow" x="-25%" y="-25%" width="150%" height="150%">'
            '<feGaussianBlur stdDeviation="3.2" result="b"/>'
            '<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>'
            "</filter></defs>"
        )
        filter_attr = ' filter="url(#pwglow)"'

    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'xmlns="http://www.w3.org/2000/svg" role="img" '
        f'aria-label="Outline of the circuit">{filter_def}'
        f'<polyline points="{points}" fill="none" stroke="{stroke}" '
        f'stroke-width="2.6" stroke-linejoin="round" stroke-linecap="round"'
        f"{filter_attr}/></svg>"
    )


def flag_strip() -> None:
    st.markdown('<div class="pw-flag"></div>', unsafe_allow_html=True)


def kerb() -> None:
    st.markdown('<div class="pw-kerb"></div>', unsafe_allow_html=True)


def kicker(text: str, *, muted: bool = False) -> None:
    cls = "pw-kicker pw-kicker--muted" if muted else "pw-kicker"
    st.markdown(f'<div class="{cls}">{text}</div>', unsafe_allow_html=True)


def hero(title: str, subtitle: str, kicker_text: str,
         art: str = "") -> None:
    """Full-width hero block with optional generated circuit art."""
    art_html = f'<div class="pw-hero-art">{art}</div>' if art else ""
    st.markdown(
        f"""<div class="pw-hero">{art_html}
          <div class="pw-kicker">{kicker_text}</div>
          <h1>{title}</h1>
          <div class="pw-hero-sub">{subtitle}</div>
        </div>""",
        unsafe_allow_html=True,
    )


def verdict(html: str) -> None:
    st.markdown(f'<div class="pw-verdict">{html}</div>', unsafe_allow_html=True)
