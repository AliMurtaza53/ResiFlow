import pandas as pd
import pytest

import importlib.util
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "compute_county_connector_bottleneck",
    Path(__file__).resolve().parents[1] / "scripts" / "compute_county_connector_bottleneck.py",
)
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

county_fips_to_state_abbr = _MODULE.county_fips_to_state_abbr
compute_node_demand = _MODULE.compute_node_demand
compute_node_connector_capacity = _MODULE.compute_node_connector_capacity
build_overload_table = _MODULE.build_overload_table
join_overload_to_counties = _MODULE.join_overload_to_counties


def test_county_fips_to_state_abbr():
    assert county_fips_to_state_abbr("06037") == "ca"  # LA County
    assert county_fips_to_state_abbr("36061") == "ny"  # Manhattan
    assert county_fips_to_state_abbr("99999") == ""


def test_compute_node_demand_sums_inbound_and_outbound():
    od = pd.DataFrame(
        {
            "origin_node": ["n1", "n2"],
            "destination_node": ["n2", "n1"],
            "Car21": [100.0, 30.0],
        }
    )
    demand = compute_node_demand(od)
    assert demand["n1"] == pytest.approx(130.0)  # 100 outbound + 30 inbound
    assert demand["n2"] == pytest.approx(130.0)  # 30 outbound + 100 inbound


def test_compute_node_connector_capacity_sums_touching_edges():
    road_links = pd.DataFrame(
        {
            "from_id": ["n1", "n1", "n3"],
            "to_id": ["n2", "n4", "n2"],
            "acc_capacity": [1000.0, 500.0, 2000.0],
        }
    )
    capacity = compute_node_connector_capacity(road_links, {"n1"})
    assert capacity["n1"] == pytest.approx(1500.0)


def test_build_overload_table_flags_overloaded_nodes():
    demand = pd.Series({"n1": 300.0, "n2": 50.0})
    capacity = pd.Series({"n1": 100.0, "n2": 100.0})

    table = build_overload_table(demand, capacity)

    overloaded = table.set_index("node_id").loc["n1"]
    assert overloaded["overload_ratio"] == pytest.approx(3.0)
    under = table.set_index("node_id").loc["n2"]
    assert under["overload_ratio"] == pytest.approx(0.5)
    assert list(table["overload_ratio"]) == sorted(table["overload_ratio"], reverse=True)


def test_join_overload_to_counties_maps_node_results_to_county_fips():
    node_overload = pd.DataFrame(
        {
            "node_id": ["n1", "n2"],
            "total_demand": [300.0, 50.0],
            "total_connector_capacity": [100.0, 100.0],
            "overload_ratio": [3.0, 0.5],
        }
    )
    crosswalk = pd.DataFrame({"county_id": ["06037", "36061"], "node_id": ["n1", "n2"]})

    county_overload = join_overload_to_counties(node_overload, crosswalk)

    by_county = county_overload.set_index("county_fips")
    assert by_county.loc["06037", "overload_ratio"] == pytest.approx(3.0)
    assert by_county.loc["06037", "state_abbr"] == "ca"
    assert by_county.loc["36061", "state_abbr"] == "ny"
