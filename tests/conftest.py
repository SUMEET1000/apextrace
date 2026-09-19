"""Synthetic telemetry fixtures.

Every unit test runs against generated data rather than the real dataset, so
the suite is fast, deterministic, and needs no network. Tests that touch real
data live in tests/test_integration.py and skip when the dataset is absent.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pitwall.config import POSITION_UNITS_PER_M  # noqa: E402


def _radius_units(lap_length: float) -> float:
    """Radius of a circular circuit of ``lap_length`` metres, in position units."""
    return lap_length / (2 * np.pi) * POSITION_UNITS_PER_M


def make_lap(
    *,
    lap_length: float = 5000.0,
    n_raw: int = 900,
    corner_positions: tuple[float, ...] = (1000.0, 2500.0, 4000.0),
    corner_speed: float = 90.0,
    top_speed: float = 320.0,
    speed_scale: float = 1.0,
    seed: int = 0,
) -> pd.DataFrame:
    """Build a physically plausible raw telemetry lap.

    Speed dips to ``corner_speed`` at each corner and rises to ``top_speed``
    between them. ``speed_scale`` uniformly scales the whole profile, which
    makes a slower-but-identically-shaped lap for delta-time tests.
    """
    rng = np.random.default_rng(seed)
    d = np.sort(rng.uniform(0, lap_length, n_raw - 2))
    d = np.concatenate([[0.0], d, [lap_length]])

    speed = np.full_like(d, top_speed)
    for c in corner_positions:
        # Gaussian speed well centred on each corner.
        speed = np.minimum(
            speed,
            corner_speed + (top_speed - corner_speed) * (1 - np.exp(-((d - c) ** 2) / (2 * 220.0 ** 2)))
        )
    speed *= speed_scale

    # Integrate dt = dd / v to get a time axis consistent with the speed trace.
    v_ms = np.clip(speed, 1.0, None) / 3.6
    dd = np.diff(d, prepend=d[0])
    t = np.cumsum(dd / np.clip(v_ms, 1e-6, None))

    # Brake where the car is decelerating; throttle inversely related.
    dv = np.gradient(speed, d)
    brake = dv < -0.05
    throttle = np.clip(100 * (1 + dv / np.abs(dv).max()), 0, 100)
    throttle[brake] = 0.0

    return pd.DataFrame({
        "Distance": d,
        "Time": pd.to_timedelta(t, unit="s"),
        "Speed": speed,
        "Throttle": throttle,
        "RPM": 3000 + speed * 30,
        "Brake": brake,
        "nGear": np.clip((speed / 40).astype(int), 1, 8),
        "DRS": np.where(speed > 300, 12, 0),
        # A circle of the right circumference, on FastF1's own coordinate
        # scale: X/Y are tenths of a metre, so an offset in metres only means
        # what it says after dividing by config.POSITION_UNITS_PER_M. A fixed
        # 1000-unit radius put the fixture at 1.26 units per metre and hid
        # exactly that conversion.
        "X": np.cos(2 * np.pi * d / lap_length) * _radius_units(lap_length),
        "Y": np.sin(2 * np.pi * d / lap_length) * _radius_units(lap_length),
        "Z": np.zeros_like(d),
    })


@pytest.fixture
def raw_lap() -> pd.DataFrame:
    return make_lap()


@pytest.fixture
def corners_frame() -> pd.DataFrame:
    return pd.DataFrame({
        "Number": [1, 2, 3],
        "Letter": ["", "", ""],
        "CornerLabel": ["1", "2", "3"],
        "Distance": [1000.0, 2500.0, 4000.0],
        "X": [0.0, 0.0, 0.0],
        "Y": [0.0, 0.0, 0.0],
    })
