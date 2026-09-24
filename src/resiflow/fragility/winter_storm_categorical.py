"""Winter storm categorical fragility: snow depth (mm) -> damage level.

STILL A PLACEHOLDER (not fixed in this pass) -- unlike earthquake/landslide,
this one is blocked on real data, not just wiring: the flat depth-only
thresholds below can't be replaced with something real until
duration_hours/air_temp_F are intersected per event and a winter-storm-
specific damage-level definition is decided (see
docs/HAZARD_TABLE_INTEGRATION_RUNBOOK.md Track B Step 2) -- T32-T35's real
cost/recovery model is calibrated on depth+duration+temperature together, so
a depth-only threshold here would just be trading one placeholder for
another. Naming/docstring corrected 2026-09 -- the parameter is snow depth
(the same real winter_storm_mm the caller, disruption/winter_storm.py, also
feeds to the real speed-penalty formula in fragility/winter_storm_
operational.py), not a separate "ice_mm" field as an earlier version of this
docstring implied. road_label is accepted (for interface parity with
earthquake/landslide's categorical_fn) but not yet used.
"""

from __future__ import annotations

import pandas as pd

# PLACEHOLDER — confirm with advisor: depth-only, no duration/temperature.
_MAJOR_MM = (40.0, 80.0, 150.0, 250.0)
_MINOR_MM = (25.0, 60.0, 120.0, 200.0)


def _level_from_mm(depth_mm: float, *, major: bool) -> str:
    thresholds = _MAJOR_MM if major else _MINOR_MM
    if depth_mm <= 0:
        return "no"
    if depth_mm < thresholds[0]:
        return "no"
    if depth_mm < thresholds[1]:
        return "minor"
    if depth_mm < thresholds[2]:
        return "moderate"
    if depth_mm < thresholds[3]:
        return "extensive"
    return "severe"


def compute_damage_levels_vectorized(
    road_classification: pd.Series,
    snow_depth_mm: pd.Series,
    road_label: pd.Series | None = None,  # noqa: ARG001 -- accepted for interface parity, not yet used
) -> pd.Series:
    depth = pd.to_numeric(snow_depth_mm, errors="coerce").fillna(0.0)
    rc = road_classification.fillna("").astype(str).str.strip().str.lower()
    major = rc.isin({"motorway", "motorway_link", "trunk", "primary", "secondary", "tertiary"})
    return pd.Series(
        [_level_from_mm(float(v), major=bool(m)) for v, m in zip(depth, major)],
        index=depth.index,
        dtype=object,
    )
