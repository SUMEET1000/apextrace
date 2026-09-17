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
from concurrent.futures import CancelledError, ProcessPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pitwall import ingest, store, transforms  # noqa: E402
from pitwall.config import (  # noqa: E402
    GRID_POINTS,
    LAPS_PER_DRIVER,
    LAPS_PER_DRIVER_DEFAULT,
    MIN_TELEMETRY_COVERAGE,
    STORE_PARTIAL_LAPS,
    STORE_PARTIAL_LAPS_DEFAULT,
    TELEMETRY_PACE_CUTOFF,
    TELEMETRY_PACE_CUTOFF_DEFAULT,
)
from pitwall.ingest import SessionKey  # noqa: E402

log = logging.getLogger("build_dataset")


def build_session(key: SessionKey, *, force: bool, n_points: int,
                  laps_per_driver: int | None = None) -> tuple[str, dict | None]:
    """Extract and persist one session's artefacts.

    Returns ``(status, manifest_row)``. The manifest row is handed back to the
    caller rather than written here because ``store.upsert_manifest`` is a
    read-modify-write of a single Parquet file: with ``--jobs`` above 1,
    concurrent writers would silently drop each other's rows, and a lost row
    removes a session from the app's picker. The parent process owns that
    write, so it stays serialised no matter how many workers are running.
    """
    if not force and store.session_is_complete(key):
        return "skipped (already built)", None

    session = ingest.load_session(key, telemetry=True)

    laps = ingest.extract_laps(session)
    if laps.empty:
        return "skipped (no lap data)", None

    corners = ingest.extract_corners(session)
    weather = ingest.extract_weather(session)
    results = ingest.extract_results(session)
    rotation = float(corners["Rotation"].iloc[0]) if not corners.empty else 0.0
    # An explicit --laps-per-driver wins; otherwise the per-session default.
    n_laps = (laps_per_driver if laps_per_driver is not None
              else LAPS_PER_DRIVER.get(key.session, LAPS_PER_DRIVER_DEFAULT))
    cutoff = TELEMETRY_PACE_CUTOFF.get(key.session, TELEMETRY_PACE_CUTOFF_DEFAULT)
    partial = STORE_PARTIAL_LAPS.get(key.session, STORE_PARTIAL_LAPS_DEFAULT)
    telemetry, track_map = ingest.extract_telemetry(
        session,
        laps_per_driver=n_laps,
        n_points=n_points,
        pace_cutoff=cutoff,
        rotation=rotation,
        partial_laps=partial,
    )

    # Corner markers arrive from FastF1 already snapped onto whichever lap it
    # picked as fastest, on that lap's speed-integral distance axis. Re-anchor
    # them onto the track map instead: one validated lap, and the same axis
    # the stored telemetry grid uses. See transforms.align_corner_distances.
    corners = transforms.align_corner_distances(corners, track_map, rotation)

    store.write_artefact(key, "laps", laps)
    store.write_artefact(key, "corners", corners)
    store.write_artefact(key, "results", results)
    store.write_artefact(key, "telemetry", telemetry)
    store.write_artefact(key, "trackmap", track_map)
    if not weather.empty:
        store.write_artefact(key, "weather", weather)

    # How many of the session's laps actually got a trace. Reporting rows
    # alone hid a race that stored 93 laps of 1258 behind a cheerful "ok".
    coverage, _ = transforms.telemetry_coverage(
        laps, telemetry, stores_all_laps=n_laps == 0,
    )
    meta = ingest.session_metadata(session, key)
    meta["n_corners"] = int(len(corners))
    meta["n_telemetry_rows"] = int(len(telemetry))
    meta["n_telemetry_laps"] = int(coverage["n_stored"])
    meta["telemetry_coverage"] = float(coverage["coverage"])
    meta["grid_points"] = n_points

    short = (n_laps == 0 and coverage["coverage"] < MIN_TELEMETRY_COVERAGE)
    return (f"{'ok' if not short else 'ok (LOW COVERAGE)'} - {len(laps)} laps, "
            f"{len(corners)} corners, {coverage['n_stored']}/{coverage['n_laps']} "
            f"laps with telemetry ({coverage['coverage']:.1%})", meta)


def _record(status: str, meta: dict | None) -> None:
    """Persist the manifest row for a freshly built session.

    Always called on the parent process - see :func:`build_session`.
    """
    if meta is not None and not status.startswith("skipped"):
        store.upsert_manifest(meta)


def _run_sequential(targets: list[SessionKey], args) -> tuple[int, int, int]:
    """Build one session at a time. Returns ``(ok, skipped, failed)``."""
    ok = failed = skipped = 0
    for i, key in enumerate(targets, 1):
        prefix = f"[{i}/{len(targets)}] {key}"
        try:
            status, meta = build_session(key, force=args.force,
                                         n_points=args.grid_points,
                                         laps_per_driver=args.laps_per_driver)
            _record(status, meta)
            if status.startswith("skipped"):
                skipped += 1
            else:
                ok += 1
            log.info("%s  %s", prefix, status)
        except ingest.RateLimited as exc:
            # No point continuing: the budget is hourly, so every remaining
            # session would fail too. Stop cleanly and tell the user how to
            # resume - the dataset is built to be restartable.
            log.warning("%s  %s", prefix, exc)
            log.info("stopping early with %d session(s) built this run", ok)
            break
        except Exception as exc:  # noqa: BLE001 - one bad session must not stop a backfill
            failed += 1
            log.error("%s  FAILED: %s", prefix, exc)
        if args.pause:
            time.sleep(args.pause)
    return ok, skipped, failed


def _run_parallel(targets: list[SessionKey], args) -> tuple[int, int, int]:
    """Build several sessions at once, writing the manifest from here only.

    Worker processes return their manifest row instead of writing it, so the
    serialised ``_record`` call below is the single writer. Progress is logged
    in completion order rather than target order - with uneven session sizes
    the two do not match, and pretending otherwise would misreport which
    session a message belongs to.
    """
    ok = failed = skipped = 0
    done = 0
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        futures = {
            pool.submit(build_session, key, force=args.force,
                        n_points=args.grid_points,
                        laps_per_driver=args.laps_per_driver): key
            for key in targets
        }
        for fut in as_completed(futures):
            key = futures[fut]
            done += 1
            prefix = f"[{done}/{len(targets)}] {key}"
            try:
                status, meta = fut.result()
                _record(status, meta)
                if status.startswith("skipped"):
                    skipped += 1
                else:
                    ok += 1
                log.info("%s  %s", prefix, status)
            except ingest.RateLimited as exc:
                # Same reasoning as the sequential path, but the in-flight
                # workers cannot be recalled - cancel everything not yet
                # started and let the running ones finish.
                log.warning("%s  %s", prefix, exc)
                for pending in futures:
                    pending.cancel()
                log.info("stopping early with %d session(s) built this run", ok)
                break
            except CancelledError:
                skipped += 1
            except Exception as exc:  # noqa: BLE001 - one bad session must not stop a backfill
                failed += 1
                log.error("%s  FAILED: %s", prefix, exc)
    return ok, skipped, failed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--years", type=int, nargs="+", required=True)
    parser.add_argument("--rounds", type=int, nargs="+", default=None,
                        help="specific round numbers; default is every round held so far")
    parser.add_argument("--sessions", nargs="+", default=["Q", "R"],
                        choices=["Q", "R", "SQ", "FP1", "FP2", "FP3", "Sprint"])
    parser.add_argument("--force", action="store_true",
                        help="rebuild sessions that are already complete")
    parser.add_argument("--grid-points", type=int, default=GRID_POINTS)
    parser.add_argument("--laps-per-driver", type=int, default=None,
                        help="telemetry laps kept per driver; overrides the "
                             f"per-session default {LAPS_PER_DRIVER}. More laps "
                             "means a real lap-to-lap corner comparison, at a "
                             "roughly linear cost in stored size")
    parser.add_argument("--pause", type=float, default=1.0,
                        help="seconds between sessions, to stay under rate limits")
    parser.add_argument("--jobs", "-j", type=int, default=1,
                        help="build this many sessions in parallel. Only worth "
                             "using when the FastF1 cache is already warm, where "
                             "the work is CPU-bound resampling rather than "
                             "network: a cold cache would turn parallel jobs "
                             "into parallel downloads and burn the hourly API "
                             "budget faster. Each worker holds a whole session's "
                             "telemetry in memory (~1-2 GB for a race), so this "
                             "is bounded by RAM, not by core count")
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

    started = time.time()
    runner = _run_parallel if args.jobs > 1 else _run_sequential
    ok, skipped, failed = runner(targets, args)

    elapsed = time.time() - started
    log.info("done in %.1fs - %d built, %d skipped, %d failed",
             elapsed, ok, skipped, failed)

    manifest = store.read_manifest()
    if not manifest.empty:
        log.info("manifest now holds %d session(s)", len(manifest))
    return 1 if failed and not ok else 0


if __name__ == "__main__":
    raise SystemExit(main())
