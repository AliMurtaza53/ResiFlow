import pandas as pd
import pytest

from resiflow.rerouting_baseline import baseline_demand_excluding_isolated_flow


def _od(rows):
    return pd.DataFrame(rows, columns=["origin_node", "destination_node", "Car21"])


def test_partially_isolated_pair_keeps_its_routed_flow():
    od = _od([("1", "2", 10.0), ("3", "4", 5.0)])
    iso = pd.DataFrame({"origin_node": ["1"], "destination_node": ["2"], "flow": [4.0]})
    out = baseline_demand_excluding_isolated_flow(od, iso)
    assert out.set_index(["origin_node", "destination_node"]).Car21.to_dict() == {("1", "2"): 6.0, ("3", "4"): 5.0}


def test_fully_isolated_pair_is_dropped():
    od = _od([("1", "2", 10.0), ("3", "4", 5.0)])
    iso = pd.DataFrame({"origin_node": ["1"], "destination_node": ["2"], "flow": [10.0]})
    out = baseline_demand_excluding_isolated_flow(od, iso)
    assert list(zip(out.origin_node, out.destination_node)) == [("3", "4")]


def test_total_baseline_flow_equals_served_flow():
    od = _od([("1", "2", 10.0), ("3", "4", 5.0), ("5", "6", 2.0)])
    iso = pd.DataFrame({"origin_node": ["1", "5"], "destination_node": ["2", "6"], "flow": [3.0, 2.0]})
    out = baseline_demand_excluding_isolated_flow(od, iso)
    assert out.Car21.sum() == pytest.approx(17.0 - 5.0)


def test_empty_isolation_and_int_node_ids():
    od = pd.DataFrame({"origin_node": [1], "destination_node": [2], "Car21": [3.0]})
    assert baseline_demand_excluding_isolated_flow(od, pd.DataFrame()).equals(od)
    iso = pd.DataFrame({"origin_node": ["1"], "destination_node": ["2"], "flow": [1.0]})
    assert baseline_demand_excluding_isolated_flow(od, iso).Car21.iloc[0] == pytest.approx(2.0)
