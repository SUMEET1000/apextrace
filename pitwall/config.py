"""Project-wide constants: paths, tyre/telemetry conventions, model assumptions.

Everything here is a *stated assumption*. The fuel-correction numbers in
particular are estimates, not measurements - they are surfaced as UI controls
so a user can see what the analysis depends on and change it.
"""

from __future__ import annotations

from pathlib import Path

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "raw_cache"
PROCESSED_DIR = DATA_DIR / "processed"
MANIFEST_PATH = PROCESSED_DIR / "manifest.parquet"

# --------------------------------------------------------------------------
# Telemetry resampling
# --------------------------------------------------------------------------

# Every lap is resampled onto a uniform distance grid of this many points.
# At a 5.8 km lap that is ~5.8 m per sample, finer than raw FastF1 telemetry
# at racing speed (~8-20 m between samples at 4-10 Hz), so no meaningful
# resolution is lost. A fixed grid makes driver-vs-driver comparison
# elementwise arithmetic instead of a merge-and-interpolate.
GRID_POINTS = 1000

# Channels interpolated linearly (physically continuous).
CONTINUOUS_CHANNELS = ("Speed", "Throttle", "RPM", "X", "Y", "Z", "Time")

# Channels held piecewise-constant (discrete states - interpolating a gear
# of 4 and 6 into 5 would invent a shift that never happened).
DISCRETE_CHANNELS = ("Brake", "nGear", "DRS")

# Reject a lap whose telemetry-measured length deviates from the session
# median by more than this fraction. Genuine racing-line variation is under
# 1%; larger gaps mean a partial lap (an in-lap ends in the pit lane, so it
# is both shorter and slower) which would be stretched across the whole
# track by the grid and corrupt every comparison against it.
MAX_LAP_LENGTH_DEVIATION = 0.015

# Only store telemetry for laps within this multiple of the session's best.
# Cooldown and heavily compromised laps are full laps (so they pass the length
# check) but carry no comparative value and would only bloat the dataset.
TELEMETRY_PACE_CUTOFF = 1.10

# --------------------------------------------------------------------------
# Corner segmentation
# --------------------------------------------------------------------------

# A corner window runs from the midpoint of the preceding straight to the
# midpoint of the following one, but is clipped to these limits so that a
# single corner at the end of a long straight does not absorb the whole
# straight and dominate its own time delta.
CORNER_MAX_ENTRY_M = 400.0
CORNER_MAX_EXIT_M = 300.0

# Throttle percentage counted as "back on power".
THROTTLE_ON_PCT = 95.0

# --------------------------------------------------------------------------
# Lap cleaning
# --------------------------------------------------------------------------

# TrackStatus "1" == all clear. Anything else (yellow, SC, VSC, red) makes a
# lap time meaningless for pace analysis.
TRACK_STATUS_CLEAR = "1"

# Per-stint outlier rejection: drop laps slower than this quantile-based
# threshold, which removes traffic-affected and lift-and-coast laps.
STINT_OUTLIER_QUANTILE = 0.95
STINT_OUTLIER_FACTOR = 1.07  # also drop anything over 107% of the stint best

# --------------------------------------------------------------------------
# Fuel correction
# --------------------------------------------------------------------------

# Seconds per lap gained per kg of fuel burned. Community consensus sits
# around 0.03-0.035 s/kg; it varies by circuit (more at high-energy tracks).
FUEL_EFFECT_S_PER_KG = 0.032

# Starting fuel load in kg. The 2026 regulations cut race fuel substantially,
# so this is season-dependent.
RACE_FUEL_KG = {2024: 110.0, 2025: 110.0, 2026: 70.0}
DEFAULT_RACE_FUEL_KG = 100.0


def race_fuel_kg(year: int) -> float:
    """Starting fuel load for a season, falling back to a sane default."""
    return RACE_FUEL_KG.get(year, DEFAULT_RACE_FUEL_KG)


# --------------------------------------------------------------------------
# Colour conventions
# --------------------------------------------------------------------------

# Official Pirelli compound colours. Fixed across every chart in the app so
# that "yellow" always means medium and never means a driver.
COMPOUND_COLOURS = {
    "SOFT": "#E8484D",
    "MEDIUM": "#F0C64B",
    "HARD": "#EDEDED",
    "INTERMEDIATE": "#43B02A",
    "WET": "#3A82D8",
    "UNKNOWN": "#7A7F87",
}

COMPOUND_ORDER = ["SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET", "UNKNOWN"]

# Fallback cycle for driver series when a team colour is missing or when two
# drivers from the same team are compared (identical team colours would make
# the comparison unreadable).
DRIVER_FALLBACK_COLOURS = ["#00D2FF", "#FF9E1B", "#B47CFF", "#4CE0B3"]

SESSION_LABELS = {"Q": "Qualifying", "R": "Race"}
