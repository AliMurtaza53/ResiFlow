"""ResiFlow preprocessing helpers (FAF5 network/OD conversion)."""

from resiflow.preprocess.faf5_network import (
    convert_faf5_links,
    convert_faf5_links_to_nird,
    extract_node_connectivity,
    validate_assignment_network,
    validate_nird_network,
)
from resiflow.preprocess.faf5_od_matrix import (
    aggregate_faf5_flows,
    convert_faf5_od_matrix,
    convert_faf5_od_to_nird,
    map_faf_zones_to_network_nodes,
    validate_assignment_od,
    validate_nird_od,
)

__all__ = [
    "aggregate_faf5_flows",
    "convert_faf5_links",
    "convert_faf5_links_to_nird",
    "convert_faf5_od_matrix",
    "convert_faf5_od_to_nird",
    "extract_node_connectivity",
    "map_faf_zones_to_network_nodes",
    "validate_assignment_network",
    "validate_assignment_od",
    "validate_nird_network",
    "validate_nird_od",
]
