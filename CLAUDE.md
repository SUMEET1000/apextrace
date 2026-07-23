# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment

`fastf1` pins `pandas<3`, and the base conda install on this machine has pandas 3.x. **Everything must run through `.venv`** — a bare `python` will resolve the wrong pandas.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
```

## Commands

```bash
# Build the curated dataset (resumable; skips complete sessions unless --force)
.venv/Scripts/python scripts/build_dataset.py --years 2024 --sessions Q R
.venv/Scripts/python scripts/build_dataset.py --years 2024 --rounds 12 --sessions Q --force

# Post-build integrity checks against the manifest
.venv/Scripts/python scripts/validate_dataset.py [--strict]

# Tests
.venv/Scripts/python -m pytest tests/ -q
.venv/Scripts/python -m pytest tests/test_models.py -q                       # one file
.venv/Scripts/python -m pytest tests/test_models.py::test_evolution_recovers_a_known_track_gain -q

# App
.venv/Scripts/python -m streamlit run app/Home.py
```

`build_dataset.py` stops early and cleanly on `ingest.RateLimited` — the F1 API budget is hourly, so re-running the same command later resumes from where it stopped. Ordinary per-session failures are logged and the backfill continues.

## Architecture

Three layers with a hard boundary between each:

```
pitwall/ingest.py   ← the ONLY module that touches FastF1 / the network
pitwall/*           ← pure pandas/numpy analysis; must never import streamlit
app/                ← Streamlit UI: caching, layout, deep links only
```

`pitwall/__init__.py` states the streamlit prohibition explicitly. It is what keeps every analysis function unit-testable without a browser or a network. Caching lives in [app/common.py](app/common.py) as `st.cache_data` wrappers around `pitwall.store`, not in the library.

`app/` modules do `sys.path.insert(0, <repo root>)` at the top and import `brand` / `common` as flat modules — Streamlit runs pages as scripts, so this is load-bearing, not incidental. Keep the `# noqa: E402` imports below it.

### Data flow

```
FastF1 → scripts/build_dataset.py → data/processed/<year>/<RR>_<S>/*.parquet → pitwall → app
```

Artefacts per session (see `store.ARTEFACTS`): `laps`, `telemetry`, `trackmap`, `corners`, `weather`, `results`. `data/processed/manifest.parquet` is the index of built sessions and drives the app's session picker. `data/raw_cache/` is the FastF1 HTTP cache — gitignored, regenerable, can grow to GBs.

### Key data contracts

**`SessionKey(year, round, session)`** identifies a session everywhere — ETL, manifest, filesystem, URL bar. Its `.slug` is `"2024/12_Q"`; `store.key_from_slug` inverts it. The app passes slugs (hashable strings) into cached loaders and converts at the boundary.

**The distance grid.** Every stored lap is resampled onto `GRID_POINTS` (1000) uniform *relative*-distance points. This makes driver-vs-driver comparison elementwise arithmetic instead of merge-and-interpolate. Consequences to respect:
- Two laps on the same grid can be subtracted directly; `transforms.delta_time` errors if lengths differ.
- Continuous channels interpolate linearly; discrete ones (`Brake`, `nGear`, `DRS`) use zero-order hold — never linearly interpolate a gear.
- `Distance` / `RelDistance` are *not stored*; they are reconstructed from row position × `LapLength` in `decode_grid`.

**Encoded vs decoded telemetry.** On disk, telemetry is quantised (`t_us` int32, `Speed_dq`, `Throttle_pct`, `RPM_dq`) with X/Y/Z hoisted into the session-level `trackmap`. Read it with `store.read_telemetry()` (decodes to physical units), **not** `read_artefact(key, "telemetry")`.

**Timedeltas.** Parquet round-trips timedeltas badly, so the ETL flattens them to `*_s` float columns. `store.read_laps()` restores the `LapTime` / `Sector*Time` / `PitInTime` timedelta columns — the analysis modules expect the restored FastF1 schema, so use `read_laps`, not `read_artefact(key, "laps")`.

### Analysis modules

| Module | Entry points |
|---|---|
| `transforms.py` | `resample_to_distance_grid`, `delta_time`, `clean_laps`, `fuel_correct`, `encode_grid`/`decode_grid` |
| `corners.py` | `build_segments` (tiles the lap), `corner_metrics`, `compare_corners` |
| `degradation.py` | `prepare` (clean + fuel-correct), `fit_stint`, `fit_all_stints`, `compound_summary` |
| `evolution.py` | `fit_evolution` (the pooled model), `naive_evolution` (the deliberate strawman) |
| `strategy.py` | `stint_table`, `pit_loss`, `race_pace`, `undercut_gain` |

`degradation.prepare()` is the standard front door for anything that consumes lap times — it returns `(laps_with_LapTime_corrected_s, rejections)`. `evolution.fit_evolution()` requires input that has already been through it.

## Conventions that carry design intent

**`pitwall/config.py` is the single place for stated assumptions.** Fuel effect, grid points, outlier thresholds, corner clipping limits, compound colours. Do not inline these constants at call sites; add them here with a comment explaining the number.

**Filtering is audited, never silent.** `clean_laps` returns `(kept, rejections)` where `rejections` has one row per reason with counts, and the app displays it. Any new filter must record itself the same way.

**Corner segmentation tiles the lap completely.** Corners *and* straights, so per-segment deltas sum exactly to the lap-time gap. Tests assert this. Adding a segment kind must preserve the tiling.

**Track evolution is a pooled model, not a trend.** Fuel is removed *before* fitting rather than fitted, because fuel load is nearly collinear with lap number and would be swallowed by the evolution spline. The formula lives in `evolution.fit_evolution` and is documented at length in the module docstring and README.

**No dual-axis charts.** Quantities with different units are stacked as panels sharing an x-axis (see `charts.evolution_with_temperature`). Compound colours are fixed by `config.COMPOUND_COLOURS` and never reused for drivers; compound is always also encoded in text or faceting, because the official Pirelli palette fails CVD checks.

## Tests

`tests/conftest.py` generates physically plausible synthetic telemetry (`make_lap`) — unit tests run against known parameters with no network and no dataset. `tests/test_integration.py` runs against real Silverstone 2024 Q data and **skips** if that session has not been built.

The suite encodes decisions, not just behaviour. Tests like `test_ignoring_fuel_correction_biases_degradation_downward`, `test_wrong_fuel_assumption_leaks_into_evolution` and `test_model_declines_when_stops_are_not_staggered` exist to assert *why* a piece of the pipeline is there. If one starts failing, the modelling assumption is what broke — not the assertion.
