"""Earthquake categorical fragility: PGA (g) → damage level."""

from __future__ import annotations

import pandas as pd

# PLACEHOLDER — confirm with advisor: PGA thresholds (g) for FAF-style road classes.
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
) -> pd.Series:
    pga = pd.to_numeric(pga_g, errors="coerce").fillna(0.0)
    rc = road_classification.fillna("").astype(str).str.strip().str.lower()
    major = rc.isin({"motorway", "motorway_link", "trunk", "primary", "secondary", "tertiary"})
    return pd.Series(
        [_level_from_pga(float(v), major=bool(m)) for v, m in zip(pga, major)],
        index=pga.index,
        dtype=object,
    )
