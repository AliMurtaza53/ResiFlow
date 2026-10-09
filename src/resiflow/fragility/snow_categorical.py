"""Snow categorical fragility: snowfall depth (mm) to damage_level.

Delegates to the single shared winter classification
(``winter_storm_categorical``: VDOT depth ladder, gated duration/temperature
escalators). The snow testbed carries no duration/temperature rasters, so it
gets the depth-only base tier -- no escalation. This replaces the separate
75/150/300/600 mm (major) and 50/100/200/400 mm (minor) thresholds that used to
live here and disagreed with the winter_storm placeholders.
"""

from __future__ import annotations

import pandas as pd

from resiflow.fragility.winter_storm_categorical import compute_damage_levels_vectorized as _shared_levels


def compute_damage_level_on_snow(
    road_classification: str,  # noqa: ARG001 -- kept for the historical signature; the ladder is class-independent
    snow_depth_mm: float,
) -> str:
    """Map snow depth (mm) to a damage level (depth-only base tier)."""
    depth = pd.Series([float(snow_depth_mm or 0.0)])
    return str(_shared_levels(pd.Series([road_classification]), depth).iloc[0])


def compute_damage_levels_vectorized(
    road_classification: pd.Series,
    snow_depth_mm: pd.Series,
) -> pd.Series:
    """Vectorized snow damage levels (depth-only base tier)."""
    return _shared_levels(road_classification, snow_depth_mm)
