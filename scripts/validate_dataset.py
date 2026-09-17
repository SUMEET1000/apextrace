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
from pitwall.corners import corner_data_issues  # noqa: E402
from pitwall.transforms import telemetry_coverage  # noqa: E402

from pitwall.config import (  # noqa: E402
    GRID_POINTS,
    LAP_KIND_FLYING,
    LAPS_PER_DRIVER,
    LAPS_PER_DRIVER_DEFAULT,
    MAX_LAP_LENGTH_DEVIATION,
    MIN_TELEMETRY_COVERAGE,
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

        # Partial laps (lap 1, in-laps, out-laps) are NaN outside the stretch
        # of track they drove; that is the point of them. Only the covered
        # span is checked, and a NaN *inside* it is still a real fault.
        if {"CovStart", "CovEnd"}.issubset(telemetry.columns):
            rel = telemetry["RelDistance"]
            covered = ((rel >= telemetry["CovStart"] - 1e-9)
                       & (rel <= telemetry["CovEnd"] + 1e-9))
        else:
            covered = pd.Series(True, index=telemetry.index)

        inside = telemetry[covered]
        for column in ("Speed", "Distance", "t"):
            if inside[column].isna().any():
                fail(f"NaN inside the covered span of telemetry column {column!r}")

        speed = inside["Speed"]
        if speed.min() < 0 or speed.max() > 400:
            fail(f"implausible speeds: {speed.min():.0f}–{speed.max():.0f} km/h")

        full_only = telemetry
        if "LapKind" in telemetry.columns:
            full_only = telemetry[telemetry["LapKind"].astype(str) == LAP_KIND_FLYING]

        # Flying laps only, against the flying-lap median - the same basis the
        # ETL guard uses. A partial lap does not measure the track (it is
        # assigned the reference lap's length by construction), so including
        # them here only pulls the median off the population being judged and
        # fails laps the ETL correctly kept.
        if not full_only.empty:
            lengths = full_only.groupby(["Driver", "LapNumber"],
                                        observed=True)["LapLength"].first()
            over = (lengths / lengths.median() - 1).abs() > MAX_LAP_LENGTH_DEVIATION
            if over.any():
                fail(f"{int(over.sum())} lap(s) outside the length tolerance")

        # Telemetry duration must agree with the timing feed - but only for
        # full laps. On a partial lap the two measure different things: the
        # timing feed reports the whole lap (an in-lap's time includes the
        # crawl down the pit lane) while ``t`` spans just the stretch of track
        # that was kept, so a pit stop's worth of difference is correct.
        if not full_only.empty:
            merged = (full_only.groupby(["Driver", "LapNumber"], observed=True)
                               .agg(tel_s=("t", "max"), stored_s=("LapTime_s", "first")))
            error = (merged["tel_s"] - merged["stored_s"]).abs()
            if error.max() > 1.0:
                warn(f"telemetry vs timing mismatch up to {error.max():.3f} s")

        # A session type that asked for every lap and got a fraction of them
        # is the failure this check exists for: nothing else here notices,
        # because each stored lap is individually well-formed. Qualifying is
        # exempt - storing only the fastest few is the stated intent there.
        if LAPS_PER_DRIVER.get(key.session, LAPS_PER_DRIVER_DEFAULT) == 0:
            summary, reasons = telemetry_coverage(laps, telemetry,
                                                  stores_all_laps=True)
            if summary["coverage"] < MIN_TELEMETRY_COVERAGE:
                top = "; ".join(f"{r.reason}: {r.count}"
                                for r in reasons.head(3).itertuples())
                warn(f"only {summary['n_stored']}/{summary['n_laps']} laps have "
                     f"telemetry ({summary['coverage']:.1%}) - {top}")

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
        # Same rule the API gates on, from one definition, so a session cannot
        # pass here and then be refused by the app. The bare monotonic check
        # this replaces missed 2025/20_FP1, where all 17 corners sit at 0.0 m:
        # an all-equal series is monotonic, so nothing fired.
        for issue in corner_data_issues(corners):
            warn(f"corner analysis unavailable - {issue}")

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
