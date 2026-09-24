"""Earthquake categorical fragility: PGA (g) -> damage level.

ROADS: HAZUS publishes NO ground-shaking fragility for ordinary roads --
Table 7-5 is PGD/ground-failure-only (see hazards/hazus_bridge.py's
road_direct_cost_usd docstring). The previous flat PGA-threshold placeholder
(0.10-0.45g) had no real HAZUS basis for roads at all. Correct behavior,
until a liquefaction-PGD layer exists (docs/HAZARD_TABLE_INTEGRATION_
RUNBOOK.md Track A): roads report "no" damage from ground shaking alone --
this is accurate per HAZUS, not a gap. Removing the placeholder rather than
keeping an arbitrary substitute is the harmonization fix for roads.

BRIDGES: still the placeholder PGA thresholds below, NOT yet replaced with
the real Sa(1.0s) HAZUS Table 7-6 fragility that prices bridge direct cost.
Sa(1.0s) is a separate raster pass (disruption/earthquake.py's
sa1p0_companion), not the same intensity measure as PGA and not available at
this generic disruption-stage call site (which only receives PGA) -- using
PGA as an Sa(1.0s) proxy here would be a real methodological error (mixing
intensity measures), not a documented simplification like landslide's
geometry-correction shortcut. Threading Sa(1.0s) through this call site is a
real, tracked follow-up, not done in this pass.
"""

from __future__ import annotations

import pandas as pd

# PLACEHOLDER — confirm with advisor: PGA thresholds (g) for FAF-style road
# classes. Kept ONLY for bridges now (see module docstring) -- roads no
# longer use this at all.
_MAJOR_PGA = (0.15, 0.25, 0.35, 0.45)
_MINOR_PGA = (0.10, 0.18, 0.28, 0.38)


def _level_from_pga(pga: float, *, major: bool) -> str:
    thresholds = _MAJOR_PGA if major else _MINOR_PGA
    if pga <= 0:
        return "no"
    if pga < thresholds[0]:
        return "no"
    if pga < thresholds[1]:
        return "minor"
    if pga < thresholds[2]:
        return "moderate"
    if pga < thresholds[3]:
        return "extensive"
    return "severe"


def compute_damage_levels_vectorized(
    road_classification: pd.Series,
    pga_g: pd.Series,
    road_label: pd.Series | None = None,
) -> pd.Series:
    pga = pd.to_numeric(pga_g, errors="coerce").fillna(0.0)
    rc = road_classification.fillna("").astype(str).str.strip().str.lower()
    major = rc.isin({"motorway", "motorway_link", "trunk", "primary", "secondary", "tertiary"})

    if road_label is None:
        is_bridge = pd.Series(False, index=pga.index)
    else:
        is_bridge = road_label.reindex(pga.index).fillna("").astype(str).str.strip().str.lower().eq("bridge")

    levels = [
        _level_from_pga(float(v), major=bool(m)) if bridge else "no"
        for v, m, bridge in zip(pga, major, is_bridge)
    ]
    return pd.Series(levels, index=pga.index, dtype=object)
