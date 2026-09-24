"""Tests for disruption/winter_storm.py's T32 companion-raster glue."""

from __future__ import annotations

import pandas as pd

from resiflow.disruption.winter_storm import _no_damage_level


def test_no_damage_level_accepts_three_args_matching_shared_categorical_fn_interface() -> None:
    road_classification = pd.Series(["primary", "residential"])
    intensity = pd.Series([12.0, 28.0])
    road_label = pd.Series(["road", "road"])
    result = _no_damage_level(road_classification, intensity, road_label)
    assert list(result) == ["no", "no"]
