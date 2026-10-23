"""Insert a centroid connector into the physical network without changing it.

Implements the explicit connector link type requested after reviewing VDOT's
VA Statewide Model (Citilabs Cube) precedent: VASWM codes centroid connectors
as a distinct FACTYPE (11), gives them a capacity (10,000 veh/lane/hr) high
enough to never bind, excludes them from the congestion/speed-flow function
entirely, and -- quantified from the live network -- attaches 80.6% of them
to a node with the directed-edge-degree signature of a MID-SEGMENT split on
an ordinary two-way road (not a real intersection).

Two operations:

  split_edge_at_fraction(): inserts a new node partway along an existing
  directed edge, replacing it with two child edges that preserve every
  non-geometric attribute (lane capacity, directionality, restrictions,
  hazard flags, tier) and whose lengths sum exactly to the parent's. Refuses
  to split inside a bridge or tunnel span (bridge_fraction/tunnel_fraction >
  0) rather than guess how to re-apportion a hazard-sensitive structure --
  callers should attach at that edge's existing endpoint instead.

  build_connector_edge(): creates the synthetic access link itself, tagged
  assignment_tier="centroid_connector" (see parameters/assignment_profiles.json
  for its capacity/speed/congestion-exclusion values), running from a new
  centroid node to the attachment node. Length x a documented speed gives its
  travel time -- VA's 15-25 mph range is used as a starting value, explicitly
  NOT a calibrated figure for any specific ResiFlow network.

Both operations only ever ADD nodes/edges; they never modify an existing
physical link's capacity, speed, or classification, and the attachment node
ends up with exactly one new edge (the connector) -- not a new crossing
movement for unrelated through traffic.
"""

from __future__ import annotations

from typing import Iterable

import pandas as pd

try:
    import geopandas as gpd  # type: ignore
    from shapely.ops import substring
except Exception:  # pragma: no cover - geometry deps unavailable in some test envs
    gpd = None
    substring = None

CENTROID_CONNECTOR_TIER = "centroid_connector"

# Attributes that must be IDENTICAL on both child edges after a split --
# nothing about the road itself (class, lanes, restrictions, hazard
# membership) changes just because a node was inserted on it.
_COPY_UNCHANGED = [
    "road_classification_coarse", "road_classification_detail", "road_classification",
    "faf5_class", "network_source", "hpms_fclass", "assignment_tier", "nhs_designation",
    "lanes", "urban", "urban_code", "averageWidth", "average_toll_cost",
    "road_bridge", "road_tunnel", "road_label", "Road_Name", "STATE", "County_Name",
    "FAFZONE", "Speed_Limit", "AB_FinalSpeed", "BA_FinalSpeed", "oneway", "trk_phb",
]


def _is_hazard_sensitive(edge: pd.Series) -> bool:
    """True if any part of this edge is a bridge or tunnel -- splitting inside
    one would misrepresent which child segment actually carries the structure."""
    for col in ("bridge_fraction", "tunnel_fraction"):
        if col in edge.index:
            value = pd.to_numeric(pd.Series([edge[col]]), errors="coerce").iloc[0]
            if pd.notna(value) and value > 0:
                return True
    return False


def split_edge_at_fraction(
    road_links: "gpd.GeoDataFrame",
    e_id,
    fraction: float,
    new_node_id,
    *,
    e_id_col: str = "e_id",
    from_col: str = "from_id",
    to_col: str = "to_id",
    length_col: str = "length",
) -> tuple[pd.Series, pd.Series]:
    """Split one directed edge into two child edges meeting at ``new_node_id``.

    ``fraction`` is the distance along the edge (0 < fraction < 1, measured
    from its ``from_id`` end) where the new node lands. Raises ValueError if
    the edge is hazard-sensitive (bridge/tunnel) or ``fraction`` is out of
    range; callers should attach at an existing endpoint in that case instead
    of guessing how to split a structure.

    Returns (child_before, child_after) as two pd.Series sharing every
    attribute in ``_COPY_UNCHANGED`` with the parent, each carrying
    ``parent_e_id`` for provenance. Their ``length_col`` values sum to the
    parent's length exactly.
    """
    if gpd is None or substring is None:
        raise ImportError("geopandas/shapely are required to split edge geometry")
    if not (0.0 < fraction < 1.0):
        raise ValueError(f"fraction must be strictly between 0 and 1, got {fraction}")

    matches = road_links[road_links[e_id_col] == e_id]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one edge with {e_id_col}={e_id!r}, found {len(matches)}")
    parent = matches.iloc[0]

    if _is_hazard_sensitive(parent):
        raise ValueError(
            f"edge {e_id!r} is bridge/tunnel-sensitive (bridge_fraction/tunnel_fraction > 0); "
            "attach at an existing endpoint instead of splitting inside the structure"
        )

    geom = parent.geometry
    while hasattr(geom, "geoms"):
        geom = geom.geoms[0]

    geom_before = substring(geom, 0.0, fraction, normalized=True)
    geom_after = substring(geom, fraction, 1.0, normalized=True)

    parent_length = float(parent[length_col])
    length_before = parent_length * fraction
    length_after = parent_length * (1.0 - fraction)

    child_before = parent.copy()
    child_after = parent.copy()

    child_before[to_col] = new_node_id
    child_before[length_col] = length_before
    child_before.geometry = geom_before
    child_before[e_id_col] = f"{e_id}_a"
    child_before["parent_e_id"] = e_id

    child_after[from_col] = new_node_id
    child_after[length_col] = length_after
    child_after.geometry = geom_after
    child_after[e_id_col] = f"{e_id}_b"
    child_after["parent_e_id"] = e_id

    # belt-and-suspenders: copied attributes must be bit-identical, not just
    # "close" -- a split must never silently change what road this is
    for col in _COPY_UNCHANGED:
        if col in parent.index:
            child_before[col] = parent[col]
            child_after[col] = parent[col]

    assert abs((length_before + length_after) - parent_length) < 1e-9, (
        "split child lengths must sum exactly to the parent's length"
    )
    return child_before, child_after


def split_bidirectional_pair(
    road_links: "gpd.GeoDataFrame",
    forward_e_id,
    backward_e_id,
    fraction: float,
    new_node_id,
    **kwargs,
) -> list[pd.Series]:
    """Split a two-way road's forward AND backward directed edges at the SAME
    proportional point, so the new node is a genuine bidirectional pass-through.

    The backward edge is split at (1 - fraction) of ITS length, since it runs
    the opposite direction over the same physical road -- the geometric split
    point must coincide even though the two directed edges' own from/to
    fractions run oppositely.
    """
    fwd_before, fwd_after = split_edge_at_fraction(road_links, forward_e_id, fraction, new_node_id, **kwargs)
    bwd_before, bwd_after = split_edge_at_fraction(road_links, backward_e_id, 1.0 - fraction, new_node_id, **kwargs)
    return [fwd_before, fwd_after, bwd_before, bwd_after]


def build_connector_edge(
    e_id,
    centroid_node_id,
    attach_node_id,
    length_miles: float,
    *,
    speed_mph: float = 20.0,
    oneway: bool = False,
    template: pd.Series | None = None,
) -> pd.Series:
    """Build one synthetic centroid-connector edge (centroid -> attach_node).

    ``speed_mph`` defaults to 20.0 mph -- VA Statewide Model's 15-25 mph
    centroid-connector range midpoint, a STARTING precedent only. Travel time
    is length / speed; capacity, congestion exclusion and speed bounds come
    from parameters/assignment_profiles.json's "centroid_connector" tier at
    edge_init() time, not set here.

    ``template`` (optional), if given, supplies values for any columns not
    set explicitly below (e.g. STATE, County_Name) so the new edge has a
    complete row matching the network's schema.
    """
    row = template.copy() if template is not None else pd.Series(dtype=object)
    row["e_id"] = e_id
    row["from_id"] = centroid_node_id
    row["to_id"] = attach_node_id
    row["length"] = length_miles
    row["assignment_tier"] = CENTROID_CONNECTOR_TIER
    row["road_classification"] = CENTROID_CONNECTOR_TIER
    row["lanes"] = 1
    row["oneway"] = oneway
    row["urban"] = template["urban"] if template is not None and "urban" in template.index else 1
    row["Speed_Limit"] = speed_mph
    row["parent_e_id"] = None
    return row


def build_bidirectional_connector(
    centroid_node_id,
    attach_node_id,
    length_miles: float,
    *,
    e_id_prefix: str,
    speed_mph: float = 20.0,
    template: pd.Series | None = None,
) -> list[pd.Series]:
    """Build both directions of a centroid connector (ingress + egress)."""
    out_edge = build_connector_edge(
        f"{e_id_prefix}_out", centroid_node_id, attach_node_id, length_miles,
        speed_mph=speed_mph, template=template,
    )
    in_edge = build_connector_edge(
        f"{e_id_prefix}_in", attach_node_id, centroid_node_id, length_miles,
        speed_mph=speed_mph, template=template,
    )
    return [out_edge, in_edge]


__all__ = [
    "CENTROID_CONNECTOR_TIER",
    "split_edge_at_fraction",
    "split_bidirectional_pair",
    "build_connector_edge",
    "build_bidirectional_connector",
]
