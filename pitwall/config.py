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

# FastF1 reports positional X/Y in tenths of a metre. Dividing by this turns
# the arc length of a lap's position trace into metres.
POSITION_UNITS_PER_M = 10.0

# Measure a lap's distance axis from the position trace rather than by
# integrating Speed over time, whenever position data is available.
#
# FastF1's own ``Distance`` is the speed integral, which inherits every defect
# of the speed channel: a dropout or a mis-scaled stretch shifts every sample
# after it, and the error accumulates to the end of the lap. Arc length along
# X/Y is a direct measurement with no accumulation, and it is the same basis
# the circuit-info corner distances use - so corner markers land where the
# corners actually are.
#
# Measured over the 2026 sessions this was introduced for, per-lap length:
#
#   circuit            speed-integral IQR   position IQR   official length
#   Shanghai (Sprint)        419.1 m           15.6 m         5451 m
#   Suzuka (R)                34.2 m            9.6 m         5807 m
#
# The position median lands within 1 m of Shanghai's official length while the
# speed integral scatters over ±10%. The scatter is what MAX_LAP_LENGTH_DEVIATION
# was rejecting - 69% of that sprint's laps - so this recovers laps that were
# never actually broken, rather than loosening the guard to admit ones that are.
DISTANCE_FROM_POSITION = True

# Reject a lap's position trace outright when this fraction of its *moving*
# samples did not move. A position sample that repeats its predecessor while
# the speed channel says the car covered several metres is a stale reading
# being re-sent, not a measurement of where the car was.
#
# This is the failure mode the arc-length measurement above cannot survive.
# In 2026/11_R (Hungary) the position feed froze at around lap 14 and stayed
# frozen for the rest of the race: 92% of raw position samples from there on
# are byte-identical to the one before, and the arc length of every affected
# lap comes out at exactly 3649.8 m - the same value for hundreds of laps,
# which is a cached path being replayed rather than 20 cars driving.
#
#   laps 1-13    stale fraction ~0.00   arc 4310 m   speed integral 4330 m
#   laps 14-70   stale fraction ~0.60   arc 3650 m   speed integral 4325 m
#
# Because the corrupt laps were the *majority*, they set the session median
# that MAX_LAP_LENGTH_DEVIATION is measured against, and the handful of
# healthy laps were rejected as the anomaly. Falling back to the speed
# integral for a stale trace keeps the lap and loses only its X/Y - the same
# trade as the car-data fallback in ``ingest._lap_telemetry``.
#
# 0.10 sits an order of magnitude clear of both populations; a genuinely
# stationary car is excluded from the denominator rather than counted as
# stale, so a spin or a red-flag crawl cannot trip it.
MAX_STALE_POSITION_FRACTION = 0.10

# A position step below this many metres, over an interval where the speed
# channel says the car moved, counts as "did not move". The feed quantises
# X/Y to whole tenths of a metre, so this is comfortably above its resolution
# and well below the ~8-20 m a car covers between samples at racing speed.
STALE_POSITION_STEP_M = 0.5

# Minimum speed-implied movement, in metres, for a sample interval to count
# towards the stale fraction at all. Below this the car is stopped or crawling
# and a repeated coordinate is the truth.
STALE_POSITION_MIN_MOVE_M = 1.0

# How far, in metres, a corner marker may sit from the track map point it was
# aligned onto before transforms.align_corner_distances calls it unreliable.
#
# The alignment is order-constrained, so it can *always* return an increasing
# set of distances - a wrong track map produces a plausible-looking answer
# rather than an obviously broken one. The residual is what distinguishes the
# two: markers genuinely on the circuit land within a car's length of the map,
# so anything beyond this means the map or the markers are not the same circuit.
# Generous on purpose - FastF1's markers sit at the geometric apex while the map
# follows the racing line, which parts them by a car width or two on a wide
# corner.
MAX_CORNER_SNAP_M = 50.0

# Reject a gridded lap whose speed trace lines up with the session's reference
# lap only after being rotated by more than this fraction of a lap.
#
# MAX_LAP_LENGTH_DEVIATION guards the *scale* of a lap's distance axis. This
# guards its *phase*: whether the trace actually begins at the start/finish
# line. A lap can pass the length check and still be anchored in the middle of
# the circuit, and that failure is invisible - the trace is a complete, normal,
# correct-duration lap, just rotated - while being the worst kind of wrong for
# corner analysis, which would then print "T4" over a segment that is nowhere
# near T4.
#
# 2026/11_R is where this surfaced. FastF1 derives each lap's window from the
# timing feed's line crossings; once Hungary's feed degraded the windows kept
# the right *duration* (lap times stay plausible to a tenth) but drifted around
# the circuit, so VER's lap 66 begins at 117 km/h - the car is mid-corner at
# what FastF1 calls the start/finish line.
#
# Measured across 2026 races, as a fraction of a lap:
#
#   session      flying laps   within 2% of the reference   median offset
#   06_R Monaco     1205                100.0%                  0.2%
#   07_R Barcelona  1112                100.0%                  0.1%
#   09_R silverst.   971                100.0%                  0.1%
#   10_R Spa         745                100.0%                  0.1%
#   11_R Hungary     284                 36.3%                 13.4%
#
# A healthy session sits two orders of magnitude inside this threshold, so it
# costs nothing where the feed works and is the only thing that catches the
# defect where it does not.
MAX_START_LINE_OFFSET = 0.02

# Only store telemetry for laps within this multiple of the session's best.
# In qualifying a cooldown lap is a full lap (so it passes the length check)
# but carries no comparative value and would only bloat the dataset.
#
# A race is the opposite case. The slow laps *are* the analysis: safety-car
# laps, the fuel-heavy opening stint, a lap spent stuck in traffic. Cutting
# them would punch holes in the lap selector at exactly the lap numbers a
# reader goes looking for, so races keep every flying lap. What still guards
# against a genuinely broken trace is MAX_LAP_LENGTH_DEVIATION, which is a
# geometric check rather than a pace one - the pace cutoff was only ever a
# size trade, and for races that trade is now made by LAPS_PER_DRIVER.
#
# Sprint qualifying is a qualifying session in every respect that matters
# here - short runs, a cooldown lap between them - so it takes qualifying's
# settings rather than the default. The sprint race is a short race and wants
# exactly what the race wants: every flying lap kept, so lap-by-lap corner
# analysis works across the whole sprint. Only practice now falls through to
# the defaults.
TELEMETRY_PACE_CUTOFF = {"Q": 1.10, "SQ": 1.10, "R": None, "Sprint": None}
TELEMETRY_PACE_CUTOFF_DEFAULT = 1.10

# How many of each driver's fastest flying laps keep full telemetry traces.
# This is the dataset's size/depth trade: traces are ~100x the size of a lap
# table row, so every extra lap is paid for in the committed repository.
# Qualifying keeps enough to compare a driver's own runs.  For races, 0 means
# "all valid flying laps" — every lap that survives pit-in/out, deleted-lap
# and pace-cutoff filtering gets a full telemetry trace, enabling true
# lap-by-lap corner analysis across the entire race.  The *lap table* is
# unaffected: it always holds every lap regardless of this setting.
LAPS_PER_DRIVER = {"Q": 5, "SQ": 5, "R": 0, "Sprint": 0}
LAPS_PER_DRIVER_DEFAULT = 1

# --------------------------------------------------------------------------
# Partial laps
# --------------------------------------------------------------------------

# Whether to keep laps that do not cover the whole track: lap 1 (starts from
# a grid box, not the line), in-laps and out-laps. They are stored against the
# *sub-range of the standard grid they actually cover*, with the rest of the
# grid left NaN - never stretched to fill it, which is what made them
# unusable before. Qualifying has no use for them; a race does, and lap 1 is
# the single most-watched lap of the weekend.
STORE_PARTIAL_LAPS = {"Q": False, "SQ": False, "R": True, "Sprint": True}
STORE_PARTIAL_LAPS_DEFAULT = False

# A partial lap is only worth storing if it covers enough of the track to
# compare. Below this fraction the lap is mostly pit lane.
MIN_PARTIAL_COVERAGE = 0.25

# Flag a session that asked for every lap (LAPS_PER_DRIVER 0) but stored far
# fewer. A healthy race or sprint lands at 96-100%; the floor sits well below
# that so ordinary source-feed gaps stay quiet and a real regression does not.
# Without this the ETL reported a race holding 93 laps of 1258 as simply "ok".
MIN_TELEMETRY_COVERAGE = 0.90

# How far a telemetry sample must sit from the racing line before it counts as
# pit lane rather than track. The pit lane runs parallel to the main straight
# at most circuits, typically 15-25 m away centre-to-centre, while the track
# itself is ~6 m half-width; the trackmap it is measured against is sampled
# every ~5-6 m, which bounds the nearest-neighbour error at ~3 m.
PIT_LANE_OFFSET_M = 12.0

# Lap kinds recorded in the telemetry artefact. "flying" laps cover the whole
# track; the rest are partial and carry a coverage range.
LAP_KIND_FLYING = "flying"
LAP_KIND_START = "start"    # lap 1, from the grid box to the line
LAP_KIND_IN = "in"          # the line to pit entry
LAP_KIND_OUT = "out"        # pit exit to the line

# --------------------------------------------------------------------------
# Chart rendering
# --------------------------------------------------------------------------

# The circuit map is drawn as mini-sectors - short constant-coloured lengths of
# track - rather than one point per grid sample. Plotly cannot colour a single
# line per vertex, so the alternatives are a marker per sample (which reads as
# a scatter plot shaped like a track) or one trace per sample (~1000 traces,
# which is unusable). Binning is the third way, and it is also the convention
# broadcast graphics already use, so the shape is one a viewer recognises.
#
# 96 bins over the GRID_POINTS=1000 grid is ~10 samples per bin, ~55 m at a
# 5.5 km lap: short enough that a braking zone and the corner it feeds land in
# different bins, long enough to keep the figure near 100 traces.
TRACKMAP_MINI_SECTORS = 96

# The compound facets on the degradation scatter wrap into a grid at this many
# columns rather than running as one row. A race uses three or four compounds,
# and four panels side by side leaves each about 70 px on a 320 px phone -
# narrower than a single tyre-age axis label. Two columns keeps every panel
# wide enough to read a trend in at any width the app supports.
DEGRADATION_FACET_COLUMNS = 2

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
# Circuit identity
# --------------------------------------------------------------------------

# Two trackmaps are the same circuit when their outlines - each centred and
# scaled into a unit box, then sampled at matching points on the distance
# grid - differ by less than this mean per-point distance.
#
# Neither name in the manifest is a usable key for this. FastF1's `Location`
# renamed the same circuit twice inside this dataset ("Miami" -> "Miami
# Gardens" in 2025, "Monaco" -> "Monte Carlo" in 2026), and `EventName` fails
# the other way round (Barcelona is the "Spanish" Grand Prix in 2024-25 and
# the "Barcelona" Grand Prix in 2026). The shape is what is actually
# duplicated, so match on the shape.
#
# Measured over the 2024-2026 dataset the two groups are nowhere near each
# other: the known re-spellings sit at 0.003 and 0.005, while the closest
# genuinely different pair of circuits (Jeddah/Imola) sits at 0.069. This
# threshold is placed in the empty space between them, an order of magnitude
# clear of both.
CIRCUIT_MATCH_TOL = 0.02

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

# Session codes that are raced rather than run against the clock. Same split
# the dicts above already make: a sprint keeps every flying lap and its stored
# laps are a chronology, so anything that orders or groups laps by lap number
# has to treat "Sprint" exactly as it treats "R".
RACE_SESSIONS = ("R", "Sprint")

# The sessions worth opening on. The app used to land on round 1 of the most
# recent season, which is a season opener and rarely the race anyone
# remembers - a first-time reader met a page with nothing much on it. These are
# the three worked examples the README leads with, each one a case where the
# analysis has a visible answer.
#
# Nothing here may be assumed to exist: a dataset built with a different set of
# rounds has to fall through to the picker's own default rather than fail, so
# every consumer checks the slug against the manifest first.
#
# `page` is an app route rather than an analysis constant. It lives here anyway
# because the featured list is one thing, and splitting it across two files to
# honour the layering would make it two things that have to be kept in step.
FEATURED_SESSIONS = (
    {
        "slug": "2024/12_Q",
        "page": "pages/1_Corner_Analysis.py",
        "title": "Silverstone 2024 · Russell vs Verstappen",
        "blurb": "0.384 s over one qualifying lap — and 0.326 s of it is won "
                 "in the corners, not on the straights.",
        "params": {"drivers": "RUS,VER"},
    },
    {
        "slug": "2024/01_R",
        "page": "pages/2_Race_Arc.py",
        "title": "Bahrain 2024 · how fast the soft went away",
        "blurb": "Soft 0.123 s/lap against hard 0.105 s/lap, with the "
                 "confidence intervals that say whether to believe it.",
        "params": {"view": "Tyre Degradation"},
    },
    {
        "slug": "2024/01_R",
        "page": "pages/2_Race_Arc.py",
        "title": "Bahrain 2024 · the track sped up while lap times slowed",
        "blurb": "A trend line says the circuit lost 1.053 s. With tyre and "
                 "fuel removed it gained 0.292 s — the naive read has the "
                 "sign wrong, not just the size.",
        "params": {"view": "Track Evolution"},
    },
)

SESSION_LABELS = {
    "FP1": "Practice 1",
    "FP2": "Practice 2",
    "FP3": "Practice 3",
    "SQ": "Sprint Qualifying",
    "Sprint": "Sprint",
    "Q": "Qualifying",
    "R": "Race",
}
