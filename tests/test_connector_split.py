import pandas as pd
import pytest

from resiflow.demand.connector_split import build_node_targets, main_component_nodes, split_od

COUNTIES = pd.DataFrame(
    {
        "county_fips": ["01001", "01003", "01005", "01007"],
        "node_id": [10, 20, 30, 30],  # 01005 and 01007 share node 30
    }
)
CONNECTORS = pd.DataFrame(
    {
        "centroid_id": [1001, 1001, 1003, 1005, 1005, 100005, 100005],
        "road_node": [101, 102, 201, 301, 302, 901, 902],
    }
)


def test_targets_split_only_multi_connector_unshared_counties():
    t = build_node_targets(COUNTIES, CONNECTORS)
    a = t[t["node"] == "10"].set_index("target")["weight"]
    assert a.to_dict() == {"101": 0.5, "102": 0.5}
    assert t[t["node"] == "20"][["target", "weight"]].values.tolist() == [["20", 1.0]]
    assert t[t["node"] == "30"][["target", "weight"]].values.tolist() == [["30", 1.0]]


def test_split_conserves_flow_and_keeps_intrazonal():
    t = build_node_targets(COUNTIES, CONNECTORS)
    od = pd.DataFrame(
        {
            "origin_node": ["10", "10", "20"],
            "destination_node": ["20", "10", "10"],
            "Car21": [8.0, 5.0, 4.0],
        }
    )
    out = split_od(od, t)
    assert out["Car21"].sum() == pytest.approx(17.0)
    row = out[(out.origin_node == "101") & (out.destination_node == "20")]
    assert row["Car21"].iloc[0] == pytest.approx(4.0)
    kept = out[(out.origin_node == "10") & (out.destination_node == "10")]
    assert kept["Car21"].iloc[0] == pytest.approx(5.0)
    both = out[(out.origin_node == "20") & (out.destination_node == "102")]
    assert both["Car21"].iloc[0] == pytest.approx(2.0)


def test_disconnected_exit_is_dropped_and_county_share_renormalized():
    links = pd.DataFrame({
        "from_id": [20, 101, 102, 301],
        "to_id": [101, 30, 999, 102],
        "current_capacity": [100, 100, 100, 100],
        # The centroid connector would otherwise hide the disconnected island.
        "faf5_class": pd.array([pd.NA, 14, 14, 50], dtype="Int64"),
    })
    valid = main_component_nodes(links)
    assert valid == {"20", "101", "30"}
    targets = build_node_targets(COUNTIES, CONNECTORS, valid_nodes=valid)
    assert targets[targets.node.eq("10")].set_index("target").weight.to_dict() == {"101": 1.0}
    assert targets.attrs["dropped_connector_ends"] == [
        {"county_fips": "01001", "node_id": "10", "target": "102", "weight": 0.5}
    ]
    od = pd.DataFrame({"origin_node": ["10", "20"], "destination_node": ["20", "10"],
                       "Car21": [8.0, 4.0]})
    result = split_od(od, targets)
    assert result.Car21.sum() == 12.0
    assert set(result.origin_node) | set(result.destination_node) <= valid


def test_no_connected_exit_fails_instead_of_silent_fallback():
    with pytest.raises(ValueError, match="No connected connector exit"):
        build_node_targets(COUNTIES, CONNECTORS, valid_nodes={"10", "20", "30"})


def test_disconnected_unsplit_loading_point_fails():
    with pytest.raises(ValueError, match="Unsplit loading nodes"):
        build_node_targets(COUNTIES, CONNECTORS, valid_nodes={"101", "102", "30"})


def test_main_component_nodes_is_weak():
    # Integration test retained: stored one-way endpoint order is not an SCC rule.
    assert main_component_nodes([1, 2, 9], [2, 3, 8]) == {"1", "2", "3"}


def test_stub_end_dropped_and_share_goes_to_connected_end():
    # 35f2e8f's scenario retained; the owner requires the surviving EXIT,
    # rather than the old source-node fallback which bypassed that exit.
    valid = {"101", "20", "10", "30", "301", "302", "201"}
    targets = build_node_targets(COUNTIES, CONNECTORS, valid)
    assert targets[targets.node.eq("10")][["target", "weight"]].values.tolist() == [["101", 1.0]]
    od = pd.DataFrame({"origin_node": ["10"], "destination_node": ["20"], "Car21": [8.]})
    assert split_od(od, targets).Car21.sum() == pytest.approx(8.)


def test_county_with_no_valid_end_rejects_unsafe_fallback():
    # Integration's all-invalid scenario retained; keeping invalid ends is
    # superseded by 6afc118's fail-closed guard, not silently discarded.
    with pytest.raises(ValueError, match="No connected connector exit"):
        build_node_targets(COUNTIES, CONNECTORS, valid_nodes=set())


def test_clark_county_surviving_exit_receives_all_demand():
    counties = pd.DataFrame({"county_fips": ["53011", "06037"], "node_id": [55788, 123]})
    connectors = pd.DataFrame({"centroid_id": [53011, 53011, 6037], "road_node": [55804, 55797, 123]})
    targets = build_node_targets(counties, connectors, valid_nodes={"55797", "123"})
    assert targets[targets.node.eq("55788")].set_index("target").weight.to_dict() == {"55797": 1.0}
    od = pd.DataFrame({"origin_node": [55788, 123], "destination_node": [123, 55788], "Car21": [8., 4.]})
    result = split_od(od, targets)
    assert result.Car21.sum() == 12.
    assert "55804" not in set(result.origin_node) | set(result.destination_node)
