import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString

from resiflow.preprocess.network_connector_insertion import (
    CENTROID_CONNECTOR_TIER,
    build_bidirectional_connector,
    build_connector_edge,
    find_nearest_eligible_attachment,
    is_eligible_attachment_edge,
    split_bidirectional_pair,
    split_edge_at_fraction,
)


def _sample_road_links() -> gpd.GeoDataFrame:
    # A straight 1-mile road, forward (n1->n2) and backward (n2->n1) directed edges.
    return gpd.GeoDataFrame(
        {
            "e_id": ["fwd1", "bwd1", "bridge1"],
            "from_id": ["n1", "n2", "n3"],
            "to_id": ["n2", "n1", "n4"],
            "length": [1.0, 1.0, 1.0],
            "lanes": [2, 2, 2],
            "assignment_tier": ["arterial", "arterial", "freeway"],
            "road_classification": ["primary", "primary", "motorway"],
            "oneway": [False, False, True],
            "bridge_fraction": [0.0, 0.0, 0.6],
            "tunnel_fraction": [0.0, 0.0, 0.0],
        },
        geometry=[
            LineString([(0, 0), (1, 0)]),
            LineString([(1, 0), (0, 0)]),
            LineString([(2, 0), (3, 0)]),
        ],
    )


def test_split_edge_lengths_sum_to_parent():
    road_links = _sample_road_links()
    before, after = split_edge_at_fraction(road_links, "fwd1", 0.3, "new_node")
    assert before["length"] == pytest.approx(0.3)
    assert after["length"] == pytest.approx(0.7)
    assert before["length"] + after["length"] == pytest.approx(1.0)


def test_split_edge_preserves_attributes_unchanged():
    road_links = _sample_road_links()
    before, after = split_edge_at_fraction(road_links, "fwd1", 0.5, "new_node")
    for attr in ["lanes", "assignment_tier", "road_classification"]:
        assert before[attr] == road_links.iloc[0][attr]
        assert after[attr] == road_links.iloc[0][attr]


def test_split_edge_sets_topology_and_provenance():
    road_links = _sample_road_links()
    before, after = split_edge_at_fraction(road_links, "fwd1", 0.3, "new_node")
    assert before["from_id"] == "n1"
    assert before["to_id"] == "new_node"
    assert after["from_id"] == "new_node"
    assert after["to_id"] == "n2"
    assert before["parent_e_id"] == "fwd1"
    assert after["parent_e_id"] == "fwd1"
    assert before["e_id"] != after["e_id"]


def test_split_edge_refuses_bridge():
    road_links = _sample_road_links()
    with pytest.raises(ValueError, match="bridge/tunnel-sensitive"):
        split_edge_at_fraction(road_links, "bridge1", 0.5, "new_node")


def test_split_edge_rejects_out_of_range_fraction():
    road_links = _sample_road_links()
    with pytest.raises(ValueError, match="fraction must be"):
        split_edge_at_fraction(road_links, "fwd1", 1.5, "new_node")
    with pytest.raises(ValueError, match="fraction must be"):
        split_edge_at_fraction(road_links, "fwd1", 0.0, "new_node")


def test_split_bidirectional_pair_uses_complementary_fraction():
    road_links = _sample_road_links()
    results = split_bidirectional_pair(road_links, "fwd1", "bwd1", 0.3, "new_node")
    fwd_before, fwd_after, bwd_before, bwd_after = results
    # forward splits at 0.3 of its own length; backward (opposite direction,
    # same physical road) must split at 0.7 of ITS length to land at the
    # same geometric point
    assert fwd_before["length"] == pytest.approx(0.3)
    assert bwd_before["length"] == pytest.approx(0.7)
    assert fwd_before["to_id"] == "new_node"
    assert bwd_after["from_id"] == "new_node"


def test_build_connector_edge_uses_dedicated_tier():
    edge = build_connector_edge("conn1", "centroid_42", "n1", 0.5, speed_mph=20.0)
    assert edge["assignment_tier"] == CENTROID_CONNECTOR_TIER
    assert edge["from_id"] == "centroid_42"
    assert edge["to_id"] == "n1"
    assert edge["length"] == pytest.approx(0.5)
    assert edge["Speed_Limit"] == pytest.approx(20.0)


def test_build_bidirectional_connector_gives_both_directions():
    edges = build_bidirectional_connector("centroid_42", "n1", 0.5, e_id_prefix="conn1")
    assert len(edges) == 2
    directions = {(e["from_id"], e["to_id"]) for e in edges}
    assert directions == {("centroid_42", "n1"), ("n1", "centroid_42")}
    for e in edges:
        assert e["assignment_tier"] == CENTROID_CONNECTOR_TIER


def _candidate_road_links() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "e_id": ["near_arterial", "far_arterial", "ramp", "bridge"],
            "road_classification": ["primary", "primary", "motorway_link", "primary"],
            "road_label": ["road", "road", "road", "bridge"],
            "Road_Name": ["MAIN ST", "SIDE ST", "RAMP", "RIVER BRIDGE"],
            "bridge_fraction": [0.0, 0.0, 0.0, 1.0],
            "tunnel_fraction": [0.0, 0.0, 0.0, 0.0],
        },
        geometry=[
            LineString([(0, 0), (0, 1)]),      # closest to the centroid at (0.01, 0.5)
            LineString([(5, 0), (5, 1)]),       # far away
            LineString([(0.01, 0), (0.01, 1)]),  # closer than near_arterial, but a ramp
            LineString([(0.005, 0), (0.005, 1)]),  # closest of all, but a bridge
        ],
    )


def test_is_eligible_attachment_edge_excludes_ramps_and_structures():
    roads = _candidate_road_links()
    eligible = {row["e_id"] for _, row in roads.iterrows() if is_eligible_attachment_edge(row)}
    assert eligible == {"near_arterial", "far_arterial"}


def test_find_nearest_eligible_attachment_skips_ramp_and_bridge():
    roads = _candidate_road_links()
    result = find_nearest_eligible_attachment(0.01, 0.5, roads)
    assert result["e_id"] == "near_arterial"


def test_find_nearest_eligible_attachment_clips_away_from_endpoints():
    roads = _candidate_road_links()
    # centroid level with the very start of the line -> fraction must still
    # clip to min_fraction, not land at 0 (the endpoint/intersection)
    result = find_nearest_eligible_attachment(0.0, 0.0, roads, min_fraction=0.15, max_fraction=0.85)
    assert result["fraction"] == pytest.approx(0.15)


def test_find_nearest_eligible_attachment_raises_if_nothing_qualifies():
    roads = _candidate_road_links()
    only_ramp_and_bridge = roads[roads["e_id"].isin(["ramp", "bridge"])]
    with pytest.raises(ValueError, match="no eligible"):
        find_nearest_eligible_attachment(0.01, 0.5, only_ramp_and_bridge)
