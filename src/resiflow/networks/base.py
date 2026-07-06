"""Shared network adapter types and tier constants."""

from __future__ import annotations

from typing import Literal

NetworkSource = Literal["faf5", "osm"]

ASSIGNMENT_TIERS = ("freeway", "arterial", "collector", "local_access")
DAMAGE_PROFILES = ("major_road", "minor_road")

# Legacy UK-style combined_label values used by older parameters and outputs.
LEGACY_COMBINED_TO_TIER: dict[str, str] = {
    "M": "freeway",
    "A_dual": "arterial",
    "A_single": "collector",
    "B": "local_access",
    "B_dual": "local_access",
    "B_single": "local_access",
}

TIER_TO_LEGACY_COMBINED: dict[str, str] = {
    "freeway": "M",
    "arterial": "A_dual",
    "collector": "A_single",
    "local_access": "B",
}

# Backward-compat aliases for fragility / damage modules.
MAJOR_ROAD_CLASSES = frozenset(
    {"motorway", "motorway_link", "trunk", "primary", "secondary"}
)
FAF_ROAD_CLASSES = frozenset(
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

LEGACY_PROFILE_FILE_ALIASES: dict[str, str] = {
    "flow_cap_plph": "flow_cap_plph_dict.json",
    "flow_breakpoint": "flow_breakpoint_dict.json",
    "free_flow_speed": "free_flow_speed_dict.json",
    "urban_speed_cap": "urban_speed_cap.json",
    "min_speed_cap": "min_speed_cap.json",
}
