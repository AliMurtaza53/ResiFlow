"""Earthquake categorical fragility at the PGA raster pass.

ROADS: HAZUS publishes NO ground-shaking fragility for ordinary roads
(Table 7-5 is PGD-only). This pass therefore always returns ``\"no\"`` for
roads — correct per HAZUS, not a gap.

BRIDGES: damage_level from ground shaking must use Sa(1.0s) Table 7-6, not
PGA. Sa arrives on a *separate* raster pass (``psa1p0_g``) that merges with
the PGA pass in ``pipeline_intensity`` *after* this function runs. Feeding
PGA into Table 7-6 would mix intensity measures. Bridge levels are therefore
assigned later in ``features_with_earthquake`` via
``hazus_bridge.bridge_sa_damage_level_default(psa1p0_g)`` once both passes
have merged and Sa is aggregated to the link. This PGA-pass categorical
always returns ``\"no\"`` for bridges too (placeholder PGA thresholds removed).
"""

from __future__ import annotations

import pandas as pd


def compute_damage_levels_vectorized(
    road_classification: pd.Series,
    pga_g: pd.Series,
    road_label: pd.Series | None = None,
) -> pd.Series:
    """PGA-pass categorical: always ``no`` (bridge Sa override happens post-merge)."""
    # Signature kept for intersections_with_intensity / road_label interface parity.
    _ = (road_classification, pga_g, road_label)
    return pd.Series(["no"] * len(pga_g), index=pga_g.index, dtype=object)
