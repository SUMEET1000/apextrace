"""Tests for degradation, track evolution and strategy.

These run on synthetic races built with **known** parameters, so each test
asks the only question that matters for a model: given data where the true
answer is known, does the fit recover it?
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pitwall import degradation, evolution, strategy

# The fuel load make_race() generates with. Every call to prepare() in these
# tests must use the same value: a mismatch between the true fuel load and
# the assumed one shows up as spurious degradation and spurious track
# evolution (see test_wrong_fuel_assumption_leaks_into_evolution).
TEST_FUEL_KG = 100.0


def make_race(
    *,
    n_drivers: int = 10,
    total_laps: int = 50,
    base_pace: float = 90.0,
    deg: dict[str, float] | None = None,
    evolution_s: float = 0.0,
    fuel_effect: float = 0.032,
    fuel_kg: float = 100.0,
    stagger_stops: bool = True,
    noise: float = 0.05,
    seed: int = 0,
) -> pd.DataFrame:
    """Synthesise a race with known degradation, evolution and fuel effects.

    ``stagger_stops`` controls the whole identification question: when drivers
    pit at different laps, tyre age and session time are decorrelated and both
    effects are separately estimable. When they all pit together, they are
    not.
    """
    rng = np.random.default_rng(seed)
    deg = deg or {"SOFT": 0.12, "HARD": 0.06}
    compounds = list(deg)
    kg_per_lap = fuel_kg / total_laps

    rows = []
    for d in range(n_drivers):
        driver = f"D{d:02d}"
        driver_offset = rng.normal(0, 0.4)
        pit_lap = (18 + (d * 2) % 16) if stagger_stops else 25

        stint, tyre_life, compound = 1, 1, compounds[0]
        for lap in range(1, total_laps + 1):
            if lap == pit_lap:
                stint, tyre_life = 2, 1
                compound = compounds[1 % len(compounds)]
                is_pit = True
            else:
                is_pit = False

            progress = lap / total_laps
            lap_time = (
                base_pace
                + driver_offset
                + deg[compound] * tyre_life           # tyre wear
                + fuel_effect * kg_per_lap * (total_laps - lap)  # fuel load
                - evolution_s * progress              # track rubbering in
                + rng.normal(0, noise)
            )
            rows.append({
                "Driver": driver, "Team": f"T{d // 2}",
                "LapNumber": float(lap), "Stint": float(stint),
                "Compound": compound, "TyreLife": float(tyre_life),
                "LapTime": pd.to_timedelta(lap_time, unit="s"),
                "IsAccurate": True,
                "PitInTime": pd.to_timedelta(5.0, unit="s") if is_pit else pd.NaT,
                "PitOutTime": pd.NaT,
                "TrackStatus": "1",
            })
            tyre_life += 1

    return pd.DataFrame(rows)


# --------------------------------------------------------------- degradation

def test_degradation_recovers_a_known_rate():
    race = make_race(deg={"SOFT": 0.15, "HARD": 0.07}, seed=1)
    prepared, _ = degradation.prepare(race, year=2024, total_laps=50, fuel_kg=TEST_FUEL_KG)
    summary = degradation.compound_summary(degradation.fit_all_stints(prepared))

    rates = summary.set_index("Compound")["deg_s_per_lap"]
    assert rates["SOFT"] == pytest.approx(0.15, abs=0.02)
    assert rates["HARD"] == pytest.approx(0.07, abs=0.02)


def test_confidence_intervals_bracket_the_truth():
    """A CI that does not contain the true value is worse than no CI."""
    race = make_race(deg={"SOFT": 0.12, "HARD": 0.05}, seed=2)
    prepared, _ = degradation.prepare(race, year=2024, total_laps=50, fuel_kg=TEST_FUEL_KG)
    summary = degradation.compound_summary(degradation.fit_all_stints(prepared))

    for compound, truth in (("SOFT", 0.12), ("HARD", 0.05)):
        row = summary[summary["Compound"] == compound].iloc[0]
        assert row["ci_low"] <= truth <= row["ci_high"], (
            f"{compound}: true {truth} outside CI "
            f"[{row['ci_low']:.4f}, {row['ci_high']:.4f}]"
        )


def test_degradation_ordering_is_preserved():
    race = make_race(deg={"SOFT": 0.20, "HARD": 0.04}, seed=3)
    prepared, _ = degradation.prepare(race, year=2024, total_laps=50, fuel_kg=TEST_FUEL_KG)
    summary = degradation.compound_summary(degradation.fit_all_stints(prepared))
    rates = summary.set_index("Compound")["deg_s_per_lap"]
    assert rates["SOFT"] > rates["HARD"]


def test_ignoring_fuel_correction_biases_degradation_downward():
    """The reason fuel correction exists, stated as a test.

    Fuel burn makes the car faster through a stint, masking tyre wear. Without
    the correction the fitted degradation must come out too low.
    """
    race = make_race(deg={"SOFT": 0.12, "HARD": 0.12}, fuel_effect=0.04, seed=4)

    corrected, _ = degradation.prepare(race, year=2024, total_laps=50, fuel_kg=TEST_FUEL_KG)
    uncorrected, _ = degradation.prepare(race, year=2024, total_laps=50, fuel_kg=0.0)

    fit_corrected = degradation.fit_all_stints(corrected)["deg_s_per_lap"].mean()
    fit_uncorrected = degradation.fit_all_stints(uncorrected)["deg_s_per_lap"].mean()

    assert fit_corrected == pytest.approx(0.12, abs=0.02)
    assert fit_uncorrected < fit_corrected - 0.02


def test_short_stints_are_not_fitted():
    race = make_race(total_laps=50, seed=5)
    tiny = race[race["LapNumber"] <= 3]
    assert degradation.fit_stint(tiny) is None


def test_cliff_detection_flags_accelerating_degradation():
    """A quadratic stint should be flagged; a linear one should not."""
    age = np.arange(1, 26)
    linear = pd.DataFrame({
        "Driver": "D1", "Stint": 1.0, "Compound": "SOFT", "Team": "T",
        "LapNumber": age.astype(float), "TyreLife": age.astype(float),
        "LapTime_corrected_s": 90 + 0.08 * age,
    })
    cliff = linear.copy()
    cliff["LapTime_corrected_s"] = 90 + 0.03 * age + 0.006 * age ** 2

    assert degradation.fit_stint(linear)["has_cliff"] is False
    assert degradation.fit_stint(cliff)["has_cliff"] is True


# ----------------------------------------------------------------- evolution

def test_evolution_recovers_a_known_track_gain():
    """The headline claim of the module, tested directly."""
    race = make_race(evolution_s=1.0, deg={"SOFT": 0.10, "HARD": 0.05}, seed=6)
    prepared, _ = degradation.prepare(race, year=2024, total_laps=50, fuel_kg=TEST_FUEL_KG)
    result = evolution.fit_evolution(prepared, total_laps=50)

    assert result is not None
    assert result["total_gain_s"] == pytest.approx(1.0, abs=0.25)


def test_evolution_and_degradation_are_separated():
    """Both effects present at once - the model must not confuse them."""
    race = make_race(evolution_s=0.8, deg={"SOFT": 0.15, "HARD": 0.06}, seed=7)
    prepared, _ = degradation.prepare(race, year=2024, total_laps=50, fuel_kg=TEST_FUEL_KG)
    result = evolution.fit_evolution(prepared, total_laps=50)

    assert result["total_gain_s"] == pytest.approx(0.8, abs=0.25)

    deg = result["degradation"]
    rates = {row.Compound.split("[T.")[-1].rstrip("]"): row.deg_s_per_lap
             for row in deg.itertuples()}
    soft = next(v for k, v in rates.items() if "SOFT" in k)
    hard = next(v for k, v in rates.items() if "HARD" in k)
    assert soft == pytest.approx(0.15, abs=0.03)
    assert hard == pytest.approx(0.06, abs=0.03)


def test_no_evolution_is_reported_as_none():
    race = make_race(evolution_s=0.0, seed=8)
    prepared, _ = degradation.prepare(race, year=2024, total_laps=50, fuel_kg=TEST_FUEL_KG)
    result = evolution.fit_evolution(prepared, total_laps=50)
    assert abs(result["total_gain_s"]) < 0.25


def test_naive_estimate_gets_evolution_badly_wrong():
    """Why the pooled model exists, stated as a test.

    A trend through lap times alone cannot tell "the track got faster" from
    "the tyres got slower", so it reports their *sum*. When degradation
    dominates - which it usually does - the naive estimate does not merely
    overstate the magnitude, it reports the wrong direction entirely: lap
    times rise through the race, so the circuit looks like it is getting
    slower even while it is genuinely rubbering in.
    """
    race = make_race(evolution_s=0.5, deg={"SOFT": 0.15, "HARD": 0.15}, seed=9)
    prepared, _ = degradation.prepare(race, year=2024, total_laps=50, fuel_kg=TEST_FUEL_KG)

    modelled = evolution.fit_evolution(prepared, total_laps=50)["total_gain_s"]
    naive_curve = evolution.naive_evolution(prepared, total_laps=50)
    naive = naive_curve["evolution_s"].iloc[0] - naive_curve["evolution_s"].iloc[-1]

    # The model recovers the truth...
    assert modelled == pytest.approx(0.5, abs=0.25)
    # ...while the naive trend is dragged the other way by degradation.
    assert naive < modelled - 0.5
    assert naive < 0, "degradation should make the naive trend show a slowing track"


def test_model_declines_when_stops_are_not_staggered():
    """Honesty check: with every driver pitting on the same lap, tyre age and
    session time stay collinear and the estimate should not be trusted.

    The model still fits, but it can no longer separate the two effects, so
    its evolution estimate drifts away from the truth. This test documents
    that limitation rather than pretending it does not exist.
    """
    staggered = make_race(evolution_s=0.8, stagger_stops=True, seed=10)
    synchronised = make_race(evolution_s=0.8, stagger_stops=False, seed=10)

    def gain(race):
        prepared, _ = degradation.prepare(race, year=2024, total_laps=50, fuel_kg=TEST_FUEL_KG)
        result = evolution.fit_evolution(prepared, total_laps=50)
        return abs(result["total_gain_s"] - 0.8) if result else float("inf")

    assert gain(staggered) < 0.25
    assert gain(synchronised) > gain(staggered)


def test_evolution_declines_on_insufficient_data():
    race = make_race(n_drivers=2, total_laps=10, seed=11)
    prepared, _ = degradation.prepare(race, year=2024, total_laps=10, fuel_kg=TEST_FUEL_KG)
    assert evolution.fit_evolution(prepared, total_laps=10) is None


# ------------------------------------------------------------------ strategy

def test_stint_table_finds_every_stint():
    race = make_race(n_drivers=4, seed=12)
    stints = strategy.stint_table(race)
    assert len(stints) == 8                      # 4 drivers x 2 stints
    assert set(stints["Driver"]) == {"D00", "D01", "D02", "D03"}
    assert (stints["laps"] > 0).all()


def test_race_pace_ranks_by_median():
    race = make_race(n_drivers=6, seed=13)
    prepared, _ = degradation.prepare(race, year=2024, total_laps=50, fuel_kg=TEST_FUEL_KG)
    pace = strategy.race_pace(prepared)
    assert pace["median_s"].is_monotonic_increasing
    assert pace["gap_to_best_s"].iloc[0] == 0.0


def test_pit_loss_sums_in_and_out_lap_components():
    """In- and out-laps carry very different shares of the loss.

    Run on a flat race (no degradation, no fuel effect, no noise) so every
    clean lap is identical and the injected penalties are the only thing the
    estimator can find.
    """
    race = make_race(n_drivers=8, deg={"SOFT": 0.0, "HARD": 0.0},
                     fuel_effect=0.0, noise=0.0, seed=14).copy()

    in_mask = race["PitInTime"].notna()
    race.loc[in_mask, "LapTime"] += pd.to_timedelta(4.0, unit="s")

    out_idx = race.index[in_mask] + 1
    out_idx = out_idx[out_idx.isin(race.index)]
    # An all-NaT column infers as datetime64; rebuild it as timedelta.
    race["PitOutTime"] = pd.Series(pd.NaT, index=race.index, dtype="timedelta64[ns]")
    race.loc[out_idx, "PitOutTime"] = pd.to_timedelta(5.0, unit="s")
    race.loc[out_idx, "LapTime"] += pd.to_timedelta(18.0, unit="s")

    loss = strategy.pit_loss(race)
    assert loss["in_lap_s"] == pytest.approx(4.0, abs=0.5)
    assert loss["out_lap_s"] == pytest.approx(18.0, abs=0.5)
    assert loss["pit_loss_s"] == pytest.approx(22.0, abs=1.0)


def test_wrong_fuel_assumption_leaks_into_evolution():
    """Why the fuel sliders exist, and what they cost when set wrong.

    Fuel load is very nearly a linear function of lap number, so any error in
    the assumed fuel effect has the same shape as track evolution and lands
    almost entirely in the evolution term. This is the single largest source
    of systematic error in the model, and it is why the app exposes the fuel
    assumptions as controls instead of burying them.
    """
    race = make_race(evolution_s=0.0, fuel_kg=100.0, seed=20)

    right, _ = degradation.prepare(race, year=2024, total_laps=50, fuel_kg=100.0)
    wrong, _ = degradation.prepare(race, year=2024, total_laps=50, fuel_kg=140.0)

    truth = evolution.fit_evolution(right, total_laps=50)["total_gain_s"]
    biased = evolution.fit_evolution(wrong, total_laps=50)["total_gain_s"]

    assert abs(truth) < 0.25, "correct assumption should find no evolution"
    # A 40% fuel over-estimate invents track evolution that was never there.
    assert abs(biased) > abs(truth) + 0.5


def test_undercut_gain_does_not_charge_the_pit_loss():
    """The correction that makes the calculator right.

    The rival concedes the same pit loss a few laps later, so it cancels.
    A 1.5 s gap must be closable by a strong tyre advantage.
    """
    table = strategy.undercut_gain(
        gap_to_rival_s=1.5, fresh_tyre_advantage_s=0.8, deg_s_per_lap=0.1)
    assert strategy.breakeven_lap(table) is not None
    assert strategy.breakeven_lap(table) <= 4


def test_undercut_fails_against_a_large_gap():
    table = strategy.undercut_gain(
        gap_to_rival_s=20.0, fresh_tyre_advantage_s=0.5, deg_s_per_lap=0.1)
    assert strategy.breakeven_lap(table) is None


def test_undercut_gain_is_monotonic_and_saturates():
    """The advantage decays to zero; it never reverses into a loss."""
    table = strategy.undercut_gain(
        gap_to_rival_s=1.0, fresh_tyre_advantage_s=1.0, deg_s_per_lap=0.2,
        max_laps=20)
    assert table["cumulative_gain_s"].is_monotonic_increasing
    assert (table["per_lap_gain_s"] >= 0).all()
    assert table["per_lap_gain_s"].iloc[-1] == 0.0


def test_gap_evolution_leader_is_always_zero():
    race = make_race(n_drivers=5, seed=15)
    gaps = strategy.gap_evolution(race)
    per_lap_min = gaps.groupby("LapNumber")["gap_s"].min()
    assert np.allclose(per_lap_min, 0.0)
    assert (gaps["gap_s"] >= -1e-9).all()


def test_head_to_head_delta_matches_the_two_lap_times():
    race = make_race(n_drivers=4, total_laps=30, seed=21)
    h2h = strategy.head_to_head(race, "D00", "D01")

    assert not h2h.empty
    assert np.allclose(h2h["delta_s"], h2h["LapTime_s_b"] - h2h["LapTime_s_a"])
    # The running total is exactly the deltas accumulated: the bottom panel of
    # the chart must not drift away from the bars drawn above it.
    assert np.isclose(h2h["cumulative_s"].iloc[-1], h2h["delta_s"].sum())


def test_head_to_head_scores_no_delta_for_a_lap_only_one_driver_ran():
    """A retirement must not read as the other driver gaining time.

    The cumulative gap is the number a reader trusts. If laps the rival never
    ran silently counted, a DNF would look like dominant pace.
    """
    race = make_race(n_drivers=2, total_laps=20, seed=3)
    retired = race[~((race["Driver"] == "D01") & (race["LapNumber"] > 12))]

    h2h = strategy.head_to_head(retired, "D00", "D01")

    both_ran = h2h[h2h["LapNumber"] <= 12]
    after = h2h[h2h["LapNumber"] > 12]
    assert both_ran["delta_s"].notna().all()
    assert after["delta_s"].isna().all()
    # Up to the retirement the running total is the sum of the scored laps.
    assert np.isclose(both_ran["cumulative_s"].iloc[-1], both_ran["delta_s"].sum())
    # After it the total is unknown, not unchanged. Carrying the last value
    # forward would state that neither driver gained on laps nobody measured.
    assert after["cumulative_s"].isna().all()
