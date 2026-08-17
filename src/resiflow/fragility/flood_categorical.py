"""Flood categorical fragility: intensity to damage_level (FAF/US classifications)."""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from resiflow.parameters import get_parameter


def _damage_threshold_scale() -> float:
    """SA seam: one multiplier over every depth threshold below (default 1.0).

    Read at call time (the parameter loader is cached) so per-run overrides
    via RESIFLOW_PARAM_OVERRIDES take effect without re-importing the module.
    Multiplying by the default 1.0 is exact for floats, so a no-override run
    classifies identically.
    """
    return float(get_parameter("vulnerability", "damage_threshold_scale", 1.0))


def _use_table_damage_thresholds() -> bool:
    """Flag: read damage-level depth thresholds from the T20 table (default off)."""
    return bool(get_parameter("vulnerability", "use_table_damage_thresholds", False))


# Damage levels in ascending order (thresholds are "level begins at" depths).
_TABLE_LEVELS = ("minor", "moderate", "extensive", "severe")
_TABLE_LEVEL_COLUMNS = {
    "minor": "minor_from_cm",
    "moderate": "moderate_from_cm",
    "extensive": "extensive_from_cm",
    "severe": "severe_from_cm",
}


def _thresholds_from_table(flood_type: str) -> dict[bool, dict[str, float]]:
    """{is_major: {level: begins_at_cm}} for one flood type from the T20 table.

    Only CURRENT rows are served; the loader has already dropped the coastal
    PLACEHOLDER_DO_NOT_USE rows, so asking for coastal fails loud here. Levels
    marked n/a in the table (surface caps at moderate) are simply absent.
    """
    from resiflow.tables import load_table

    table = load_table(
        get_parameter(
            "vulnerability", "damage_threshold_table", "T20_damage_level_depth_thresholds"
        )
    )
    rows = table.loc[
        (table["flood_type"] == flood_type)
        & (table["status"].astype(str).str.startswith("CURRENT"))
    ]
    if rows.empty:
        raise ValueError(
            f"No usable damage-threshold rows for flood type {flood_type!r} in "
            "the T20 table (coastal rows are placeholders and are never loaded)."
        )
    out: dict[bool, dict[str, float]] = {}
    for _, row in rows.iterrows():
        is_major = str(row["road_class"]).strip().lower().startswith("major")
        thresholds: dict[str, float] = {}
        for level in _TABLE_LEVELS:
            raw = pd.to_numeric(pd.Series([row[_TABLE_LEVEL_COLUMNS[level]]]), errors="coerce").iloc[0]
            if pd.notna(raw):
                thresholds[level] = float(raw)
        out[is_major] = thresholds
    if set(out) != {True, False}:
        raise ValueError(
            f"T20 table must provide both major and minor rows for {flood_type!r}."
        )
    return out


def _classify_from_thresholds(depth_cm: float, thresholds: dict[str, float], s: float) -> str:
    level_out = "no"
    for level in _TABLE_LEVELS:
        if level in thresholds and depth_cm >= thresholds[level] * s:
            level_out = level
    return level_out


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

    s = _damage_threshold_scale()
    major = rc_lower in MAJOR_FAF
    if _use_table_damage_thresholds():
        thresholds = _thresholds_from_table(fldType)[major]
        return _classify_from_thresholds(depth, thresholds, s)
    if fldType == "surface":
        if major:
            if depth < 200 * s:
                return "no"
            if depth < 600 * s:
                return "minor"
            return "moderate"
        if depth < 50 * s:
            return "no"
        if depth < 600 * s:
            return "minor"
        return "moderate"

    if fldType == "river":
        if major:
            if depth < 50 * s:
                return "no"
            if depth < 100 * s:
                return "minor"
            if depth < 200 * s:
                return "moderate"
            if depth < 600 * s:
                return "extensive"
            return "severe"
        if depth <= 0:
            return "no"
        if depth < 50 * s:
            return "minor"
        if depth < 200 * s:
            return "moderate"
        if depth < 600 * s:
            return "extensive"
        return "severe"

    if fldType == "coastal":
        # PLACEHOLDER — confirm with advisor: surge/velocity-style thresholds (cm).
        if major:
            if depth < 40 * s:
                return "no"
            if depth < 90 * s:
                return "minor"
            if depth < 180 * s:
                return "moderate"
            if depth < 500 * s:
                return "extensive"
            return "severe"
        if depth < 30 * s:
            return "no"
        if depth < 80 * s:
            return "minor"
        if depth < 150 * s:
            return "moderate"
        if depth < 400 * s:
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

    s = _damage_threshold_scale()
    if _use_table_damage_thresholds():
        for is_major, thresholds in _thresholds_from_table(fldType).items():
            mask = faf_mask & (major_faf if is_major else ~major_faf)
            for level in _TABLE_LEVELS:
                if level in thresholds:
                    result.loc[mask & (depth_cm >= thresholds[level] * s)] = level
        return result
    if fldType == "surface":
        faf_major_mask = faf_mask & major_faf
        faf_minor_mask = faf_mask & ~major_faf
        result.loc[faf_major_mask & (depth_cm < 200 * s)] = "no"
        result.loc[faf_major_mask & (depth_cm >= 200 * s) & (depth_cm < 600 * s)] = "minor"
        result.loc[faf_major_mask & (depth_cm >= 600 * s)] = "moderate"
        result.loc[faf_minor_mask & (depth_cm < 50 * s)] = "no"
        result.loc[faf_minor_mask & (depth_cm >= 50 * s) & (depth_cm < 600 * s)] = "minor"
        result.loc[faf_minor_mask & (depth_cm >= 600 * s)] = "moderate"
    elif fldType == "river":
        faf_major_mask = faf_mask & major_faf
        faf_minor_mask = faf_mask & ~major_faf
        result.loc[faf_major_mask & (depth_cm < 50 * s)] = "no"
        result.loc[faf_major_mask & (depth_cm >= 50 * s) & (depth_cm < 100 * s)] = "minor"
        result.loc[faf_major_mask & (depth_cm >= 100 * s) & (depth_cm < 200 * s)] = "moderate"
        result.loc[faf_major_mask & (depth_cm >= 200 * s) & (depth_cm < 600 * s)] = "extensive"
        result.loc[faf_major_mask & (depth_cm >= 600 * s)] = "severe"
        result.loc[faf_minor_mask & (depth_cm <= 0)] = "no"
        result.loc[faf_minor_mask & (depth_cm > 0) & (depth_cm < 50 * s)] = "minor"
        result.loc[faf_minor_mask & (depth_cm >= 50 * s) & (depth_cm < 200 * s)] = "moderate"
        result.loc[faf_minor_mask & (depth_cm >= 200 * s) & (depth_cm < 600 * s)] = "extensive"
        result.loc[faf_minor_mask & (depth_cm >= 600 * s)] = "severe"
    elif fldType == "coastal":
        # PLACEHOLDER — confirm with advisor: mirrors scalar coastal thresholds (cm).
        faf_major_mask = faf_mask & major_faf
        faf_minor_mask = faf_mask & ~major_faf
        result.loc[faf_major_mask & (depth_cm < 40 * s)] = "no"
        result.loc[faf_major_mask & (depth_cm >= 40 * s) & (depth_cm < 90 * s)] = "minor"
        result.loc[faf_major_mask & (depth_cm >= 90 * s) & (depth_cm < 180 * s)] = "moderate"
        result.loc[faf_major_mask & (depth_cm >= 180 * s) & (depth_cm < 500 * s)] = "extensive"
        result.loc[faf_major_mask & (depth_cm >= 500 * s)] = "severe"
        result.loc[faf_minor_mask & (depth_cm < 30 * s)] = "no"
        result.loc[faf_minor_mask & (depth_cm >= 30 * s) & (depth_cm < 80 * s)] = "minor"
        result.loc[faf_minor_mask & (depth_cm >= 80 * s) & (depth_cm < 150 * s)] = "moderate"
        result.loc[faf_minor_mask & (depth_cm >= 150 * s) & (depth_cm < 400 * s)] = "extensive"
        result.loc[faf_minor_mask & (depth_cm >= 400 * s)] = "severe"
    else:
        logging.info("Unknown flood type: %s", fldType)

    return result
