"""Flood categorical fragility: intensity to damage_level (FAF/US classifications)."""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

FAF_US_CLASSES = frozenset(
    {
        "motorway",
        "motorway_link",
        "trunk",
        "primary",
        "secondary",
        "tertiary",
        "service",
        "unclassified",
        "local",
    }
)
MAJOR_FAF = frozenset({"motorway", "motorway_link", "trunk", "primary", "secondary"})


def compute_damage_level_on_flooded_roads(
    fldType: str,
    road_classification: str,
    trunk_road: str,
    road_label: str,
    fldDepth: float,
) -> str:
    """Determine categorical damage for FAF/US road classes from flood depth (m)."""
    if fldType == "flood":
        fldType = "river"
    depth = float(fldDepth or 0.0) * 100.0  # cm
    rc_lower = ("" if road_classification is None else str(road_classification)).strip().lower()
    if rc_lower not in FAF_US_CLASSES:
        return "no"

    major = rc_lower in MAJOR_FAF
    if fldType == "surface":
        if major:
            if depth < 200:
                return "no"
            if depth < 600:
                return "minor"
            return "moderate"
        if depth < 50:
            return "no"
        if depth < 600:
            return "minor"
        return "moderate"

    if fldType == "river":
        if major:
            if depth < 50:
                return "no"
            if depth < 100:
                return "minor"
            if depth < 200:
                return "moderate"
            if depth < 600:
                return "extensive"
            return "severe"
        if depth <= 0:
            return "no"
        if depth < 50:
            return "minor"
        if depth < 200:
            return "moderate"
        if depth < 600:
            return "extensive"
        return "severe"

    if fldType == "coastal":
        # PLACEHOLDER — confirm with advisor: surge/velocity-style thresholds (cm).
        if major:
            if depth < 40:
                return "no"
            if depth < 90:
                return "minor"
            if depth < 180:
                return "moderate"
            if depth < 500:
                return "extensive"
            return "severe"
        if depth < 30:
            return "no"
        if depth < 80:
            return "minor"
        if depth < 150:
            return "moderate"
        if depth < 400:
            return "extensive"
        return "severe"

    logging.info("Unknown flood type: %s", fldType)
    return "no"


def compute_damage_levels_on_flooded_roads_vectorized(
    fldType: str,
    road_classification: pd.Series,
    trunk_road: pd.Series,
    road_label: pd.Series,
    fldDepth: pd.Series,
) -> pd.Series:
    """Vectorized FAF/US flood categorical damage."""
    if fldType == "flood":
        fldType = "river"
    depth_cm = pd.to_numeric(fldDepth, errors="coerce").fillna(0.0) * 100.0
    rc_lower = road_classification.fillna("").astype(str).str.strip().str.lower()
    faf_mask = rc_lower.isin(FAF_US_CLASSES)
    major_faf = rc_lower.isin(MAJOR_FAF)
    result = pd.Series("no", index=rc_lower.index, dtype=object)

    if fldType == "surface":
        faf_major_mask = faf_mask & major_faf
        faf_minor_mask = faf_mask & ~major_faf
        result.loc[faf_major_mask & (depth_cm < 200)] = "no"
        result.loc[faf_major_mask & (depth_cm >= 200) & (depth_cm < 600)] = "minor"
        result.loc[faf_major_mask & (depth_cm >= 600)] = "moderate"
        result.loc[faf_minor_mask & (depth_cm < 50)] = "no"
        result.loc[faf_minor_mask & (depth_cm >= 50) & (depth_cm < 600)] = "minor"
        result.loc[faf_minor_mask & (depth_cm >= 600)] = "moderate"
    elif fldType == "river":
        faf_major_mask = faf_mask & major_faf
        faf_minor_mask = faf_mask & ~major_faf
        result.loc[faf_major_mask & (depth_cm < 50)] = "no"
        result.loc[faf_major_mask & (depth_cm >= 50) & (depth_cm < 100)] = "minor"
        result.loc[faf_major_mask & (depth_cm >= 100) & (depth_cm < 200)] = "moderate"
        result.loc[faf_major_mask & (depth_cm >= 200) & (depth_cm < 600)] = "extensive"
        result.loc[faf_major_mask & (depth_cm >= 600)] = "severe"
        result.loc[faf_minor_mask & (depth_cm <= 0)] = "no"
        result.loc[faf_minor_mask & (depth_cm > 0) & (depth_cm < 50)] = "minor"
        result.loc[faf_minor_mask & (depth_cm >= 50) & (depth_cm < 200)] = "moderate"
        result.loc[faf_minor_mask & (depth_cm >= 200) & (depth_cm < 600)] = "extensive"
        result.loc[faf_minor_mask & (depth_cm >= 600)] = "severe"
    else:
        logging.info("Unknown flood type: %s", fldType)

    return result
