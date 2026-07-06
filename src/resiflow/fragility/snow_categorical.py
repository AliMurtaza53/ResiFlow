"""Snow categorical fragility: snowfall depth (mm) to damage_level."""

from __future__ import annotations

import pandas as pd


def compute_damage_level_on_snow(
    road_classification: str,
    snow_depth_mm: float,
) -> str:
    """Map snow depth (mm) to recovery damage level (FAF/US roads)."""
    depth = float(snow_depth_mm or 0.0)
    rc = ("" if road_classification is None else str(road_classification)).strip().lower()
    major = rc in {"motorway", "motorway_link", "trunk", "primary", "secondary"}

    if depth <= 0:
        return "no"
    if major:
        if depth < 75:
            return "no"
        if depth < 150:
            return "minor"
        if depth < 300:
            return "moderate"
        if depth < 600:
            return "extensive"
        return "severe"
    if depth < 50:
        return "no"
    if depth < 100:
        return "minor"
    if depth < 200:
        return "moderate"
    if depth < 400:
        return "extensive"
    return "severe"


def compute_damage_levels_vectorized(
    road_classification: pd.Series,
    snow_depth_mm: pd.Series,
) -> pd.Series:
    """Vectorized snow damage levels."""
    depth = pd.to_numeric(snow_depth_mm, errors="coerce").fillna(0.0)
    rc_lower = road_classification.fillna("").astype(str).str.strip().str.lower()
    major = rc_lower.isin({"motorway", "motorway_link", "trunk", "primary", "secondary"})
    result = pd.Series("no", index=depth.index, dtype=object)

    result.loc[major & (depth >= 75) & (depth < 150)] = "minor"
    result.loc[major & (depth >= 150) & (depth < 300)] = "moderate"
    result.loc[major & (depth >= 300) & (depth < 600)] = "extensive"
    result.loc[major & (depth >= 600)] = "severe"

    minor = ~major
    result.loc[minor & (depth >= 50) & (depth < 100)] = "minor"
    result.loc[minor & (depth >= 100) & (depth < 200)] = "moderate"
    result.loc[minor & (depth >= 200) & (depth < 400)] = "extensive"
    result.loc[minor & (depth >= 400)] = "severe"
    return result
