"""Earthquake operational fragility: damage state → max_speed (step function)."""

from __future__ import annotations

import pandas as pd

# PLACEHOLDER — confirm with advisor: speed factors by damage state.
_SPEED_FACTOR = {
    "no": 1.0,
    "minor": 0.85,
    "moderate": 0.5,
    "extensive": 0.0,
    "severe": 0.0,
}


def apply_max_speed_to_links(
    road_links: pd.DataFrame,
    *,
    damage_col: str = "damage_level_max",
    free_flow_col: str = "free_flow_speeds",
    out_col: str = "max_speed",
) -> pd.DataFrame:
    out = road_links.copy()
    if free_flow_col not in out.columns:
        out[free_flow_col] = 50.0
    free_flow = pd.to_numeric(out[free_flow_col], errors="coerce").fillna(50.0)
    levels = out.get(damage_col, "no").fillna("no").astype(str).str.lower()
    factors = levels.map(_SPEED_FACTOR).fillna(1.0)
    out[out_col] = free_flow * factors
    return out
