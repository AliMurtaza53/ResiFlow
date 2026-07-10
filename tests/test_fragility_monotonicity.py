"""Fragility curve monotonicity and boundary tests for multihazard extensions."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from resiflow.fragility.earthquake_categorical import compute_damage_levels_vectorized
from resiflow.fragility.flood_categorical import compute_damage_level_on_flooded_roads
from resiflow.fragility.landslide_categorical import compute_damage_levels_vectorized as landslide_levels
from resiflow.fragility.snow_categorical import compute_damage_levels_vectorized as snow_levels
from resiflow.fragility.winter_storm_categorical import compute_damage_levels_vectorized as winter_levels

_LEVEL_ORDER = {"no": 0, "minor": 1, "moderate": 2, "extensive": 3, "severe": 4}


def _level_rank(series: pd.Series) -> pd.Series:
    return series.map(_LEVEL_ORDER).fillna(0).astype(int)


def test_flood_river_edr_monotonic() -> None:
    depths_cm = np.linspace(0, 300, 50)
    prev = -1
    for depth_cm in depths_cm:
        level = compute_damage_level_on_flooded_roads(
            "river", "tertiary", False, "road", depth_cm / 100.0
        )
        rank = _LEVEL_ORDER[level]
        assert rank >= prev
        prev = rank
    assert compute_damage_level_on_flooded_roads("river", "tertiary", False, "road", 0.0) == "no"


def test_earthquake_edr_monotonic() -> None:
    pga = pd.Series(np.linspace(0, 0.6, 40))
    rc = pd.Series(["tertiary"] * len(pga))
    ranks = _level_rank(compute_damage_levels_vectorized(rc, pga))
    assert ranks.is_monotonic_increasing
    assert ranks.iloc[0] == 0


def test_landslide_edr_monotonic() -> None:
    mm = pd.Series(np.linspace(0, 400, 40))
    rc = pd.Series(["local"] * len(mm))
    ranks = _level_rank(landslide_levels(rc, mm))
    assert ranks.is_monotonic_increasing
    assert ranks.iloc[0] == 0


def test_winter_storm_edr_monotonic() -> None:
    mm = pd.Series(np.linspace(0, 300, 40))
    rc = pd.Series(["tertiary"] * len(mm))
    ranks = _level_rank(winter_levels(rc, mm))
    assert ranks.is_monotonic_increasing
    assert ranks.iloc[0] == 0


def test_snow_edr_monotonic() -> None:
    mm = pd.Series(np.linspace(0, 500, 40))
    rc = pd.Series(["tertiary"] * len(mm))
    ranks = _level_rank(snow_levels(rc, mm))
    assert ranks.is_monotonic_increasing
    assert ranks.iloc[0] == 0
