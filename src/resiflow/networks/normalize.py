"""Normalize link tables from FAF5, OSM, or other sources."""

from __future__ import annotations

from typing import Any

import pandas as pd

from resiflow.config import get_env
from resiflow.networks.base import TIER_TO_LEGACY_COMBINED
from resiflow.networks.faf5 import normalize_network_class
from resiflow.networks.osm import normalize_highway_tag
from resiflow.networks.profiles import load_network_mapping


def detect_network_source(
    road_links: pd.DataFrame,
    explicit: str | None = None,
) -> str:
    """Infer network source from columns or environment."""
    if explicit:
        return explicit.strip().lower()
    env = get_env("RESIFLOW_NETWORK_SOURCE", "NIRD_NETWORK_SOURCE")
    if env:
        return env.strip().lower()
    if "network_source" in road_links.columns:
        values = road_links["network_source"].dropna().astype(str).str.lower()
        if not values.empty:
            return values.mode().iloc[0]
    if "tntp_capacity_vph" in road_links.columns or "tntp_free_flow_time" in road_links.columns:
        return "tntp"
    if "highway" in road_links.columns:
        return "osm"
    if "FAFZONE" in road_links.columns or "road_classification_detail" in road_links.columns:
        return "faf5"
    return "faf5"


def _resolve_network_class(
    road_links: pd.DataFrame,
    source: str,
) -> pd.Series:
    if "network_class" in road_links.columns:
        return road_links["network_class"].astype(str).str.strip().str.lower()

    if source == "osm":
        if "highway" in road_links.columns:
            return road_links["highway"].map(normalize_highway_tag)
        if "road_classification" in road_links.columns:
            return road_links["road_classification"].map(normalize_highway_tag)
        raise ValueError("OSM links require 'highway' or 'road_classification' column")

    if source == "tntp":
        if "road_classification" in road_links.columns:
            return road_links["road_classification"].astype(str).str.strip().str.lower()
        raise ValueError("TNTP links require 'road_classification' column")

    if "road_classification" in road_links.columns:
        return road_links["road_classification"].map(normalize_network_class)
    raise ValueError("Network links require 'road_classification' or 'highway' column")


def _map_with_default(
    network_class: pd.Series,
    mapping: dict[str, str],
    default: str,
) -> pd.Series:
    return network_class.map(lambda value: mapping.get(value, default))


def normalize_network_links(
    road_links: pd.DataFrame,
    *,
    source: str | None = None,
    mapping: dict[str, Any] | None = None,
    params_root: str | None = None,
) -> pd.DataFrame:
    """Add network_source, network_class, assignment_tier, damage_profile, combined_label.

    ``assignment_tier``/``damage_profile`` are only FILLED from the name-based
    ``network_mapping.<source>.json`` where the link doesn't already carry a
    real value. FAF5 links converted via
    ``resiflow.preprocess.faf5_network.convert_faf5_links`` already carry a
    real ``assignment_tier`` derived from HPMS ``F_Class``
    (``resiflow.hpms_fclass.assignment_tier_from_fclass``: F1/F2->freeway,
    F3/F4->arterial, F5/F6->collector, F7->local_access) -- a real,
    per-link-differentiated value. Until 2026-10-08 this function
    unconditionally OVERWROTE that real value with the name-based mapping
    (every FAF5 ``primary`` link -> "arterial" regardless of whether its
    real F_Class was actually a principal arterial, minor arterial, or
    major collector), immediately after Script 1 loaded the harmonized
    network -- see docs/FLOOD_TABLE_REVIEW.md Section 3/4 item 9. Preserving
    a real existing value here fixes that silently-discarded fix; the
    JSON mapping remains the correct fallback for non-FAF5 networks (OSM,
    TNTP, toy fixtures) that have no such per-link attribute.
    """
    out = road_links.copy()
    resolved_source = detect_network_source(out, explicit=source)
    resolved_mapping = mapping or load_network_mapping(
        resolved_source,
        params_root=params_root,
    )

    network_class = _resolve_network_class(out, resolved_source)
    tier_map = resolved_mapping.get("network_class_to_assignment_tier", {})
    damage_map = resolved_mapping.get("network_class_to_damage_profile", {})
    default_tier = resolved_mapping.get("default_assignment_tier", "arterial")
    default_damage = resolved_mapping.get("default_damage_profile", "minor_road")

    mapped_tier = _map_with_default(network_class, tier_map, default_tier)
    mapped_damage = _map_with_default(network_class, damage_map, default_damage)

    out["network_source"] = resolved_source
    out["network_class"] = network_class
    if "assignment_tier" in out.columns:
        out["assignment_tier"] = out["assignment_tier"].where(
            out["assignment_tier"].notna(), mapped_tier
        )
    else:
        out["assignment_tier"] = mapped_tier
    if "damage_profile" in out.columns:
        out["damage_profile"] = out["damage_profile"].where(
            out["damage_profile"].notna(), mapped_damage
        )
    else:
        out["damage_profile"] = mapped_damage
    out["combined_label"] = out["assignment_tier"].map(TIER_TO_LEGACY_COMBINED)
    return out


def is_major_road(
    road_classification: str | None,
    trunk_road: bool = False,
) -> bool:
    """Return True for major FAF/OSM highway classes (fragility / damage helper)."""
    del trunk_road
    from resiflow.networks.base import MAJOR_ROAD_CLASSES

    rc = ("" if road_classification is None else str(road_classification)).strip().lower()
    return rc in MAJOR_ROAD_CLASSES
