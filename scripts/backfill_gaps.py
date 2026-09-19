"""Fill every gap between the official F1 schedule and the built dataset.

    python scripts/backfill_gaps.py --dry-run
    python scripts/backfill_gaps.py --jobs 3

Works out for itself which sessions are missing - it reads the schedule for
each season, expands every event into the sessions its format actually had
(a sprint weekend has no FP2/FP3, it has SQ and Sprint), drops anything that
has not happened yet, and subtracts what the manifest already holds.

Why this exists next to ``build_dataset.py`` rather than inside it: the two
costs of a backfill are different in kind, and mixing them is what makes a
large one slow.

    downloading  - network-bound, and capped by FastF1's request budget
    building     - CPU-bound resampling, and embarrassingly parallel

``build_dataset.py`` does both per session and stops the whole run on
``RateLimited``, which is the right behaviour for a small targeted build and
the wrong one for an 80-session backfill left running overnight. So this
script splits them:

  Phase 1 warms the FastF1 HTTP cache one session at a time, *watching the
  request budget itself* and sleeping exactly as long as the rolling window
  needs before it would trip. It never trips the limiter, so it never has to
  abort and be restarted by hand.

  Phase 2 hands the now-warm cache to ``build_dataset._run_parallel``, where
  the work is pure CPU and no request is made at all.

The phases alternate over chunks, so the CPU work happens during time the
download phase would otherwise spend waiting on the budget.

A note on the budget, because it is easy to misread: FastF1 rate-limits
itself, client-side, in ``fastf1.req`` - 500 requests/hour to the timing API
and 4/second. Nothing is rejected by a server and nothing is banned; the
limiter simply raises once the rolling hour is full. It is shared per
*process*, so restarting is enough to reset the counter - which is precisely
why this script does not do that. Downloads run in a single process at the
budgeted rate. That bounds a cold backfill at roughly 50 sessions/hour no
matter how many cores are thrown at it, and the honest way to be fast is to
waste no requests and to overlap the CPU work, not to defeat the limiter.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from build_dataset import _run_parallel, _run_sequential  # noqa: E402
from pitwall import ingest, store  # noqa: E402
from pitwall.config import GRID_POINTS  # noqa: E402
from pitwall.ingest import SessionKey  # noqa: E402

log = logging.getLogger("backfill")

# Which session codes each event format actually ran. A sprint weekend trades
# FP2 and FP3 for sprint qualifying and the sprint itself, so expanding every
# event into the same five sessions would invent sessions that never existed
# and report them forever as a permanent gap.
SESSIONS_BY_FORMAT = {
    "conventional": ("FP1", "FP2", "FP3", "Q", "R"),
    "sprint_qualifying": ("FP1", "SQ", "Sprint", "Q", "R"),
    "sprint_shootout": ("FP1", "SS", "Sprint", "Q", "R"),
    "sprint": ("FP1", "Q", "FP2", "Sprint", "R"),
}


def expected_sessions(years: list[int]) -> pd.DataFrame:
    """Every session those seasons have held so far, one row each."""
    now = pd.Timestamp.utcnow().tz_localize(None)
    rows = []
    for year in years:
        sched = ingest.get_schedule(year)
        for _, event in sched.iterrows():
            if pd.to_datetime(event["EventDate"]) > now:
                continue
            fmt = str(event.get("EventFormat", "conventional"))
            if fmt not in SESSIONS_BY_FORMAT:
                log.warning("unknown event format %r at %s %s - assuming conventional",
                            fmt, year, event.get("EventName"))
            for sess in SESSIONS_BY_FORMAT.get(fmt, SESSIONS_BY_FORMAT["conventional"]):
                rows.append({
                    "year": year,
                    "round": int(event["RoundNumber"]),
                    "session": sess,
                    "event_name": str(event.get("EventName", "")),
                    "format": fmt,
                })
    # Fixed schema, so a season with nothing held yet can still be filtered
    # by session instead of raising KeyError on a columnless frame.
    return pd.DataFrame(rows, columns=["year", "round", "session",
                                       "event_name", "format"])


def find_gaps(years: list[int], sessions: list[str] | None) -> pd.DataFrame:
    """Expected sessions that the manifest does not already hold."""
    expected = expected_sessions(years)
    if sessions:
        expected = expected[expected["session"].isin(sessions)]

    manifest = store.read_manifest()
    if manifest.empty:
        return expected.reset_index(drop=True)

    # Listed is not the same as built. A session whose artefacts were deleted
    # or half-copied keeps its manifest row, and trusting the row alone meant
    # the repair pass could never queue it - the mirror image of the orphaned
    # row build_dataset can leave behind.
    have = {
        (int(r.year), int(r.round), str(r.session))
        for r in manifest.itertuples()
        if store.session_is_complete(SessionKey(int(r.year), int(r.round), str(r.session)))
    }
    missing = [
        (r.year, r.round, r.session) not in have
        for r in expected.itertuples()
    ]
    return expected[missing].reset_index(drop=True)


# --------------------------------------------------------------------------
# Phase 1 - budgeted downloading
# --------------------------------------------------------------------------

def _general_limiter():
    """FastF1's own hourly counter for the timing API.

    The limiter objects live on ``_SessionWithRateLimiting._RATE_LIMITS`` as
    *class* attributes, so every session shares them and the deque of request
    timestamps can be read directly. That is the whole trick here: knowing how
    much budget is left is what lets this wait for exactly the right amount of
    time instead of a blind 45-minute sleep.
    """
    from fastf1 import req

    for pattern, limiters in req._SessionWithRateLimiting._RATE_LIMITS.items():
        # The catch-all pattern, i.e. livetiming.formula1.com - not the
        # narrower ergast one, which session loading no longer leans on.
        if pattern.pattern.startswith("^https?://.+"):
            for lim in limiters:
                if isinstance(lim, req._CallsPerIntervalLimitRaise):
                    return lim
    return None


def _wait_for_headroom(limiter, need: int) -> None:
    """Block until ``need`` more requests can be made without tripping."""
    if limiter is None:
        return
    while True:
        now = time.time()
        window = sorted(t for t in limiter._timestamps if t > now - limiter._interval)
        headroom = limiter._timestamps.maxlen - len(window)
        if headroom >= need:
            return
        # Wait for the (need - headroom)-th oldest in-window request to age
        # out of the rolling hour, plus a second of slack.
        expires_at = window[need - headroom - 1] + limiter._interval
        sleep_s = max(1.0, expires_at - now + 1.0)
        log.info("budget full (%d/%d used) - waiting %.0f min for headroom",
                 len(window), limiter._timestamps.maxlen, sleep_s / 60)
        time.sleep(sleep_s)


def download_chunk(targets: list[SessionKey], limiter, est: float) -> float:
    """Warm the FastF1 cache for these sessions. Returns the updated estimate.

    ``est`` is the running mean of requests per session load, used to reserve
    budget *before* a load rather than discovering mid-load that it ran out.
    A load that trips the limiter half way through leaves a session partly
    cached, which is the state that makes a resumed run look like it did
    nothing.
    """
    for i, key in enumerate(targets, 1):
        if store.session_is_complete(key):
            continue
        _wait_for_headroom(limiter, int(est) + 4)  # +4 slack for a fat session
        started = time.time()
        try:
            session = ingest.load_session(key, telemetry=True)
            del session
        except ingest.RateLimited:
            # Should not happen given the reservation above, but if the
            # estimate was low, wait properly and take this session again.
            log.warning("[%d/%d] %s  budget tripped mid-load, waiting",
                        i, len(targets), key)
            _wait_for_headroom(limiter, int(est) * 2 + 10)
            try:
                session = ingest.load_session(key, telemetry=True)
                del session
            except Exception as exc:  # noqa: BLE001
                log.error("[%d/%d] %s  download FAILED: %s", i, len(targets), key, exc)
                continue
        except Exception as exc:  # noqa: BLE001 - one bad session must not stop a backfill
            log.error("[%d/%d] %s  download FAILED: %s", i, len(targets), key, exc)
            continue

        if limiter is not None:
            used = sum(1 for t in limiter._timestamps if t >= started)
            if used:
                est = 0.7 * est + 0.3 * used  # smooth, so one outlier cannot skew it
            in_window = sum(1 for t in limiter._timestamps
                            if t > time.time() - limiter._interval)
            log.info("[%d/%d] %s  cached in %.0fs (%d req, budget %d/%d)",
                     i, len(targets), key, time.time() - started, used,
                     in_window, limiter._timestamps.maxlen)
        else:
            log.info("[%d/%d] %s  cached in %.0fs", i, len(targets), key,
                     time.time() - started)
    return est


# --------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--years", type=int, nargs="+", default=[2024, 2025, 2026])
    parser.add_argument("--sessions", nargs="+", default=None,
                        help="restrict to these session codes; default is every "
                             "session the schedule says was held")
    parser.add_argument("--jobs", "-j", type=int, default=3,
                        help="parallel workers for the build phase. Each holds a "
                             "whole session's telemetry (~1-2 GB for a race), so "
                             "this is bounded by RAM, not cores")
    parser.add_argument("--chunk", type=int, default=40,
                        help="sessions to download before building them. Smaller "
                             "chunks surface results sooner; larger ones overlap "
                             "more CPU work with the budget wait")
    parser.add_argument("--grid-points", type=int, default=GRID_POINTS)
    parser.add_argument("--laps-per-driver", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true",
                        help="report the gaps and exit without downloading")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(message)s",
                        datefmt="%H:%M:%S")
    logging.getLogger("fastf1").setLevel(logging.WARNING)

    gaps = find_gaps(args.years, args.sessions)
    if gaps.empty:
        log.info("no gaps - every session held in %s is built",
                 ", ".join(str(y) for y in args.years))
        return 0

    log.info("%d missing session(s):", len(gaps))
    for year, sub in gaps.groupby("year"):
        counts = sub.groupby("session").size().to_dict()
        log.info("  %s: %s", year,
                 ", ".join(f"{k}x{v}" for k, v in sorted(counts.items())))

    if args.dry_run:
        for r in gaps.itertuples():
            log.info("  %s/%02d_%s  %s", r.year, r.round, r.session, r.event_name)
        return 0

    targets = [SessionKey(int(r.year), int(r.round), str(r.session))
               for r in gaps.itertuples()]

    limiter = _general_limiter()
    if limiter is None:
        log.warning("could not find FastF1's rate limiter - falling back to "
                    "reactive handling, this run may stop early")
    else:
        ingest.enable_cache()
        in_window = sum(1 for t in limiter._timestamps
                        if t > time.time() - limiter._interval)
        log.info("request budget: %d/%d used in the last hour",
                 in_window, limiter._timestamps.maxlen)

    build_args = SimpleNamespace(jobs=args.jobs, force=False,
                                 grid_points=args.grid_points,
                                 laps_per_driver=args.laps_per_driver,
                                 pause=0.0)
    runner = _run_parallel if args.jobs > 1 else _run_sequential

    started = time.time()
    est = 11.0  # requests per session load; refined as we go
    total_ok = total_failed = 0
    for start in range(0, len(targets), args.chunk):
        chunk = targets[start:start + args.chunk]
        log.info("=== chunk %d-%d of %d: downloading ===",
                 start + 1, start + len(chunk), len(targets))
        est = download_chunk(chunk, limiter, est)

        log.info("=== chunk %d-%d of %d: building on %d worker(s) ===",
                 start + 1, start + len(chunk), len(targets), args.jobs)
        ok, skipped, failed = runner(chunk, build_args)
        total_ok += ok
        total_failed += failed
        log.info("chunk done - %d built, %d skipped, %d failed", ok, skipped, failed)

    log.info("backfill finished in %.1f min - %d built, %d failed",
             (time.time() - started) / 60, total_ok, total_failed)

    remaining = find_gaps(args.years, args.sessions)
    if remaining.empty:
        log.info("dataset is now complete for %s",
                 ", ".join(str(y) for y in args.years))
    else:
        log.warning("%d session(s) still missing:", len(remaining))
        for r in remaining.itertuples():
            log.warning("  %s/%02d_%s  %s", r.year, r.round, r.session, r.event_name)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
