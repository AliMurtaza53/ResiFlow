"""Flood categorical fragility: intensity to damage_level (FAF/US classifications)."""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from resiflow.hpms_fclass import flood_road_class_sophistication
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


def _load_t20_table() -> pd.DataFrame:
    from resiflow.tables import load_table

    return load_table(
        get_parameter(
            "vulnerability", "damage_threshold_table", "T20_damage_level_depth_thresholds"
        )
    )


_SOPHISTICATION_CLASSES = frozenset({"sophisticated", "simple", "ordinary"})


def _table_uses_sophistication_scheme(table: pd.DataFrame) -> bool:
    """Which road-class scheme the configured T20 table uses -- auto-detected
    from its own road_class values, so the same use_table_damage_thresholds
    flag + damage_threshold_table parameter select both the behavior and the
    scheme (point damage_threshold_table at the US-candidate file to get the
    van Ginkel/Li sophisticated/simple/ordinary scheme instead of the legacy
    major/minor one -- no separate flag needed)."""
    values = set(table["road_class"].astype(str).str.strip().str.lower())
    return bool(_SOPHISTICATION_CLASSES & values)


def _thresholds_from_table(flood_type: str, table: pd.DataFrame | None = None) -> dict:
    """{road_class_key: {level: begins_at_cm}} for one flood type from the T20 table.

    ``road_class_key`` is ``True``/``False`` (legacy major/minor scheme) or
    ``"sophisticated"``/``"simple"``/``"ordinary"`` (van Ginkel/Li 3-way
    scheme) depending on which table is configured -- see
    _table_uses_sophistication_scheme. Only CURRENT (legacy scheme) or
    CANDIDATE (3-way scheme) rows are served; coastal's placeholder status
    in either table is never auto-loaded, so asking for coastal fails loud
    here (the hardcoded non-table coastal path remains the only coastal
    source -- see its own PLACEHOLDER comment below). Levels marked n/a in
    the table (e.g. surface caps at moderate) are simply absent.
    """
    if table is None:
        table = _load_t20_table()

    if _table_uses_sophistication_scheme(table):
        rows = table.loc[
            (table["flood_type"].astype(str).str.strip() == flood_type)
            & (table["status"].astype(str).str.strip() == "CANDIDATE")
        ]
        if rows.empty:
            raise ValueError(
                f"No usable (status=CANDIDATE) sophistication-scheme threshold rows for "
                f"flood type {flood_type!r} in the T20 table -- coastal's status is "
                "PLACEHOLDER_SUBSTITUTE_RIVER, not CANDIDATE, and is never auto-loaded."
            )
        out: dict[str, dict[str, float]] = {}
        for _, row in rows.iterrows():
            key = str(row["road_class"]).strip().lower()
            thresholds: dict[str, float] = {}
            for level in _TABLE_LEVELS:
                raw = pd.to_numeric(pd.Series([row[_TABLE_LEVEL_COLUMNS[level]]]), errors="coerce").iloc[0]
                if pd.notna(raw):
                    thresholds[level] = float(raw)
            out[key] = thresholds
        missing = _SOPHISTICATION_CLASSES - set(out)
        if missing:
            raise ValueError(f"T20 table missing sophistication-scheme rows {missing} for {flood_type!r}.")
        return out

    rows = table.loc[
        (table["flood_type"] == flood_type)
        & (table["status"].astype(str).str.startswith("CURRENT"))
    ]
    if rows.empty:
        raise ValueError(
            f"No usable damage-threshold rows for flood type {flood_type!r} in "
            "the T20 table (coastal rows are placeholders and are never loaded)."
        )
    out = {}
    for _, row in rows.iterrows():
        is_major = str(row["road_class"]).strip().lower().startswith("major")
        thresholds = {}
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


def _is_major(road_classification: str | None, hpms_fclass) -> bool:
    """Major/minor split: real hpms_fclass (F1-F3 major, F4-F7 minor,
    docs/FLOOD_TABLE_REVIEW.md Section 1) when available; the legacy
    name-based MAJOR_FAF set otherwise (synthetic/non-FAF5 networks with
    no hpms_fclass column)."""
    if hpms_fclass is not None and not (isinstance(hpms_fclass, float) and np.isnan(hpms_fclass)):
        try:
            return int(hpms_fclass) <= 3
        except (TypeError, ValueError):
            pass
    rc_lower = ("" if road_classification is None else str(road_classification)).strip().lower()
    return rc_lower in MAJOR_FAF


def compute_damage_level_on_flooded_roads(
    fldType: str,
    road_classification: str,
    trunk_road: str,
    road_label: str,
    fldDepth: float,
    *,
    hpms_fclass=None,
    nhs_designation=None,
) -> str:
    """Determine categorical damage for FAF/US road classes from flood depth (m).

    ``hpms_fclass``/``nhs_designation`` are optional (keyword-only, default
    None): real HPMS F_Class / NHS attributes (resiflow.hpms_fclass), used
    when present to drive the major/minor split (or, when the configured
    T20 table is the 3-way US-candidate one, the sophisticated/simple/
    ordinary split) instead of the legacy name-based classifier. Absent on
    non-FAF5 networks -- falls back to the legacy behavior unchanged.
    """
    if fldType == "flood":
        fldType = "river"
    depth = float(fldDepth or 0.0) * 100.0  # cm
    rc_lower = ("" if road_classification is None else str(road_classification)).strip().lower()
    if rc_lower not in FAF_US_CLASSES:
        return "no"

    s = _damage_threshold_scale()
    if _use_table_damage_thresholds():
        table = _load_t20_table()
        if _table_uses_sophistication_scheme(table):
            key = flood_road_class_sophistication(
                pd.Series([nhs_designation]), pd.Series([road_label])
            ).iloc[0]
        else:
            key = _is_major(road_classification, hpms_fclass)
        thresholds = _thresholds_from_table(fldType, table)[key]
        return _classify_from_thresholds(depth, thresholds, s)
    major = _is_major(road_classification, hpms_fclass)
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


def _is_major_vectorized(road_classification: pd.Series, hpms_fclass: pd.Series | None) -> pd.Series:
    """Vectorized counterpart of _is_major -- see its docstring."""
    rc_lower = road_classification.fillna("").astype(str).str.strip().str.lower()
    name_based = rc_lower.isin(MAJOR_FAF)
    if hpms_fclass is None:
        return name_based
    fc = pd.to_numeric(hpms_fclass, errors="coerce")
    has_fc = fc.notna()
    out = name_based.copy()
    out.loc[has_fc] = (fc.loc[has_fc] <= 3)
    return out


def compute_damage_levels_on_flooded_roads_vectorized(
    fldType: str,
    road_classification: pd.Series,
    trunk_road: pd.Series,
    road_label: pd.Series,
    fldDepth: pd.Series,
    *,
    hpms_fclass: pd.Series | None = None,
    nhs_designation: pd.Series | None = None,
) -> pd.Series:
    """Vectorized FAF/US flood categorical damage.

    ``hpms_fclass``/``nhs_designation`` -- see compute_damage_level_on_flooded_roads's
    docstring (same optional real-attribute upgrade, vectorized).
    """
    if fldType == "flood":
        fldType = "river"
    depth_cm = pd.to_numeric(fldDepth, errors="coerce").fillna(0.0) * 100.0
    rc_lower = road_classification.fillna("").astype(str).str.strip().str.lower()
    faf_mask = rc_lower.isin(FAF_US_CLASSES)
    major_faf = _is_major_vectorized(road_classification, hpms_fclass)
    result = pd.Series("no", index=rc_lower.index, dtype=object)

    s = _damage_threshold_scale()
    if _use_table_damage_thresholds():
        table = _load_t20_table()
        if _table_uses_sophistication_scheme(table):
            nhs_series = nhs_designation if nhs_designation is not None else pd.Series(
                [None] * len(rc_lower), index=rc_lower.index
            )
            label_series = road_label if road_label is not None else pd.Series(
                "", index=rc_lower.index
            )
            sophistication = flood_road_class_sophistication(nhs_series, label_series)
            for key, thresholds in _thresholds_from_table(fldType, table).items():
                mask = faf_mask & (sophistication == key)
                for level in _TABLE_LEVELS:
                    if level in thresholds:
                        result.loc[mask & (depth_cm >= thresholds[level] * s)] = level
            return result
        for is_major, thresholds in _thresholds_from_table(fldType, table).items():
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
