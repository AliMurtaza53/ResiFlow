"""Network-classification and assignment adapter layer (FAF5, OSM, TNTP, ...)."""

from resiflow.networks.assignment import map_tier_profile, tier_series
from resiflow.networks.base import (
    ASSIGNMENT_TIERS,
    DAMAGE_PROFILES,
    LEGACY_COMBINED_TO_TIER,
    TIER_TO_LEGACY_COMBINED,
)
from resiflow.networks.normalize import detect_network_source, is_major_road, normalize_network_links
from resiflow.networks.tntp import (
    links_to_geodataframe,
    read_tntp_links,
    read_tntp_nodes,
    read_tntp_trips,
)
from resiflow.networks.profiles import (
    coerce_profile_dict,
    load_assignment_profiles,
    load_network_mapping,
    resolve_params_root,
)

__all__ = [
    "ASSIGNMENT_TIERS",
    "DAMAGE_PROFILES",
    "LEGACY_COMBINED_TO_TIER",
    "TIER_TO_LEGACY_COMBINED",
    "coerce_profile_dict",
    "detect_network_source",
    "is_major_road",
    "links_to_geodataframe",
    "load_assignment_profiles",
    "load_network_mapping",
    "map_tier_profile",
    "normalize_network_links",
    "read_tntp_links",
    "read_tntp_nodes",
    "read_tntp_trips",
    "resolve_params_root",
    "tier_series",
]
