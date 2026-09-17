"""Tests for the storage-layer helpers that views depend on.

``get_lap`` is the one with teeth: Corner Analysis calls it with ``None`` and
renders whatever lap it lands on, so its default has to be both sensible and
total. A crash here blanks the flagship view.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from pitwall.store import get_lap


def _telemetry(rows: list[tuple[str, float, float]]) -> pd.DataFrame:
    """A decoded-telemetry stand-in: one row per lap is enough for get_lap."""
    return pd.DataFrame(
        [{"Driver": d, "LapNumber": n, "LapTime_s": t, "Speed": 200.0}
         for d, n, t in rows]
    )


def test_defaults_to_the_drivers_fastest_lap():
    tel = _telemetry([("VER", 1.0, 95.0), ("VER", 2.0, 91.5), ("VER", 3.0, 93.0)])
    assert get_lap(tel, "VER")["LapNumber"].iloc[0] == 2.0


def test_an_explicit_lap_number_wins_over_the_default():
    tel = _telemetry([("VER", 1.0, 95.0), ("VER", 2.0, 91.5)])
    assert get_lap(tel, "VER", 1.0)["LapNumber"].iloc[0] == 1.0


def test_an_unknown_driver_returns_empty_rather_than_raising():
    assert get_lap(_telemetry([("VER", 1.0, 95.0)]), "HAM").empty


def test_a_driver_whose_every_lap_is_untimed_still_returns_a_lap():
    """The 2026/06_R crash: VER retired on lap 1, so his only stored lap is a
    ``start`` kind with no LapTime. ``idxmin`` on an all-NaN series returns NaN
    and the old ``.loc`` lookup raised ``KeyError: nan``, blanking the page for
    a driver who demonstrably has telemetry."""
    tel = _telemetry([("VER", 1.0, np.nan)])
    lap = get_lap(tel, "VER")
    assert len(lap) == 1
    assert lap["LapNumber"].iloc[0] == 1.0


def test_untimed_fallback_is_deterministic_and_picks_the_earliest_lap():
    tel = _telemetry([("VER", 7.0, np.nan), ("VER", 3.0, np.nan), ("VER", 5.0, np.nan)])
    assert get_lap(tel, "VER")["LapNumber"].iloc[0] == 3.0


def test_a_timed_lap_is_preferred_even_when_untimed_laps_come_first():
    """Mixed case: the fastest *timed* lap still wins, so the fallback cannot
    quietly displace the normal default."""
    tel = _telemetry([("VER", 1.0, np.nan), ("VER", 2.0, 92.0), ("VER", 3.0, np.nan)])
    assert get_lap(tel, "VER")["LapNumber"].iloc[0] == 2.0


def test_one_drivers_untimed_laps_do_not_affect_another():
    tel = _telemetry([("VER", 1.0, np.nan), ("NOR", 1.0, 94.0), ("NOR", 2.0, 90.0)])
    assert get_lap(tel, "VER")["LapNumber"].iloc[0] == 1.0
    assert get_lap(tel, "NOR")["LapNumber"].iloc[0] == 2.0
