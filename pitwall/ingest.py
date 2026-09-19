"""FastF1 boundary layer: the only module that talks to the F1 API.

Keeping every network call behind this module means the rest of the package
operates on plain DataFrames and can be tested without a network connection.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Iterable

import fastf1
import numpy as np
import pandas as pd

from pitwall.config import (
    CACHE_DIR,
    DISTANCE_FROM_POSITION,
    GRID_POINTS,
    LAP_KIND_FLYING,
    LAP_KIND_IN,
    LAP_KIND_OUT,
    LAP_KIND_START,
    MAX_LAP_LENGTH_DEVIATION,
    MAX_STALE_POSITION_FRACTION,
    MAX_START_LINE_OFFSET,
    MIN_PARTIAL_COVERAGE,
    TELEMETRY_PACE_CUTOFF_DEFAULT,
)
from pitwall.transforms import (
    distance_from_position,
    encode_grid,
    extract_track_map,
    resample_to_distance_grid,
    stale_position_fraction,
    start_line_offset,
    trim_to_track,
)

# How each lap kind sits against the start/finish line, and which end of it
# (if any) is pit lane that must be trimmed first.
#   anchor "full" - covers the track; "head" - starts at the line;
#                   "tail" - ends at the line.
#   side   "lead" - pit lane comes first; "trail" - pit lane comes last.
_ANCHOR_BY_KIND: dict[str, tuple[str, str | None]] = {
    LAP_KIND_FLYING: ("full", None),
    LAP_KIND_START: ("tail", None),   # grid box -> line; no pit lane involved
    LAP_KIND_IN: ("head", "trail"),   # line -> pit entry
    LAP_KIND_OUT: ("tail", "lead"),   # pit exit -> line
}

log = logging.getLogger(__name__)

_cache_enabled = False


def _lap_telemetry(lap) -> tuple[pd.DataFrame | None, bool]:
    """Best available telemetry for one lap, with position data optional.

    ``lap.get_telemetry()`` merges the car channels with the positional feed.
    When a session's ``pos_data`` is shorter than its ``car_data`` - 2026/06_R
    (Monaco) has 111 min against 201 min - the merge raises
    ``KeyError: 'Date'`` for every lap past the end of the position feed, and
    the lap used to be dropped entirely.

    That was throwing away a complete set of car channels. Nothing downstream
    needs per-lap X/Y: ``encode_grid`` does not store it, and the circuit
    geometry is hoisted into the session-level track map built from a single
    reference lap. So fall back to car data alone, which carries ``Time`` plus
    every stored channel, and derive ``Distance`` the same way the merged path
    does.

    The position feed has a second, quieter failure: it stays *present* but
    goes stale, re-sending the last coordinate it had. 2026/11_R (Hungary)
    froze that way around lap 14 and never recovered. That is worse than an
    absent feed, because nothing raises - the arc length of a frozen trace
    comes out at a plausible 3650 m, the same number for hundreds of laps -
    so :func:`transforms.stale_position_fraction` is checked explicitly and a
    stale trace takes exactly the same car-data-only path as a missing one.

    Returns ``(telemetry, has_position)``. Callers that need the racing line -
    only :func:`transforms.trim_to_track`, for in- and out-laps - must check
    the flag rather than the exception.
    """
    try:
        tel = lap.get_telemetry()
        if tel is not None and {"X", "Y"}.issubset(tel.columns):
            # Finiteness first. Both stale_position_fraction and
            # distance_from_position answer "cannot tell" with 0.0 and an
            # unchanged frame on non-finite coordinates, so a NaN position
            # scored 0% stale and was accepted as healthy - and trim_to_track
            # then fed NaN to a KD-tree query.
            finite = np.isfinite(
                tel[["X", "Y"]].to_numpy(dtype="float64")).all()
            stale = stale_position_fraction(tel) if finite else 1.0
            if not finite:
                log.debug("%s lap %s: position feed has non-finite "
                          "coordinates, using car data alone",
                          lap.get("Driver"), lap.get("LapNumber"))
            elif stale > MAX_STALE_POSITION_FRACTION:
                # The position feed is frozen for this lap - present, but
                # re-sending stale coordinates. Everything it would be used
                # for (arc length, the track map, pit-lane trimming) would be
                # plausible and wrong, so drop the channel and keep the lap.
                log.debug("%s lap %s: position feed %.0f%% stale, using car "
                          "data alone", lap.get("Driver"), lap.get("LapNumber"),
                          stale * 100)
            else:
                return ((distance_from_position(tel) if DISTANCE_FROM_POSITION
                         else tel), True)
    except Exception as exc:  # noqa: BLE001 - fall through to car data
        log.debug("merged telemetry unavailable for %s lap %s: %s",
                  lap.get("Driver"), lap.get("LapNumber"), exc)

    try:
        car = lap.get_car_data()
    except Exception as exc:  # noqa: BLE001 - a lap may lack telemetry entirely
        log.debug("no car data for %s lap %s: %s",
                  lap.get("Driver"), lap.get("LapNumber"), exc)
        return None, False
    if car is None or len(car) < 2:
        return None, False
    return car.add_distance(), False


def enable_cache() -> None:
    """Point FastF1 at the project-local HTTP cache (idempotent).

    The cache is gitignored and regenerable, but it is what makes a repeated
    ETL run take seconds instead of hours.
    """
    global _cache_enabled
    if _cache_enabled:
        return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(str(CACHE_DIR))
    _cache_enabled = True


@dataclass(frozen=True)
class SessionKey:
    """Identifies one session across the ETL, the manifest and the URL bar."""

    year: int
    round: int
    session: str  # "Q" or "R"

    @property
    def slug(self) -> str:
        return f"{self.year}/{self.round:02d}_{self.session}"

    def __str__(self) -> str:
        return self.slug


def get_schedule(year: int) -> pd.DataFrame:
    """Event schedule for a season, testing events excluded."""
    enable_cache()
    sched = fastf1.get_event_schedule(year, include_testing=False)
    return pd.DataFrame(sched)


class RateLimited(RuntimeError):
    """The F1 API's hourly request budget is exhausted.

    Distinct from an ordinary load failure: no amount of retrying inside a
    single run will clear it, so the caller should stop rather than burn
    through the remaining sessions failing.
    """


def load_session(
    key: SessionKey,
    *,
    telemetry: bool = True,
    retries: int = 3,
    backoff_s: float = 20.0,
):
    """Load a FastF1 session, retrying transient failures.

    Rate limiting is handled differently from other errors. The F1 API caps
    requests per hour, so a short backoff cannot clear it - a 60 s wait
    against an hourly budget just fails again. Rate limits are raised as
    :class:`RateLimited` for the caller to stop on; the dataset is resumable,
    so the run can simply be restarted once the budget resets.
    """
    enable_cache()
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            session = fastf1.get_session(key.year, key.round, key.session)
            session.load(
                laps=True,
                telemetry=telemetry,
                weather=True,
                # Race-control messages are where FastF1 gets the Deleted
                # flag from. With them off the column was written for every
                # lap and was False on all 161,941 of them, so both the
                # extract filter below and clean_laps were filtering on a
                # flag nothing could ever set (measured 19 Sept 2026).
                messages=True,
            )
            return session
        except fastf1.RateLimitExceededError as exc:
            raise RateLimited(
                f"F1 API rate limit reached at {key}. The budget is hourly; "
                f"re-run the same command later and it will resume from here."
            ) from exc
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller below
            last_exc = exc
            log.warning("load failed for %s: %s (attempt %d/%d)",
                        key, exc, attempt, retries)
            if attempt < retries:
                time.sleep(backoff_s)
    raise RuntimeError(f"could not load session {key}") from last_exc


# --------------------------------------------------------------------------
# Extraction - each returns a plain, Parquet-ready DataFrame
# --------------------------------------------------------------------------

_LAP_COLUMNS = [
    "Driver", "DriverNumber", "Team", "LapNumber", "Stint", "LapTime",
    "Sector1Time", "Sector2Time", "Sector3Time",
    "SpeedI1", "SpeedI2", "SpeedFL", "SpeedST",
    "Compound", "TyreLife", "FreshTyre", "TrackStatus", "Position",
    "IsPersonalBest", "IsAccurate", "Deleted",
    "PitInTime", "PitOutTime", "LapStartTime",
]


def extract_laps(session) -> pd.DataFrame:
    """Lap table, with timedeltas flattened to float seconds for Parquet."""
    laps = pd.DataFrame(session.laps)
    cols = [c for c in _LAP_COLUMNS if c in laps.columns]
    out = laps[cols].copy()

    # Parquet round-trips timedeltas poorly across engines; store seconds and
    # keep the original column name plus an explicit _s suffix.
    for col in ("LapTime", "Sector1Time", "Sector2Time", "Sector3Time",
                "PitInTime", "PitOutTime", "LapStartTime"):
        if col in out.columns:
            out[f"{col}_s"] = out[col].dt.total_seconds()
            out = out.drop(columns=[col])

    for col in ("Driver", "DriverNumber", "Team", "Compound", "TrackStatus"):
        if col in out.columns:
            out[col] = out[col].astype(str)

    return out.reset_index(drop=True)


def extract_weather(session) -> pd.DataFrame:
    weather = pd.DataFrame(session.weather_data)
    if weather.empty:
        return weather
    out = weather.copy()
    if "Time" in out.columns:
        out["Time_s"] = out["Time"].dt.total_seconds()
        out = out.drop(columns=["Time"])
    return out.reset_index(drop=True)


def extract_results(session) -> pd.DataFrame:
    res = pd.DataFrame(session.results)
    if res.empty:
        return res
    keep = [
        "DriverNumber", "Abbreviation", "FullName", "TeamName", "TeamColor",
        "Position", "ClassifiedPosition", "GridPosition", "Status", "Points",
        "Q1", "Q2", "Q3", "Time",
    ]
    out = res[[c for c in keep if c in res.columns]].copy()
    for col in ("Q1", "Q2", "Q3", "Time"):
        if col in out.columns and pd.api.types.is_timedelta64_dtype(out[col]):
            out[f"{col}_s"] = out[col].dt.total_seconds()
            out = out.drop(columns=[col])
    return out.reset_index(drop=True)


def _static_circuit_info(session, exc: Exception):
    """Corner geometry without FastF1's own distance measurement.

    ``Session.get_circuit_info`` does two things: it fetches the circuit's
    *static* corner map - marker X/Y and the track rotation, neither of which
    depends on the session - and then snaps each marker onto
    ``laps.pick_fastest()`` to measure ``Distance``. Only the second step needs
    the position feed, and where that feed is short it raises and takes the
    whole corner map down with it. 2026/06_R is the case: Monaco's fastest lap
    has no position data, ``KeyError: 'Date'`` propagates, and the session was
    stored with no corners at all, so corner analysis was unavailable for a
    race whose telemetry is otherwise 85% complete.

    Losing that step costs us nothing, because ``Distance`` is re-measured
    against the track map afterwards anyway - see
    :func:`transforms.align_corner_distances`, which is a better datum than
    FastF1's arbitrary fastest lap in the first place. So fall back to the
    static map and let the distances arrive as NaN.
    """
    try:
        from fastf1.mvapi import get_circuit_info as static_circuit_info
        circuit_key = session.session_info["Meeting"]["Circuit"]["Key"]
        info = static_circuit_info(year=session.event.year,
                                   circuit_key=circuit_key)
    except Exception as inner:  # noqa: BLE001 - circuit info is optional
        log.warning("no circuit info available: %s (static map also failed: %s)",
                    exc, inner)
        return None
    if info is not None and info.corners is not None and not info.corners.empty:
        log.warning("circuit info fell back to the static corner map (%s); "
                    "marker distances come from the track map", exc)
    return info


def extract_corners(session) -> pd.DataFrame:
    """Corner marker positions from the circuit map.

    ``Distance`` (metres of each apex from the start/finish line) is the
    linchpin of the whole corner-analysis feature - it is what lets telemetry
    be sliced into named corners.
    """
    try:
        info = session.get_circuit_info()
    except Exception as exc:  # noqa: BLE001 - circuit info is optional
        info = _static_circuit_info(session, exc)
    if info is None or info.corners is None or info.corners.empty:
        return pd.DataFrame()

    corners = pd.DataFrame(info.corners).copy()
    corners["Rotation"] = float(getattr(info, "rotation", 0.0) or 0.0)
    if "Letter" in corners.columns:
        corners["Letter"] = corners["Letter"].fillna("").astype(str)
    corners["CornerLabel"] = (
        corners["Number"].astype(int).astype(str) + corners.get("Letter", "")
    )
    return corners.reset_index(drop=True)


def _driver_laps_to_grid(laps_subset: pd.DataFrame,
                         n_points: int,
                         *,
                         kind: str = LAP_KIND_FLYING,
                         track_length: float | None = None,
                         track_xy: np.ndarray | None = None) -> pd.DataFrame:
    """Resample a set of laps onto the distance grid and stack them.

    ``kind`` selects how each lap is placed against the start/finish line:
    a flying lap fills the grid, while a partial lap is anchored to the end
    of the track it actually covers (see
    :func:`transforms.resample_to_distance_grid`). Partial kinds need
    ``track_length``; the two pit kinds also need ``track_xy`` so the
    pit-lane run can be trimmed before anchoring.
    """
    anchor, side = _ANCHOR_BY_KIND[kind]
    frames = []
    for _, lap in laps_subset.iterrows():
        tel, has_position = _lap_telemetry(lap)
        if tel is None or len(tel) < 2:
            continue

        if side is not None:
            # Trimming the pit lane off an in- or out-lap is geometric, so a
            # lap with no position data cannot be anchored honestly: its
            # Distance still counts down the pit lane. Drop it rather than
            # store a lap whose corners are offset by the length of the pits.
            if not has_position:
                log.debug("%s lap %s has no position data to trim the pit lane",
                          lap.get("Driver"), lap.get("LapNumber"))
                continue
            if track_xy is not None:
                tel = trim_to_track(tel, track_xy, side)
                if len(tel) < 2:
                    log.debug("%s lap %s is all pit lane",
                              lap.get("Driver"), lap.get("LapNumber"))
                    continue

        try:
            grid = resample_to_distance_grid(
                tel, n_points=n_points, anchor=anchor, track_length=track_length,
            )
        except ValueError as exc:
            log.debug("resample failed for %s lap %s: %s",
                      lap.get("Driver"), lap.get("LapNumber"), exc)
            continue

        # A lap that barely leaves the pits is not a comparison, it is a
        # sliver. Drop it rather than offer it in a selector.
        coverage = float(grid["CovEnd"].iloc[0] - grid["CovStart"].iloc[0])
        if kind != LAP_KIND_FLYING and coverage < MIN_PARTIAL_COVERAGE:
            log.debug("%s lap %s covers only %.0f%% of the track, dropping",
                      lap.get("Driver"), lap.get("LapNumber"), coverage * 100)
            continue

        grid.insert(0, "Driver", str(lap["Driver"]))
        grid.insert(1, "LapNumber", float(lap["LapNumber"]))
        lap_time = lap.get("LapTime")
        grid["LapTime_s"] = (
            lap_time.total_seconds() if pd.notna(lap_time) else np.nan
        )
        grid["Compound"] = str(lap.get("Compound", "UNKNOWN"))
        grid["LapKind"] = kind
        frames.append(grid)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def _reference_lap(telemetry: pd.DataFrame,
                   max_offset: float = MAX_START_LINE_OFFSET
                   ) -> pd.DataFrame | None:
    """The gridded lap the session agrees with, and that carries usable X/Y.

    The reference lap is doing three jobs - it is the circuit geometry stored
    in the track map, it is the racing line :func:`transforms.trim_to_track`
    measures the pit lane against, and it is the datum
    :func:`_drop_misanchored_laps` measures every other lap's phase against.
    The first two need position data. Laps gridded from car data alone (see
    :func:`_lap_telemetry`) have none, so the fastest lap overall is not
    necessarily a usable reference.

    The third job is why the *fastest* lap is not good enough either. A lap can
    be complete, correct-length and quick while its window starts somewhere
    other than the start/finish line, and if that lap becomes the datum then
    every correctly anchored lap in the session measures as offset and gets
    dropped - the guard inverts and deletes the healthy majority. 2026/08_Q is
    the case: 70 of its 88 laps share one phase, the other 18 sit 2.4% (~104 m)
    further round, and the fastest lap is one of the 18. Anchoring on it drops
    the 70. That is the same failure that let a corrupt majority set the median
    for :data:`config.MAX_LAP_LENGTH_DEVIATION` at Hungary, in mirror image.

    So the phase datum is taken by consensus - the offset the largest set of
    mutually consistent laps shares - and the reference is the fastest
    position-carrying lap that agrees with it. Consensus rather than a plain
    median because a degraded feed scatters laps around the lap rather than
    biasing them one way, and a median of scattered phases is not a phase any
    lap actually has.
    """
    if not {"X", "Y"}.issubset(telemetry.columns):
        return None
    # A lap only half-covered by the position feed would give a truncated map,
    # so require every grid point of the candidate to carry X/Y.
    per_lap = telemetry.assign(
        _covered=telemetry["X"].notna() & telemetry["Y"].notna()
    ).groupby(["Driver", "LapNumber"], observed=True).agg(
        covered=("_covered", "all"), lap_time=("LapTime_s", "min"),
    )
    complete = per_lap.loc[per_lap["covered"], "lap_time"].dropna()
    if complete.empty:
        return None

    def lap_of(key) -> pd.DataFrame:
        driver, lap_number = key
        return telemetry[(telemetry["Driver"] == driver)
                         & (telemetry["LapNumber"] == lap_number)]

    ordered = complete.sort_values()
    seed = lap_of(ordered.index[0])
    if "Speed" not in telemetry.columns or len(ordered) == 1:
        return seed

    seed_speed = seed["Speed"].to_numpy(dtype="float64")
    offsets = {
        key: start_line_offset(lap["Speed"].to_numpy(dtype="float64"), seed_speed)
        for key, lap in telemetry.groupby(["Driver", "LapNumber"],
                                          observed=True, sort=False)
    }
    # Half the rejection threshold, because the clustering window has to be
    # narrower than the offset it is trying to resolve. 2026/08_Q's two groups
    # sit 2.4% apart, so a +/-2% window spans both and settles between them, on
    # a phase neither group has - which then reads as "the fastest lap is fine"
    # and keeps the smaller group.
    tol = max_offset / 2
    consensus = _modal_offset(np.fromiter(offsets.values(), dtype="float64"), tol)

    agreed = [key for key in ordered.index
              if abs(offsets.get(key, 0.0) - consensus) <= tol]
    key = agreed[0] if agreed else min(
        ordered.index, key=lambda k: abs(offsets.get(k, 0.0) - consensus))
    if key != ordered.index[0]:
        log.info("reference lap moved to %s L%s: the fastest lap is %.1f%% of "
                 "a lap off the phase %d of %d laps agree on",
                 key[0], key[1], -consensus * 100,
                 sum(abs(o - consensus) <= tol for o in offsets.values()),
                 len(offsets))
    return lap_of(key)


def _modal_offset(offsets: np.ndarray, tol: float) -> float:
    """The offset shared by the largest group of laps within ``tol``.

    A mode rather than a mean or median: the misanchored laps in a degraded
    session sit at scattered phases, and any average of those lands on a phase
    no lap actually has.
    """
    if offsets.size == 0:
        return 0.0
    ordered = np.sort(offsets)
    lo = np.searchsorted(ordered, ordered - tol, side="left")
    hi = np.searchsorted(ordered, ordered + tol, side="right")
    return float(ordered[int(np.argmax(hi - lo))])


def _drop_misanchored_laps(telemetry: pd.DataFrame,
                           ref: pd.DataFrame,
                           max_offset: float) -> pd.DataFrame:
    """Drop laps whose trace does not begin at the start/finish line.

    Each lap's window comes from the timing feed's line crossings. When that
    feed degrades the window can keep the right duration - so the lap time is
    right, the length is right, and every existing guard passes - while
    starting somewhere else entirely on the circuit. 2026/11_R is the case:
    VER's lap 66 begins at 117 km/h, mid-corner.

    A rotated lap is the most dangerous shape of bad data this pipeline can
    store, because it is a complete and internally consistent lap. Every
    corner delta read off it is attributed to the wrong corner, and nothing
    downstream can tell. So it is measured here against the reference lap -
    which is position-anchored by construction, see :func:`_reference_lap` -
    and dropped rather than stored.
    """
    if "Speed" not in telemetry.columns or "Speed" not in ref.columns:
        return telemetry
    reference = ref["Speed"].to_numpy(dtype="float64")

    misanchored = []
    for (driver, lap_number), lap in telemetry.groupby(
            ["Driver", "LapNumber"], observed=True, sort=False):
        offset = start_line_offset(lap["Speed"].to_numpy(dtype="float64"),
                                   reference)
        if abs(offset) > max_offset:
            misanchored.append((driver, lap_number, offset))

    if not misanchored:
        return telemetry

    log.warning("dropping %d lap(s) not anchored to the start/finish line "
                "(worst %.0f%% of a lap out): %s",
                len(misanchored),
                100 * max(abs(o) for _, _, o in misanchored),
                ", ".join(f"{d} L{n:.0f}" for d, n, _ in misanchored))
    keys = {(d, n) for d, n, _ in misanchored}
    dropped = pd.Series(
        list(zip(telemetry["Driver"], telemetry["LapNumber"])),
        index=telemetry.index,
    ).isin(keys)
    return telemetry[~dropped].reset_index(drop=True)


def extract_telemetry(
    session,
    *,
    laps_per_driver: int,
    n_points: int = GRID_POINTS,
    max_length_deviation: float = MAX_LAP_LENGTH_DEVIATION,
    max_start_line_offset: float = MAX_START_LINE_OFFSET,
    pace_cutoff: float | None = TELEMETRY_PACE_CUTOFF_DEFAULT,
    rotation: float = 0.0,
    partial_laps: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Distance-gridded telemetry for the fastest N *flying* laps per driver.

    When ``laps_per_driver`` is 0 (or negative), **all** valid flying laps are
    kept, enabling full lap-by-lap corner analysis across an entire race.

    Returns ``(telemetry, track_map)``: the compact per-lap channel data, and
    the session's circuit geometry stored once rather than per lap.

    Storing only the best laps per driver is what keeps the committed dataset
    small enough to ship in the repo. Qualifying gets several laps so a
    driver's own runs can be compared; a race stores every valid lap so any
    pair of laps can be compared corner-by-corner.

    With ``partial_laps`` set, the laps that do *not* cover the whole track
    are kept too - lap 1 from the grid, in-laps and out-laps - each anchored
    to the stretch of track it actually drove and NaN elsewhere. They are
    tagged in ``LapKind`` and bounded by ``CovStart``/``CovEnd`` so no caller
    can mistake them for a full lap. This runs as a second pass because
    trimming the pit lane off an in- or out-lap needs the circuit geometry,
    which is only known once the flying laps have been gridded.
    """
    laps = session.laps
    frames = []
    for drv in laps["Driver"].dropna().unique():
        drv_laps = laps.pick_drivers(drv)
        drv_laps = drv_laps[drv_laps["LapTime"].notna()]
        for col in ("PitInTime", "PitOutTime"):
            if col in drv_laps.columns:
                drv_laps = drv_laps[drv_laps[col].isna()]
        if "Deleted" in drv_laps.columns:
            # .eq(True) rather than .fillna(False).astype(bool): the column is
            # object dtype with NaNs, and fillna+astype is deprecated there.
            drv_laps = drv_laps[~drv_laps["Deleted"].eq(True)]
        if partial_laps:
            # Lap 1 starts on the grid, so it is always short and would be
            # gridded here only to be thrown out by the length check below.
            # The partial pass picks it up properly instead.
            drv_laps = drv_laps[drv_laps["LapNumber"] != 1]
        if drv_laps.empty:
            continue
        best = (drv_laps if laps_per_driver <= 0
                else drv_laps.nsmallest(laps_per_driver, "LapTime"))
        grid = _driver_laps_to_grid(best, n_points)
        if not grid.empty:
            frames.append(grid)

    if not frames:
        return pd.DataFrame(), pd.DataFrame()
    telemetry = pd.concat(frames, ignore_index=True)

    # Safety net for any remaining partial or corrupted lap. Real racing-line
    # variation is well under 1%; anything further out is a broken trace.
    #
    # Re-measured after each pass, because the first median is taken over a
    # population that still contains the outliers it is about to remove. That
    # is tolerable when a handful of laps are bad and not when 18% of them are
    # (2026/03_R): the contaminated median sits far enough off that a lap can
    # pass the guard and then fall outside the tolerance of the survivors,
    # which is exactly what validate_dataset.py re-checks and fails on. The
    # median is robust, so this settles in one or two passes; the cap is only
    # there to bound the loop.
    for _ in range(3):
        median_length = telemetry["LapLength"].median()
        bad = (telemetry["LapLength"] / median_length - 1.0).abs() > max_length_deviation
        if not bad.any():
            break
        dropped = telemetry.loc[bad, ["Driver", "LapNumber"]].drop_duplicates()
        log.warning("dropping %d lap(s) with anomalous length: %s",
                    len(dropped),
                    ", ".join(f"{r.Driver} L{r.LapNumber:.0f}"
                              for r in dropped.itertuples()))
        telemetry = telemetry[~bad].reset_index(drop=True)
        if telemetry.empty:
            break

    # Laps far off the session's best are cooldown or heavily compromised
    # laps. They are full laps (so they survive the length check) but carry
    # no comparative value in qualifying and would only bloat the dataset.
    # Races pass ``pace_cutoff=None`` - there a slow lap is data, not noise.
    if pace_cutoff is not None and telemetry["LapTime_s"].notna().any():
        best = telemetry["LapTime_s"].min()
        slow = telemetry["LapTime_s"] > best * pace_cutoff
        if slow.any():
            telemetry = telemetry[~slow].reset_index(drop=True)

    if telemetry.empty:
        log.warning("no lap survived the length and pace filters")
        return pd.DataFrame(), pd.DataFrame()

    # Circuit geometry, taken from the session's fastest lap and stored once.
    # It has to be a lap that carries X/Y: where the position feed ran short
    # the fastest lap may have been gridded from car data alone, and picking
    # it would leave the session with no track map and no pit-lane trimming.
    ref = _reference_lap(telemetry)
    track_map = extract_track_map(ref, rotation=rotation) if ref is not None else pd.DataFrame()

    if ref is not None:
        telemetry = _drop_misanchored_laps(telemetry, ref, max_start_line_offset)
        if telemetry.empty:
            log.warning("no lap survived the start-line alignment check")
            return pd.DataFrame(), pd.DataFrame()

    if partial_laps and ref is not None:
        telemetry = pd.concat(
            [telemetry, _extract_partial_laps(laps, ref, n_points=n_points)],
            ignore_index=True,
        )
    elif partial_laps:
        log.warning("no lap with position data; partial laps cannot be anchored")

    # Compact for storage; X/Y/Z now live in the track map instead.
    meta_cols = ["Driver", "LapNumber", "LapLength", "LapTime_s", "Compound",
                 "LapKind", "CovStart", "CovEnd"]
    encoded = pd.concat(
        [telemetry[meta_cols].reset_index(drop=True), encode_grid(telemetry)],
        axis=1,
    )
    encoded["Driver"] = encoded["Driver"].astype("category")
    encoded["Compound"] = encoded["Compound"].astype("category")
    encoded["LapKind"] = encoded["LapKind"].astype("category")
    encoded["LapNumber"] = encoded["LapNumber"].astype("int16")
    encoded["LapLength"] = encoded["LapLength"].astype("float32")
    encoded["LapTime_s"] = encoded["LapTime_s"].astype("float32")
    encoded["CovStart"] = encoded["CovStart"].astype("float32")
    encoded["CovEnd"] = encoded["CovEnd"].astype("float32")

    return encoded, track_map


def _extract_partial_laps(laps: pd.DataFrame, ref: pd.DataFrame,
                          *, n_points: int) -> pd.DataFrame:
    """Grid the laps that do not cover the whole track.

    ``ref`` is the session's gridded fastest lap, still carrying unrotated
    X/Y - the racing line that :func:`transforms.trim_to_track` measures pit
    lane against. The rotated copy in the stored track map would not line up
    with raw telemetry.
    """
    track_length = float(ref["LapLength"].iloc[0])
    track_xy = ref[["X", "Y"]].to_numpy(dtype="float64") if {"X", "Y"}.issubset(ref.columns) else None

    is_in = laps["PitInTime"].notna() if "PitInTime" in laps.columns else pd.Series(False, index=laps.index)
    is_out = laps["PitOutTime"].notna() if "PitOutTime" in laps.columns else pd.Series(False, index=laps.index)
    is_first = laps["LapNumber"] == 1

    # Lap 1 is classified first: it is an out-lap in FastF1's bookkeeping
    # (the car leaves the grid, not the pits) but geometrically it is a clean
    # run from the grid box to the line with no pit lane on it at all.
    selections = {
        LAP_KIND_START: laps[is_first],
        LAP_KIND_IN: laps[is_in & ~is_first],
        LAP_KIND_OUT: laps[is_out & ~is_in & ~is_first],
    }

    frames = []
    for kind, subset in selections.items():
        if subset.empty:
            continue
        grid = _driver_laps_to_grid(
            subset, n_points, kind=kind,
            track_length=track_length, track_xy=track_xy,
        )
        if not grid.empty:
            n = grid.groupby(["Driver", "LapNumber"], observed=True).ngroups
            mean_cov = grid["CovEnd"].sub(grid["CovStart"]).mean() * 100
            log.info("  partial: %-5s %3d lap(s), mean coverage %.1f%%",
                     kind, n, mean_cov)
            frames.append(grid)

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def session_metadata(session, key: SessionKey) -> dict:
    """One manifest row describing an extracted session."""
    event = session.event
    laps = session.laps
    total_laps = int(laps["LapNumber"].max()) if len(laps) else 0
    return {
        "year": key.year,
        "round": key.round,
        "session": key.session,
        "slug": key.slug,
        "event_name": str(event.get("EventName", "")),
        "location": str(event.get("Location", "")),
        "country": str(event.get("Country", "")),
        "event_date": pd.to_datetime(event.get("EventDate", pd.NaT)),
        "n_drivers": int(laps["Driver"].nunique()) if len(laps) else 0,
        "n_laps": int(len(laps)),
        "total_laps": total_laps,
        # Only sessions built with messages=True can have this at all, so the
        # column's presence says the Deleted flags are real and its value says
        # how many there were. Without it, a session with no deletions and one
        # that was never asked look identical.
        "n_deleted_laps": (int(laps["Deleted"].eq(True).sum())
                           if len(laps) and "Deleted" in laps.columns else 0),
    }


def available_rounds(year: int) -> Iterable[int]:
    """Round numbers for a season that have already happened."""
    sched = get_schedule(year)
    now = pd.Timestamp.utcnow().tz_localize(None)
    past = sched[pd.to_datetime(sched["EventDate"]) <= now]
    return [int(r) for r in past["RoundNumber"].tolist()]
