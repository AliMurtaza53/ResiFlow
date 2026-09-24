"""Landslide categorical fragility: displacement (mm) -> damage level.

Uses the SAME real HAZUS PGD fragility that prices direct cost
(hazards/hazus_bridge.py), replacing the old flat-threshold placeholder
(25/75/150/300mm major, 15/50/100/200mm minor). Those thresholds were well
below HAZUS's own real medians (304.8/609.6/1524mm for major roads, Table
7-5) -- the placeholder was closing/slowing links far more aggressively than
the real fragility pricing the same event would ever justify. See
docs/HAZARD_TABLE_INTEGRATION_RUNBOOK.md.

Roads use hazus_bridge.road_pgd_damage_level() (Table 7-5, exact same curve
as direct cost). Bridges use hazus_bridge.bridge_pgd_damage_level_default()
(Table 7-7's shared base medians, no per-bridge geometry correction -- full
NBI attributes aren't available at this disruption-stage call site; Script
3's real bridge cost computation still applies the fully geometry-corrected
fragility separately). Zero new data needed for either branch -- landslide's
PGD is already real (derived from a paired real earthquake's PGA + the real
national n10 susceptibility layer).
"""

from __future__ import annotations

import pandas as pd

from resiflow.hazards.hazus_bridge import bridge_pgd_damage_level_default, road_pgd_damage_level

_MM_PER_INCH = 25.4


def compute_damage_levels_vectorized(
    road_classification: pd.Series,
    displacement_mm: pd.Series,
    road_label: pd.Series | None = None,
) -> pd.Series:
    depth_mm = pd.to_numeric(displacement_mm, errors="coerce").fillna(0.0)
    pgd_in = depth_mm / _MM_PER_INCH
    rc = road_classification.fillna("").astype(str)
    if road_label is None:
        is_bridge = pd.Series(False, index=depth_mm.index)
    else:
        is_bridge = road_label.reindex(depth_mm.index).fillna("").astype(str).str.strip().str.lower().eq("bridge")

    levels = [
        bridge_pgd_damage_level_default(pgd_in.loc[i])
        if is_bridge.loc[i]
        else road_pgd_damage_level(road_classification=rc.loc[i], pgd_in=pgd_in.loc[i])
        for i in depth_mm.index
    ]
    return pd.Series(levels, index=depth_mm.index, dtype=object)
