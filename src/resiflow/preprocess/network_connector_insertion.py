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


def _is_ramp(edge: pd.Series) -> bool:
    """True for interchange ramps/connector-style links -- never a plausible
    place for ordinary demand to enter the network, VA's own FACTYPE scheme
    (hramp/Lramp, codes 9-10) keeps these distinct from arterials for the
    same reason."""
    for col in ("road_classification", "road_classification_coarse", "road_classification_detail"):
        if col in edge.index and "ramp" in str(edge[col]).lower():
            return True
        if col in edge.index and "motorway_link" in str(edge[col]).lower():
            return True
    for col in ("road_label", "Road_Name"):
        if col in edge.index and "ramp" in str(edge[col]).lower():
            return True
    return False


def _is_limited_access_mainline(edge: pd.Series) -> bool:
    """True for freeway/motorway mainline -- these have no direct property
    access in reality (entry/exit only via ramps), so they are no more a
    plausible connector attachment point than a ramp itself."""
    if "assignment_tier" in edge.index and str(edge["assignment_tier"]).lower() == "freeway":
        return True
    for col in ("road_classification", "road_classification_coarse", "road_classification_detail"):
        if col in edge.index and str(edge[col]).lower() == "motorway":
            return True
    return False


def is_eligible_attachment_edge(edge: pd.Series) -> bool:
    """An edge a connector may attach to: not a ramp, not freeway/motorway
    mainline, not bridge/tunnel.

    Deliberately simple -- "avoid intersections and ramps and bridges and
    tunnels" is the whole bar for now, not a geographically-optimal choice
    of access point. Freeway mainline is excluded alongside ramps for the
    same underlying reason: neither has direct property access.
    """
    return (
        not _is_ramp(edge)
        and not _is_limited_access_mainline(edge)
        and not _is_hazard_sensitive(edge)
    )


def find_nearest_eligible_attachment(
    centroid_lon: float,
    centroid_lat: float,
    road_links: "gpd.GeoDataFrame",
    *,
    min_fraction: float = 0.15,
    max_fraction: float = 0.85,
    e_id_col: str = "e_id",
) -> dict:
    """Nearest eligible point to (centroid_lon, centroid_lat) to attach a connector.

    "Eligible" = passes is_eligible_attachment_edge(), and the nearest point
    on the edge falls within [min_fraction, max_fraction] of its length --
    clipping away from the endpoints keeps the new node clear of whatever
    real intersection sits at either end, without needing to resolve
    intersection geometry explicitly.

    Returns {"e_id", "fraction", "point": (lon, lat), "distance_deg"} for the
    closest qualifying edge, or raises ValueError if none qualify.

    Degree-planar distance (not haversine) is precision enough to choose
    among nearby local-scale candidates; this is a coarse nearest-edge
    search, not a geodesic routing decision.
    """
    if gpd is None:
        raise ImportError("geopandas is required to search for an attachment point")
    from shapely.geometry import Point

    centroid_point = Point(centroid_lon, centroid_lat)
    best: dict | None = None
    for _, edge in road_links.iterrows():
        if not is_eligible_attachment_edge(edge):
            continue
        geom = edge.geometry
        while hasattr(geom, "geoms"):
            geom = geom.geoms[0]
        fraction = geom.project(centroid_point, normalized=True)
        fraction = min(max(fraction, min_fraction), max_fraction)
        candidate_point = geom.interpolate(fraction, normalized=True)
        distance = centroid_point.distance(candidate_point)
        if best is None or distance < best["distance_deg"]:
            best = {
                "e_id": edge[e_id_col],
                "fraction": float(fraction),
                "point": (candidate_point.x, candidate_point.y),
                "distance_deg": float(distance),
            }
    if best is None:
        raise ValueError("no eligible (non-ramp, non-bridge/tunnel) edge found to attach to")
    return best


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
    length_miles: float | None = None,
    *,
    geometry=None,
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

    ``geometry`` (a shapely LineString in the network's native CRS) should
    be passed whenever real network coordinates are available: the
    assignment engine derives travel distance from ``geometry.length``, NOT
    from the ``length`` attribute (road_revised.py recomputes
    ``length_mile`` from geometry every run) -- a connector edge committed
    to a real network without real geometry would silently assign as
    zero-length. When given, ``length`` is set from the geometry itself
    (same units as the rest of road_links, i.e. CRS-native meters), and
    ``length_miles`` is ignored. Without ``geometry`` (e.g. schema-only unit
    tests), ``length_miles`` is stored directly, unconverted.

    ``template`` (optional), if given, supplies values for any columns not
    set explicitly below (e.g. STATE, County_Name) so the new edge has a
    complete row matching the network's schema.
    """
    row = template.copy() if template is not None else pd.Series(dtype=object)
    row["e_id"] = e_id
    row["from_id"] = centroid_node_id
    row["to_id"] = attach_node_id
    if geometry is not None:
        row.geometry = geometry
        row["length"] = geometry.length
    else:
        row["length"] = length_miles
    row["assignment_tier"] = CENTROID_CONNECTOR_TIER
    row["road_classification"] = CENTROID_CONNECTOR_TIER
    row["lanes"] = 1
    row["oneway"] = oneway
    row["urban"] = template["urban"] if template is not None and "urban" in template.index else 1
    row["Speed_Limit"] = speed_mph
    row["parent_e_id"] = None
    # road_revised.py's create_igraph_network() builds the Dijkstra edge
    # weight as time_cost + operating_cost + average_toll_cost with NO
    # NaN guard -- a connector edge missing this column (e.g. no template
    # given) becomes NaN weight and crashes igraph's shortest-path call at
    # assignment time, not at build time. A connector has no toll.
    if "average_toll_cost" not in row.index or pd.isna(row.get("average_toll_cost")):
        row["average_toll_cost"] = 0.0
    return row


def build_bidirectional_connector(
    centroid_node_id,
    attach_node_id,
    length_miles: float | None = None,
    *,
    e_id_prefix: str,
    geometry=None,
    speed_mph: float = 20.0,
    template: pd.Series | None = None,
) -> list[pd.Series]:
    """Build both directions of a centroid connector (ingress + egress).

    ``geometry``, if given, is the centroid->attach_node LineString; the
    reverse-direction edge gets it reversed so both directions carry real,
    equal-length geometry.
    """
    reverse_geometry = None
    if geometry is not None:
        reverse_geometry = type(geometry)(list(geometry.coords)[::-1])
    out_edge = build_connector_edge(
        f"{e_id_prefix}_out", centroid_node_id, attach_node_id, length_miles,
        geometry=geometry, speed_mph=speed_mph, template=template,
    )
    in_edge = build_connector_edge(
        f"{e_id_prefix}_in", attach_node_id, centroid_node_id, length_miles,
        geometry=reverse_geometry, speed_mph=speed_mph, template=template,
    )
    return [out_edge, in_edge]


__all__ = [
    "CENTROID_CONNECTOR_TIER",
    "is_eligible_attachment_edge",
    "find_nearest_eligible_attachment",
    "split_edge_at_fraction",
    "split_bidirectional_pair",
    "build_connector_edge",
    "build_bidirectional_connector",
]
