"""Tests for disruption/earthquake.py's raster-intersection glue.

Regression coverage for a bug introduced 2026-09-23: intensity_hazard.py's
shared categorical_fn call site was changed to pass 3 args (road_classification,
intensity, road_label), but earthquake.py's own placeholder categorical_fn
for the Sa(1.0s)/liquefaction companion passes (_no_damage_level) still only
accepted 2 -- a TypeError on every earthquake scenario with sa1p0_companion=True
(Mineral, New Madrid, Cascadia all have it), never caught by the existing
suite because no test exercised that raster-intersection call path directly.
"""

from __future__ import annotations

import pandas as pd

from resiflow.disruption.earthquake import _no_damage_level


def test_no_damage_level_accepts_three_args_matching_shared_categorical_fn_interface() -> None:
    road_classification = pd.Series(["primary", "motorway"])
    intensity = pd.Series([0.3, 0.8])
    road_label = pd.Series(["road", "bridge"])
    result = _no_damage_level(road_classification, intensity, road_label)
    assert list(result) == ["no", "no"]
