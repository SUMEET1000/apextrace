"""Bake the landing page's numbers into frontend/src/landing/facts.json.

The landing is a static page that must show its answer while the API is still
waking (about 46 s on Render's free tier), so it cannot fetch its numbers. It
reads them from this file instead, and ``--check`` is what stops the file
drifting from what the API computes: it rebuilds everything in memory and
exits 1 naming every field that differs from the committed copy.

Every analysis number comes from the API's own endpoints, called in-process
through FastAPI's TestClient, so nothing here re-implements a computation. The
circuit drawing is read through the same cache loaders the API uses; turning
it into an SVG path is presentation, not analysis.

    .venv/Scripts/python scripts/landing_facts.py           # write the file
    .venv/Scripts/python scripts/landing_facts.py --check   # exit 1 on drift
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import warnings
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
OUT = REPO / "frontend" / "src" / "landing" / "facts.json"

with warnings.catch_warnings():
    # starlette's TestClient warns about its httpx backend on import; it works.
    warnings.simplefilter("ignore", DeprecationWarning)
    from fastapi.testclient import TestClient

from api import cache  # noqa: E402
from api.main import app  # noqa: E402
from pitwall.viz.trackmap import _rotate  # noqa: E402

SLUG, DRIVER_A, DRIVER_B = "2024/12_Q", "RUS", "VER"
RACE_SLUG = "2024/01_R"

# Silverstone's corner names, by turn number. FastF1 carries corner numbers
# only, so the names are a fixed fact about the circuit, not data.
CORNER_NAMES = ("Abbey", "Farm", "Village", "The Loop", "Aintree", "Brooklands",
                "Luffield", "Woodcote", "Copse", "Maggotts", "Becketts",
                "Becketts", "Becketts", "Chapel", "Stowe", "Vale", "Vale", "Club")
# The FIA's published lap length. The telemetry's own distance (5,831 m on
# Russell's pole lap) is the racing line, so it is not quoted as the length.
LAP_LENGTH_KM = 5.891

# Rounded so the file is identical on every machine: pandas sums can differ in
# the last float bits across platforms, and the page shows three decimals.
DP = 5


def r(value: float, dp: int = DP) -> float:
    return round(float(value), dp)


def get(client: TestClient, path: str, **params) -> dict:
    response = client.get(path, params=params)
    if response.status_code != 200:
        raise SystemExit(f"{path} {params} returned {response.status_code}: {response.text[:300]}")
    return response.json()


def track_drawing() -> dict:
    """The circuit as an SVG path, in the orientation of the official map.

    The stored track map is already rotated at ingest; the corner markers are
    stored unrotated with the angle beside them, and are turned here the same
    way ``pitwall.viz.trackmap`` turns them. Every third point is kept: 334
    points draw the circuit smoothly and keep the path short.
    """
    track = cache.load_artefact(SLUG, "trackmap")
    corners = cache.load_artefact(SLUG, "corners")
    mx, my = _rotate(corners["X"].to_numpy(dtype=float), corners["Y"].to_numpy(dtype=float),
                     float(corners["Rotation"].iloc[0]))

    pts = list(zip(track["X"].astype(float), track["Y"].astype(float)))
    marks = list(zip(mx, my))
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    min_x, max_y = min(xs), max(ys)
    scale = 1000 / max(max(xs) - min_x, max_y - min(ys))

    def fit(p):
        return round((p[0] - min_x) * scale + 40, 1), round((max_y - p[1]) * scale + 40, 1)

    path = "M" + " L".join(f"{a},{b}" for a, b in (fit(p) for p in pts[::3])) + " Z"
    if len(marks) != len(CORNER_NAMES):
        raise SystemExit(f"{SLUG} has {len(marks)} corner markers, the names table has "
                         f"{len(CORNER_NAMES)}")
    return {
        "d": path,
        "w": round((max(xs) - min_x) * scale + 80),
        "h": round((max_y - min(ys)) * scale + 80),
        "length_km": LAP_LENGTH_KM,
        "corners": [{"n": i + 1, "name": CORNER_NAMES[i], "x": fit(p)[0], "y": fit(p)[1]}
                    for i, p in enumerate(marks)],
    }


def test_count() -> int:
    out = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q", "--collect-only"],
                         cwd=REPO, capture_output=True, text=True, check=False)
    match = re.search(r"(\d+) tests? collected", out.stdout)
    if not match:
        raise SystemExit("pytest --collect-only printed no count:\n" + out.stdout[-800:] + out.stderr[-800:])
    return int(match.group(1))


def data_mib() -> int:
    """Size of data/processed in MiB, counted from file sizes.

    ``du -sm`` reports 631 here, which is disk space allocated in 4 KiB
    clusters and so depends on the filesystem; the file sizes do not.
    """
    root = REPO / "data" / "processed"
    total = sum(f.stat().st_size for f in root.rglob("*") if f.is_file())
    return round(total / 2**20)


def build() -> dict:
    client = TestClient(app)
    comp = get(client, "/api/corner-analysis", slug=SLUG, driver1=DRIVER_A, driver2=DRIVER_B)
    home = get(client, "/api/home", slug=SLUG)
    arc = get(client, "/api/race-arc", slug=RACE_SLUG)
    manifest = get(client, "/api/manifest")
    theme = get(client, "/api/theme")

    # Position and Q3 time per driver, from the qualifying classification.
    grid = {row["Driver"]: row for row in home["classification"]}
    pole = next(row for row in home["classification"] if row["Pos"] == 1)
    p2 = next(row for row in home["classification"] if row["Pos"] == 2)

    def seconds(laptime: str) -> float:   # the API formats Q3 as m:ss.sss
        minutes, rest = laptime.split(":")
        return int(minutes) * 60 + float(rest)

    corners = [s for s in comp["segments"] if s["kind"] == "corner"]
    straights = [s for s in comp["segments"] if s["kind"] == "straight"]
    names = dict(zip((f"T{i}" for i in range(1, 19)), CORNER_NAMES))
    # Positive delta = the first driver (Russell) was faster there.
    a_wins = [c for c in corners if c["delta_s"] > 0]
    b_wins = sorted((c for c in corners if c["delta_s"] < 0), key=lambda c: c["delta_s"])
    top = b_wins[:3]
    rest = b_wins[3:]

    def turn(label: str) -> int:
        return int(label[1:])

    count_bars = (
        [{"label": f"{DRIVER_A}_corners", "value": r(sum(c["delta_s"] for c in a_wins)),
          "turns": [turn(c["label"]) for c in a_wins]}]
        + [{"label": c["label"], "name": names[c["label"]], "value": r(c["delta_s"]),
            "turns": [turn(c["label"])]} for c in top]
        + [{"label": f"{DRIVER_B}_other", "value": r(sum(c["delta_s"] for c in rest)),
            "turns": [turn(c["label"]) for c in rest]}]
        + [{"label": "straights", "value": r(sum(s["delta_s"] for s in straights)),
            "turns": [], "count": len(straights)}]
    )

    deg = {row["Compound"]: {"s_per_lap": r(row["deg_s_per_lap"]), "ci_low": r(row["ci_low"]),
                             "ci_high": r(row["ci_high"]), "stints": int(row["n_stints"])}
           for row in arc["degradation"]["summary"]}
    loss = arc["strategy"]["pit_loss"]

    def driver(code: str, time_s: float) -> dict:
        row = grid[code]
        return {"code": code, "name": row["Name"], "team": row["Team"],
                "position": int(row["Pos"]), "time_s": r(time_s, 3), "time": row["Q3"]}

    return {
        "source": {"slug": SLUG, "race_slug": RACE_SLUG,
                   "event": home["meta"]["event_name"], "location": home["meta"]["location"],
                   "year": int(home["meta"]["year"]), "session": home["session_label"]},
        "lap": {
            "a": driver(DRIVER_A, comp["time_a"]),
            "b": driver(DRIVER_B, comp["time_b"]),
            "gap_s": r(comp["summary"]["total_delta_s"]),
            "corner_s": r(comp["summary"]["corner_delta_s"]),
            "straight_s": r(comp["summary"]["straight_delta_s"]),
        },
        "pole": {"code": pole["Driver"], "time": pole["Q3"], "p2_code": p2["Driver"],
                 "margin_s": r(seconds(p2["Q3"]) - seconds(pole["Q3"]), 3)},
        "corners": [{"n": turn(c["label"]), "name": names[c["label"]], "delta_s": r(c["delta_s"])}
                    for c in corners],
        "faster": {"a": len(a_wins), "b": len(b_wins), "b_top": [turn(c["label"]) for c in top]},
        "count_bars": count_bars,
        "track": track_drawing(),
        "tyres": deg,
        "pit_loss": {"total_s": r(loss["pit_loss_s"], 3), "in_s": r(loss["in_lap_s"], 3),
                     "out_s": r(loss["out_lap_s"], 3), "stops": int(loss["n_stops"])},
        "spec": {"sessions": len(manifest["sessions"]), "seasons": len(manifest["years"]),
                 "tests": test_count(), "data_mib": data_mib()},
        "compound_colours": theme["compound_colours"],
        "session_labels": theme["session_labels"],
    }


def diff(old, new, path="") -> list[str]:
    if isinstance(old, dict) and isinstance(new, dict):
        out = []
        for key in sorted(set(old) | set(new)):
            if key not in old or key not in new:
                out.append(f"{path}.{key}: {'missing' if key not in new else 'extra'} in the rebuild")
            else:
                out += diff(old[key], new[key], f"{path}.{key}")
        return out
    if isinstance(old, list) and isinstance(new, list) and len(old) == len(new):
        return [line for i, (a, b) in enumerate(zip(old, new)) for line in diff(a, b, f"{path}[{i}]")]
    return [] if old == new else [f"{path}: committed {json.dumps(old)[:80]} != rebuilt {json.dumps(new)[:80]}"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if the committed file has drifted")
    args = parser.parse_args()

    facts = build()
    text = json.dumps(facts, indent=1, ensure_ascii=False) + "\n"
    if not args.check:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {OUT.relative_to(REPO)}")
        return 0

    if not OUT.exists():
        print(f"FAIL {OUT.relative_to(REPO)} does not exist; run without --check")
        return 1
    drift = diff(json.loads(OUT.read_text(encoding="utf-8")), facts)
    for line in drift:
        print("FAIL", line)
    print(f"{len(drift)} fields drifted" if drift else "facts.json matches the API")
    return 1 if drift else 0


if __name__ == "__main__":
    os.chdir(REPO)
    sys.exit(main())
