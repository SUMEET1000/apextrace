# ApexTrace — F1 Telemetry Analysis

**Live: [apextrace.onrender.com](https://apextrace.onrender.com)** — it opens on Silverstone 2024,
Russell vs Verstappen. Free hosting, so it sleeps when idle; the first request wakes it.

An analysis tool for Formula 1 timing and telemetry data. It compares drivers
corner by corner, measures tyre degradation with confidence intervals, and
separates track evolution from the tyre and fuel effects it is normally
confounded with.

Built on [FastF1](https://docs.fastf1.dev/), which wraps the official F1
timing feed: ~4–10 Hz car telemetry (speed, throttle, brake, gear, DRS, RPM),
positional data, lap and sector times, tyre compounds and stint history.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python scripts/build_dataset.py --years 2024 --sessions Q R

cd frontend && npm install && cd ..
.venv/Scripts/python scripts/run_dev.py
```

The app is then on <http://localhost:5173>, with the API and its OpenAPI docs
on <http://localhost:8000/docs>.

---

## What it answers

**"He's two tenths quicker — where?"** A lap-time gap is not actionable. The
corner analysis tiles the lap into corner and straight segments and reports the
time won or lost in each, alongside braking point, apex speed and throttle
application.

> Silverstone 2024 qualifying, Russell vs Verstappen: Russell is **0.384 s**
> faster, of which **0.326 s** comes from the corners and **0.058 s** from the
> straights. Verstappen's biggest gains are Vale (**−0.198 s**), Village
> (−0.096 s) and Luffield (−0.075 s) — the three heaviest braking zones.

**"How fast is this tyre going away?"** Per-stint regression of fuel-corrected
lap time on tyre age, pooled across the field by inverse variance.

> Bahrain 2024: soft **0.123 s/lap** (95% CI 0.113–0.133, 25 stints) versus
> hard **0.105 s/lap** (95% CI 0.101–0.109, 37 stints).

**"How much of the pace gain was the track?"** See below — this is the part
worth reading.

**"Does the undercut work?"** Pit loss measured from the data (Bahrain 2024:
**24.4 s**, decomposed into 3.3 s of in-lap and 21.1 s of out-lap), combined
with the measured degradation rate.

---

## The analysis that matters most

### Track evolution is not a trend line

A circuit gets faster as rubber goes down. The obvious way to measure that —
fit lap time against session time — **does not work**, and it is worth being
precise about why.

Within a single stint, tyre age and session time are the same column of
numbers. Lap 12 of a stint is both *12 laps of wear* and *12 laps later in the
race*. From one stint alone, "the track got faster" and "the tyre got slower"
are indistinguishable, so a trend through lap times measures their **sum**.

What breaks the collinearity is that **drivers do not pit at the same time**.
Across the field, a 10-lap-old tyre appears on lap 15 for one driver and lap 40
for another. Pooling all drivers decorrelates tyre age from session time and
makes both separately estimable:

```
corrected_laptime ~ C(Driver) + C(Compound) + C(Compound):TyreLife + cr(progress, df=4)
```

| Term | What it absorbs |
|---|---|
| `C(Driver)` | raw pace differences between cars |
| `C(Compound)` | how quick each tyre is when new, independent of its age |
| `C(Compound):TyreLife` | degradation, allowed to differ per compound |
| `cr(progress, df=4)` | natural cubic spline on session progress — **this is track evolution** |

The compound main effect is not decoration. Without it a constant pace
difference between tyres has nowhere to go but the age slope: on a noiseless
fixture where both compounds truly degrade at 0.100 s/lap, a 2 s soft-tyre
advantage alone moves the estimates to 0.179 and 0.031.

The decomposition is only reported when it is actually identified. Where tyre
age and session progress cannot be told apart — a single-stint session, or one
where every tyre ages with the race — OLS still answers, from a pseudoinverse,
with a confident arbitrary split. The fit is refused instead. Across the stored
races the two carry a variance inflation factor of 1.5–6.1, against a
conventional alarm threshold of 10.

Fuel is removed *beforehand* rather than fitted, because fuel load is almost a
perfect linear function of lap number and would otherwise be swallowed by the
evolution term.

**The result, Bahrain 2024:**

| Method | Track evolution |
|---|---|
| Pooled model (tyre + fuel removed) | **+0.372 s** — the circuit got faster |
| Naive trend through lap times | **−1.013 s** — the circuit got *slower* |

The naive estimate does not merely misstate the size. It gets the **direction
wrong**, because degradation dominates the raw lap times. Model R² = 0.780
across 988 clean laps and 20 drivers.

The band drawn around that curve is an interval for the curve itself — the
contrast between each point and the session start, with its own variance taken
from the fitted covariance matrix. It is therefore exactly zero wide at the
start, where the plotted quantity is a number minus itself.

Two independent checks that the model is doing what it claims:

- The per-compound degradation it recovers as a by-product (hard 0.107, soft
  0.117 s/lap) reproduces the separate per-stint fits (0.105, 0.123 s/lap),
  which are computed by an entirely different route.
- On synthetic races with known parameters, the model recovers both effects
  simultaneously — and
  [a test](tests/test_models.py) asserts that its accuracy *degrades* when pit
  stops are artificially synchronised, which is exactly what the
  identification argument predicts.

---

## How the data pipeline works

```
FastF1 (official F1 timing API)
        │
        ▼  scripts/build_dataset.py — resumable, rate-limit aware
   clean · resample · quantise
        │
        ▼
   data/processed/<year>/<round>_<session>/
        laps · telemetry · trackmap · corners · weather · results   (Parquet)
        │
        ▼
   pitwall/  — pure pandas/numpy analysis library (no UI, no web framework)
        │
        ▼
   api/  — FastAPI: caching, JSON safety, chart figures over HTTP
        │
        ▼
   frontend/  — React + TypeScript: layout, widgets and deep links only
```

`pitwall/` never imports a UI or web framework. Every analysis function is
unit-testable and can be lifted into a notebook unchanged — which is why
replacing the original Streamlit frontend with React was a change to `api/`
and `frontend/` and touched no analysis code at all.

The charts are the same figures either way: `api/charts.py` calls the existing
`pitwall/viz` builders and serves `fig.to_json()`, which the browser renders
with a version-matched plotly.js. Nothing about a chart is re-implemented in
the frontend.

### The design decision that made it shippable

Telemetry is sampled in *time*, so two drivers' samples never line up in space
and every comparison needs a merge-and-interpolate. Instead, the ETL resamples
every lap onto a **uniform 1000-point relative-distance grid**. Comparison then
becomes elementwise arithmetic on aligned arrays.

Aligning on *relative* distance (fraction of lap) rather than absolute metres
is deliberate: drivers take different lines, so measured lap distance varies by
a few tenths of a percent. FastF1's own `delta_time` handles this by rescaling
one lap by `ref_len / comp_len` — algebraically the same alignment, computed
once at ETL time instead of on every comparison.

Profiling the first build showed 2.2 MB per session, which would have put the
full three-season dataset near 200 MB. Three observations cut it **4.7× to
477 KB** with no analytically meaningful loss:

| Change | Saved | Why it is lossless |
|---|---|---|
| Drop `Distance` / `RelDistance` | 317 KB | Recoverable from row index × lap length on a uniform grid |
| Move `X`/`Y`/`Z` to one session-level track map | 625 KB | Circuit geometry is identical for every driver — it is not lap data |
| Quantise channels to real precision | ~800 KB | Speed to 0.1 km/h, throttle to 1%, RPM to 10 rpm, time to 1 µs |

At a 5.8 km lap, 1000 points is ~5.8 m resolution — finer than the raw feed at
racing speed (8–20 m between samples at 4–10 Hz).

---

## Validation

FastF1's own `utils.delta_time` is **deprecated**, and its docstring warns it
"has a tendency to give inaccurate results", recommending verification against
sector times instead. So the pipeline is validated against **official timing**,
not against a function its authors no longer trust.

A sector line is a fixed point on track. Take each driver's officially timed
Sector 1 duration, find where in their telemetry that much time had elapsed,
and every driver should land on the same distance:

| Check | Result |
|---|---|
| S1 line located across 47 laps | **± 3.2 m** (0.06% of lap — under one car length) |
| S2 line | ± 6.0 m (0.10%) |
| Delta time vs official S1 gaps | median **0.068 s**, p90 0.091 s |
| Telemetry lap duration vs timing feed | 0.000 s |

The 0.068 s residual on sector gaps is the intrinsic limit of telemetry-derived
delta time — the same limitation FastF1 documents. It is reported here rather
than hidden, because it bounds what the corner-by-corner numbers can be trusted
to.

**64 tests**, run against synthetic data with known parameters:

```bash
.venv/Scripts/python -m pytest tests/ -q
.venv/Scripts/python scripts/validate_dataset.py
```

Tests worth pointing at, because each encodes a decision:

- Degradation fits recover a known slope, and the **confidence intervals
  bracket the true value** — a CI that misses is worse than no CI.
- Omitting fuel correction is asserted to bias degradation *downward*, which is
  the reason the correction exists.
- A wrong fuel assumption is shown to **invent track evolution that was never
  there** — which is why the app exposes fuel as sliders rather than burying it.
- Segment deltas sum exactly to the lap-time gap, on synthetic and real data.

---

## Judgement calls

**Assumptions are exposed, not hidden.** Fuel effect (s/kg) and starting fuel
load are UI sliders. They are estimates, and fuel error maps almost perfectly
onto the evolution term, so the user can see what the analysis rests on.

**Filtering is audited, not silent.** `clean_laps` returns a rejection
breakdown that the app displays — traffic, safety cars and pit laps removed,
with counts. Silent filtering is how an analysis loses trust.

**Corners *and* straights.** The lap is tiled completely, so per-segment deltas
sum to the lap-time gap. Reporting corners alone would quietly drop the
straights, where power and slipstream differences live.

**The undercut model does not charge the pit loss.** You concede the pit loss
when you box; your rival concedes the same one a few laps later, so it cancels.
What remains is the time your fresher tyre took out of them in between. The
intuitive version — repaying a ~20 s stop from a tyre advantage — makes every
undercut look impossible. Pit loss decides what traffic you rejoin into, not
this comparison.

**Colour is validated, not chosen by eye.** Series colours are a categorical
palette checked against this app's own dark surface: all eight pass the
lightness band, chroma floor, CVD separation (worst adjacent ΔE 8.4 under
protanopia), normal-vision floor and 3:1 contrast.

The official Pirelli tyre colours **fail** that same check — soft (red) against
intermediate (green) collapses to ΔE 3.5 under deuteranopia, and hard is pure
white with zero chroma. They are kept anyway, because every F1 viewer already
reads them and substituting invented colours would make the tool worse for its
users. The mitigation is that compound colour is never the only channel: every
compound is labelled in text, and the degradation view facets by compound
rather than colouring by it.

**No dual-axis charts.** Where two quantities of different units are read
together — lap time and track temperature — they are stacked as panels on a
shared x-axis. Two arbitrary scalings on one frame manufacture correlations.

---

## Layout

| Path | What lives there |
|---|---|
| `pitwall/transforms.py` | Distance-grid resampling, delta time, lap cleaning, fuel correction |
| `pitwall/corners.py` | Corner segmentation and per-corner metrics |
| `pitwall/degradation.py` | Per-stint OLS (HC3), compound pooling, AIC cliff detection |
| `pitwall/evolution.py` | The pooled track-evolution model |
| `pitwall/strategy.py` | Stints, race pace, pit loss, undercut |
| `pitwall/viz/` | Shared theme and one figure builder per view |
| `scripts/build_dataset.py` | ETL CLI |
| `scripts/validate_dataset.py` | Post-build integrity checks |
| `api/` | FastAPI service: cached loaders, JSON endpoints, chart figures |
| `frontend/` | React + TypeScript UI, Vite build |

---

## Deploying

The app is a pure reader: it loads the parquet artefacts under
`data/processed/` and never calls the F1 API at runtime. `pitwall.ingest`
imports `fastf1` but only opens the network inside `enable_cache()` and the
ETL functions, which the UI does not touch. That means the built dataset is
committed to the repo and the deployed app needs no credentials, no cron and
no outbound access.

Build the frontend once, and the API serves it from its own origin — one
process, no separate static host:

```bash
cd frontend && npm ci && npm run build && cd ..
.venv/Scripts/python -m uvicorn api.main:app --host 0.0.0.0 --port 8000
```

`api/main.py` mounts `frontend/dist` only when it exists, and falls back to
`index.html` for client-side routes so a hard refresh on `/corner-analysis`
works. **Run a single worker:** the loaders in `api/cache.py` are per-process
and one of them holds a decoded race telemetry frame (~74 MB).

Rebuilding the dataset is a local operation — re-run `build_dataset.py`, commit
the new session directories and the updated `manifest.parquet`, and the
deployment follows the push.

---

## Notes

`fastf1` requires `pandas<3`, so the project must run in its own virtual
environment — a base install with pandas 3.x will not resolve.

Data © Formula 1. This is an independent analysis project, not affiliated with
Formula 1, the FIA, or any team.
