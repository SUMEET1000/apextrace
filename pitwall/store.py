"""Parquet persistence and the session manifest.

The app reads exclusively through this module, and it caches nothing - the
API layer wraps these functions in ``api/cache.py`` with the bounds each one
needs, which keeps this importable from tests and notebooks with no cache
semantics attached.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pitwall.config import GRID_POINTS, MANIFEST_PATH, PROCESSED_DIR
from pitwall.ingest import SessionKey
from pitwall.transforms import decode_grid

# The artefacts written per session. "trackmap" holds circuit geometry once
# per session rather than repeating X/Y on every stored lap.
ARTEFACTS = ("laps", "telemetry", "trackmap", "corners", "weather", "results")


def session_dir(key: SessionKey):
    return PROCESSED_DIR / str(key.year) / f"{key.round:02d}_{key.session}"


def artefact_path(key: SessionKey, name: str):
    return session_dir(key) / f"{name}.parquet"


def write_artefact(key: SessionKey, name: str, df: pd.DataFrame) -> None:
    """Write one artefact, creating the session directory as needed."""
    if name not in ARTEFACTS:
        raise ValueError(f"unknown artefact {name!r}, expected one of {ARTEFACTS}")
    path = artefact_path(key, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False, compression="zstd")


def read_artefact(key: SessionKey, name: str) -> pd.DataFrame:
    path = artefact_path(key, name)
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def read_telemetry(key: SessionKey, n_points: int = GRID_POINTS) -> pd.DataFrame:
    """Stored telemetry, decoded back into physical units.

    Callers should use this rather than ``read_artefact(key, "telemetry")``,
    which returns the compact on-disk encoding.
    """
    raw = read_artefact(key, "telemetry")
    if raw.empty:
        return raw
    return decode_grid(raw, n_points=n_points)


_TIMEDELTA_COLUMNS = (
    "LapTime", "Sector1Time", "Sector2Time", "Sector3Time",
    "PitInTime", "PitOutTime", "LapStartTime",
)

# Nothing in a session lasts a day. Anything beyond this is corruption, not
# a duration.
_MAX_DURATION_S = 86_400


def read_laps(key: SessionKey) -> pd.DataFrame:
    """Lap table with timedelta columns restored.

    Parquet round-trips timedeltas poorly across engines, so the ETL flattens
    them to float seconds. Restoring them here means the analysis modules see
    one schema - the same one FastF1 produces - instead of every model having
    to handle both.
    """
    laps = read_artefact(key, "laps")
    if laps.empty:
        return laps
    out = laps.copy()
    for col in _TIMEDELTA_COLUMNS:
        seconds = f"{col}_s"
        if seconds in out.columns:
            # Guard the conversion: a non-finite or absurd value would either
            # overflow the nanosecond representation or, worse, silently
            # become a plausible-looking duration.
            values = pd.to_numeric(out[seconds], errors="coerce")
            values = values.where(np.isfinite(values) & (values.abs() < _MAX_DURATION_S))
            out[col] = pd.to_timedelta(values, unit="s")
    if "LapNumber" in out.columns:
        out["LapNumber"] = out["LapNumber"].astype(float)
    return out


def get_lap(telemetry: pd.DataFrame, driver: str,
            lap_number: float | None = None) -> pd.DataFrame:
    """One driver's lap from a decoded telemetry frame.

    Defaults to that driver's fastest stored lap, which is what nearly every
    comparison wants.
    """
    drv = telemetry[telemetry["Driver"] == driver]
    if drv.empty:
        return drv
    if lap_number is None:
        timed = drv["LapTime_s"].dropna()
        if timed.empty:
            # Every stored lap for this driver is untimed. A retirement does
            # this: VER's only stored lap in Monaco 2026/06_R is lap 1, a
            # ``start`` kind with no LapTime. ``idxmin`` on an all-NaN series
            # returns NaN, and the ``.loc`` lookup then raised ``KeyError: nan``
            # rather than returning the lap the driver demonstrably has.
            #
            # Fall back to the lowest lap number: deterministic, and a real lap.
            # Picking a default is allowed here precisely because the caller
            # states which lap it landed on - the same contract the fastest-lap
            # default already relies on.
            lap_number = drv["LapNumber"].min()
        else:
            lap_number = drv.loc[timed.idxmin(), "LapNumber"]
    return drv[drv["LapNumber"] == lap_number].reset_index(drop=True)


def session_is_complete(key: SessionKey) -> bool:
    """True if every artefact exists - used to make the ETL resumable.

    ``weather`` is excluded from the requirement because some older sessions
    genuinely have no weather feed, and demanding it would make those sessions
    rebuild forever.
    """
    required = [a for a in ARTEFACTS if a != "weather"]
    return all(artefact_path(key, a).exists() for a in required)


# --------------------------------------------------------------------------
# Manifest
# --------------------------------------------------------------------------

def read_manifest() -> pd.DataFrame:
    if not MANIFEST_PATH.exists():
        return pd.DataFrame()
    return pd.read_parquet(MANIFEST_PATH)


def upsert_manifest(row: dict) -> pd.DataFrame:
    """Insert or replace one session's manifest row, keyed by slug."""
    manifest = read_manifest()
    new = pd.DataFrame([row])
    if manifest.empty:
        merged = new
    else:
        manifest = manifest[manifest["slug"] != row["slug"]]
        merged = pd.concat([manifest, new], ignore_index=True)
    merged = merged.sort_values(["year", "round", "session"]).reset_index(drop=True)
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(MANIFEST_PATH, index=False, compression="zstd")
    return merged


def key_from_slug(slug: str) -> SessionKey:
    """``"2026/10_Q"`` -> SessionKey(2026, 10, "Q")."""
    year_part, rest = slug.split("/")
    round_part, session_part = rest.split("_")
    return SessionKey(int(year_part), int(round_part), session_part)


def load_session_bundle(key: SessionKey) -> dict[str, pd.DataFrame]:
    """All artefacts for a session, keyed by artefact name."""
    return {name: read_artefact(key, name) for name in ARTEFACTS}
