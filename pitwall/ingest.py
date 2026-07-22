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
    GRID_POINTS,
    MAX_LAP_LENGTH_DEVIATION,
    TELEMETRY_PACE_CUTOFF,
)
from pitwall.transforms import (
    encode_grid,
    extract_track_map,
    resample_to_distance_grid,
)

log = logging.getLogger(__name__)

_cache_enabled = False


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


def load_session(
    key: SessionKey,
    *,
    telemetry: bool = True,
    retries: int = 3,
    backoff_s: float = 20.0,
):
    """Load a FastF1 session, retrying through rate limits.

    The F1 API rate-limits aggressively during a bulk backfill, and a failure
    partway through a 140-session run is expensive, so back off and retry
    rather than aborting.
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
                messages=False,
            )
            return session
        except fastf1.RateLimitExceededError as exc:
            last_exc = exc
            wait = backoff_s * attempt
            log.warning("rate limited on %s, waiting %.0fs (attempt %d/%d)",
                        key, wait, attempt, retries)
            time.sleep(wait)
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


def extract_corners(session) -> pd.DataFrame:
    """Corner marker positions from the circuit map.

    ``Distance`` (metres of each apex from the start/finish line) is the
    linchpin of the whole corner-analysis feature - it is what lets telemetry
    be sliced into named corners.
    """
    try:
        info = session.get_circuit_info()
    except Exception as exc:  # noqa: BLE001 - circuit info is optional
        log.warning("no circuit info available: %s", exc)
        return pd.DataFrame()
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
                         n_points: int) -> pd.DataFrame:
    """Resample a set of laps onto the distance grid and stack them."""
    frames = []
    for _, lap in laps_subset.iterrows():
        try:
            tel = lap.get_telemetry()
        except Exception as exc:  # noqa: BLE001 - a lap may lack telemetry
            log.debug("no telemetry for %s lap %s: %s",
                      lap.get("Driver"), lap.get("LapNumber"), exc)
            continue
        if tel is None or len(tel) < 2:
            continue
        try:
            grid = resample_to_distance_grid(tel, n_points=n_points)
        except ValueError as exc:
            log.debug("resample failed for %s lap %s: %s",
                      lap.get("Driver"), lap.get("LapNumber"), exc)
            continue

        grid.insert(0, "Driver", str(lap["Driver"]))
        grid.insert(1, "LapNumber", float(lap["LapNumber"]))
        lap_time = lap.get("LapTime")
        grid["LapTime_s"] = (
            lap_time.total_seconds() if pd.notna(lap_time) else np.nan
        )
        grid["Compound"] = str(lap.get("Compound", "UNKNOWN"))
        frames.append(grid)

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def extract_telemetry(
    session,
    *,
    laps_per_driver: int,
    n_points: int = GRID_POINTS,
    max_length_deviation: float = MAX_LAP_LENGTH_DEVIATION,
    pace_cutoff: float | None = TELEMETRY_PACE_CUTOFF,
    rotation: float = 0.0,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Distance-gridded telemetry for the fastest N *flying* laps per driver.

    Returns ``(telemetry, track_map)``: the compact per-lap channel data, and
    the session's circuit geometry stored once rather than per lap.

    Storing only the best laps per driver is what keeps the committed dataset
    small enough to ship in the repo. Qualifying gets several laps so a
    driver's own runs can be compared; a race gets one, because race analysis
    needs the *lap table*, not full traces for 1200 laps.

    In- and out-laps are excluded before ranking. They are not flying laps,
    and an in-lap ends in the pit lane so it covers noticeably less distance
    than a full circuit of the track - gridding one onto [0, 1] would stretch
    a partial lap across the whole track and corrupt every comparison made
    against it.
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
        if drv_laps.empty:
            continue
        best = drv_laps.nsmallest(laps_per_driver, "LapTime")
        grid = _driver_laps_to_grid(best, n_points)
        if not grid.empty:
            frames.append(grid)

    if not frames:
        return pd.DataFrame(), pd.DataFrame()
    telemetry = pd.concat(frames, ignore_index=True)

    # Safety net for any remaining partial or corrupted lap. Real racing-line
    # variation is well under 1%; anything further out is a broken trace.
    median_length = telemetry["LapLength"].median()
    deviation = (telemetry["LapLength"] / median_length - 1.0).abs()
    bad = deviation > max_length_deviation
    if bad.any():
        dropped = telemetry.loc[bad, ["Driver", "LapNumber"]].drop_duplicates()
        log.warning("dropping %d lap(s) with anomalous length: %s",
                    len(dropped),
                    ", ".join(f"{r.Driver} L{r.LapNumber:.0f}"
                              for r in dropped.itertuples()))
        telemetry = telemetry[~bad].reset_index(drop=True)

    # Laps far off the session's best are cooldown or heavily compromised
    # laps. They are full laps (so they survive the length check) but carry
    # no comparative value and would only bloat the shipped dataset.
    if pace_cutoff is not None and telemetry["LapTime_s"].notna().any():
        best = telemetry["LapTime_s"].min()
        slow = telemetry["LapTime_s"] > best * pace_cutoff
        if slow.any():
            telemetry = telemetry[~slow].reset_index(drop=True)

    # Circuit geometry, taken from the session's fastest lap and stored once.
    fastest_key = telemetry.loc[telemetry["LapTime_s"].idxmin(), ["Driver", "LapNumber"]]
    ref = telemetry[
        (telemetry["Driver"] == fastest_key["Driver"])
        & (telemetry["LapNumber"] == fastest_key["LapNumber"])
    ]
    track_map = extract_track_map(ref, rotation=rotation)

    # Compact for storage; X/Y/Z now live in the track map instead.
    meta_cols = ["Driver", "LapNumber", "LapLength", "LapTime_s", "Compound"]
    encoded = pd.concat(
        [telemetry[meta_cols].reset_index(drop=True), encode_grid(telemetry)],
        axis=1,
    )
    encoded["Driver"] = encoded["Driver"].astype("category")
    encoded["Compound"] = encoded["Compound"].astype("category")
    encoded["LapNumber"] = encoded["LapNumber"].astype("int16")
    encoded["LapLength"] = encoded["LapLength"].astype("float32")
    encoded["LapTime_s"] = encoded["LapTime_s"].astype("float32")

    return encoded, track_map


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
    }


def available_rounds(year: int) -> Iterable[int]:
    """Round numbers for a season that have already happened."""
    sched = get_schedule(year)
    now = pd.Timestamp.utcnow().tz_localize(None)
    past = sched[pd.to_datetime(sched["EventDate"]) <= now]
    return [int(r) for r in past["RoundNumber"].tolist()]
