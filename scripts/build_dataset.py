"""ETL: pull sessions from the F1 API and write the curated Parquet dataset.

    python scripts/build_dataset.py --years 2026 --rounds 10 --sessions Q
    python scripts/build_dataset.py --years 2024 2025 2026 --sessions Q R

Resumable by design: sessions that already have a complete set of artefacts
are skipped unless --force is given, so an interrupted backfill can simply be
re-run.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pitwall import ingest, store  # noqa: E402
from pitwall.config import GRID_POINTS  # noqa: E402
from pitwall.ingest import SessionKey  # noqa: E402

# Qualifying keeps several laps per driver so a driver's own runs can be
# compared; a race keeps one, because race analysis works off the lap table.
LAPS_PER_DRIVER = {"Q": 3, "R": 1}

log = logging.getLogger("build_dataset")


def build_session(key: SessionKey, *, force: bool, n_points: int) -> str:
    """Extract and persist one session. Returns a short status string."""
    if not force and store.session_is_complete(key):
        return "skipped (already built)"

    session = ingest.load_session(key, telemetry=True)

    laps = ingest.extract_laps(session)
    if laps.empty:
        return "skipped (no lap data)"

    corners = ingest.extract_corners(session)
    weather = ingest.extract_weather(session)
    results = ingest.extract_results(session)
    rotation = float(corners["Rotation"].iloc[0]) if not corners.empty else 0.0
    telemetry, track_map = ingest.extract_telemetry(
        session,
        laps_per_driver=LAPS_PER_DRIVER.get(key.session, 1),
        n_points=n_points,
        rotation=rotation,
    )

    store.write_artefact(key, "laps", laps)
    store.write_artefact(key, "corners", corners)
    store.write_artefact(key, "results", results)
    store.write_artefact(key, "telemetry", telemetry)
    store.write_artefact(key, "trackmap", track_map)
    if not weather.empty:
        store.write_artefact(key, "weather", weather)

    meta = ingest.session_metadata(session, key)
    meta["n_corners"] = int(len(corners))
    meta["n_telemetry_rows"] = int(len(telemetry))
    meta["grid_points"] = n_points
    store.upsert_manifest(meta)

    return (f"ok - {len(laps)} laps, {len(corners)} corners, "
            f"{len(telemetry):,} telemetry rows")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--years", type=int, nargs="+", required=True)
    parser.add_argument("--rounds", type=int, nargs="+", default=None,
                        help="specific round numbers; default is every round held so far")
    parser.add_argument("--sessions", nargs="+", default=["Q", "R"],
                        choices=["Q", "R", "FP1", "FP2", "FP3", "Sprint"])
    parser.add_argument("--force", action="store_true",
                        help="rebuild sessions that are already complete")
    parser.add_argument("--grid-points", type=int, default=GRID_POINTS)
    parser.add_argument("--pause", type=float, default=1.0,
                        help="seconds between sessions, to stay under rate limits")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    # FastF1 is chatty at INFO during loads; keep our own log readable.
    logging.getLogger("fastf1").setLevel(logging.WARNING)

    targets: list[SessionKey] = []
    for year in args.years:
        rounds = args.rounds
        if rounds is None:
            try:
                rounds = list(ingest.available_rounds(year))
            except Exception as exc:  # noqa: BLE001
                log.error("could not fetch schedule for %s: %s", year, exc)
                continue
        for rnd in rounds:
            for sess in args.sessions:
                targets.append(SessionKey(year, rnd, sess))

    log.info("building %d session(s) at %d grid points",
             len(targets), args.grid_points)

    ok = failed = skipped = 0
    started = time.time()
    for i, key in enumerate(targets, 1):
        prefix = f"[{i}/{len(targets)}] {key}"
        try:
            status = build_session(key, force=args.force, n_points=args.grid_points)
            if status.startswith("skipped"):
                skipped += 1
            else:
                ok += 1
            log.info("%s  %s", prefix, status)
        except Exception as exc:  # noqa: BLE001 - one bad session must not stop a backfill
            failed += 1
            log.error("%s  FAILED: %s", prefix, exc)
        if args.pause:
            time.sleep(args.pause)

    elapsed = time.time() - started
    log.info("done in %.1fs - %d built, %d skipped, %d failed",
             elapsed, ok, skipped, failed)

    manifest = store.read_manifest()
    if not manifest.empty:
        log.info("manifest now holds %d session(s)", len(manifest))
    return 1 if failed and not ok else 0


if __name__ == "__main__":
    raise SystemExit(main())
