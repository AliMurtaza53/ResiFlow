"""Winter storm categorical fragility (ice loading / regional snow — not inundation)."""

from __future__ import annotations

import pandas as pd

# PLACEHOLDER — confirm with advisor: separate from snow depth curve.
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
    ice_mm: pd.Series,
) -> pd.Series:
    depth = pd.to_numeric(ice_mm, errors="coerce").fillna(0.0)
    rc = road_classification.fillna("").astype(str).str.strip().str.lower()
    major = rc.isin({"motorway", "motorway_link", "trunk", "primary", "secondary", "tertiary"})
    return pd.Series(
        [_level_from_mm(float(v), major=bool(m)) for v, m in zip(depth, major)],
        index=depth.index,
        dtype=object,
    )
