import pandas as pd
import pytest

from resiflow.demand.connector_split import build_node_targets, split_od

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
