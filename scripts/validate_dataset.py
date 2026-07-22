"""Integrity checks over the curated Parquet dataset.

    python scripts/validate_dataset.py
    python scripts/validate_dataset.py --strict   # non-zero exit on any warning

Run after a build. Catches the failure modes that are invisible until an
analysis silently produces nonsense: a missing artefact, a lap gridded to the
wrong length, telemetry that disagrees with the timing feed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from pitwall import store  # noqa: E402

from pitwall.config import (  # noqa: E402
    GRID_POINTS,
    MAX_LAP_LENGTH_DEVIATION,
    PROCESSED_DIR,
)

REQUIRED_ARTEFACTS = ("laps", "telemetry", "trackmap", "corners", "results")


def check_session(slug: str, meta: pd.Series) -> list[tuple[str, str]]:
    """Return a list of (level, message) problems for one session."""
    problems: list[tuple[str, str]] = []
    key = store.key_from_slug(slug)

    def fail(msg: str) -> None:
        problems.append(("FAIL", msg))

    def warn(msg: str) -> None:
        problems.append(("WARN", msg))

    for artefact in REQUIRED_ARTEFACTS:
        if not store.artefact_path(key, artefact).exists():
            fail(f"missing {artefact}.parquet")
    if problems:
        return problems

    laps = store.read_laps(key)
    telemetry = store.read_telemetry(key)
    corners = store.read_artefact(key, "corners")
    track = store.read_artefact(key, "trackmap")

    if laps.empty:
        fail("laps table is empty")
        return problems

    # --- telemetry grid ---------------------------------------------------
    if telemetry.empty:
        warn("no telemetry stored")
    else:
        sizes = telemetry.groupby(["Driver", "LapNumber"], observed=True).size()
        if set(sizes.unique()) != {GRID_POINTS}:
            fail(f"laps not all on the {GRID_POINTS}-point grid: "
                 f"found sizes {sorted(set(sizes.unique()))}")

        for column in ("Speed", "Distance", "t"):
            if telemetry[column].isna().any():
                fail(f"NaN present in telemetry column {column!r}")

        speed = telemetry["Speed"]
        if speed.min() < 0 or speed.max() > 400:
            fail(f"implausible speeds: {speed.min():.0f}–{speed.max():.0f} km/h")

        lengths = telemetry.groupby(["Driver", "LapNumber"], observed=True)["LapLength"].first()
        deviation = (lengths / lengths.median() - 1).abs()
        if (deviation > MAX_LAP_LENGTH_DEVIATION).any():
            fail(f"{int((deviation > MAX_LAP_LENGTH_DEVIATION).sum())} lap(s) "
                 f"outside the length tolerance")

        # Telemetry duration must agree with the timing feed.
        merged = (telemetry.groupby(["Driver", "LapNumber"], observed=True)
                           .agg(tel_s=("t", "max"), stored_s=("LapTime_s", "first")))
        error = (merged["tel_s"] - merged["stored_s"]).abs()
        if error.max() > 1.0:
            warn(f"telemetry vs timing mismatch up to {error.max():.3f} s")

    # --- track map --------------------------------------------------------
    if track.empty:
        warn("no track map")
    elif len(track) != GRID_POINTS:
        fail(f"track map has {len(track)} points, expected {GRID_POINTS}")

    # --- corners ----------------------------------------------------------
    if corners.empty:
        warn("no corner data (corner analysis unavailable)")
    else:
        if not (3 <= len(corners) <= 30):
            warn(f"{len(corners)} corners is outside the usual range")
        if corners["Distance"].isna().any():
            fail("corner Distance has NaNs - corner segmentation would break")
        if not corners["Distance"].is_monotonic_increasing:
            warn("corner distances are not sorted")

    # --- laps -------------------------------------------------------------
    if laps["LapTime_s"].dropna().empty:
        fail("no lap times at all")
    else:
        times = laps["LapTime_s"].dropna()
        if times.min() < 30:
            warn(f"implausibly short lap time {times.min():.1f} s")

    expected_drivers = int(meta.get("n_drivers", 0))
    if expected_drivers and laps["Driver"].nunique() != expected_drivers:
        warn(f"{laps['Driver'].nunique()} drivers in laps, "
             f"manifest says {expected_drivers}")

    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true",
                        help="exit non-zero on warnings as well as failures")
    args = parser.parse_args()

    manifest = store.read_manifest()
    if manifest.empty:
        print("No manifest found. Run scripts/build_dataset.py first.")
        return 1

    total_fail = total_warn = 0
    print(f"Validating {len(manifest)} session(s)\n")

    for row in manifest.itertuples():
        problems = check_session(row.slug, manifest[manifest["slug"] == row.slug].iloc[0])
        fails = [m for level, m in problems if level == "FAIL"]
        warns = [m for level, m in problems if level == "WARN"]
        total_fail += len(fails)
        total_warn += len(warns)
        if fails or warns:
            print(f"  {row.slug}  {row.event_name}")
            for m in fails:
                print(f"      FAIL  {m}")
            for m in warns:
                print(f"      warn  {m}")

    size_mb = sum(p.stat().st_size for p in
                  PROCESSED_DIR.rglob("*.parquet")) / 1024 ** 2

    print(f"\n{len(manifest)} sessions · {size_mb:.1f} MB on disk")
    print(f"{total_fail} failure(s), {total_warn} warning(s)")

    if total_fail:
        return 1
    return 1 if (args.strict and total_warn) else 0


if __name__ == "__main__":
    raise SystemExit(main())
