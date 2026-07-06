"""Tests for TNTP parsers, demand adapters, and testbed registry."""

from __future__ import annotations

import pytest

from resiflow.demand.tntp import load_tntp_trips, split_freight_passenger
from resiflow.networks.tntp import read_tntp_links, read_tntp_nodes, read_tntp_trips
from resiflow.testbeds import list_testbeds, load_testbed


@pytest.fixture
def sioux_spec():
    return load_testbed("sioux_falls")


def test_testbed_registry_lists_sioux_falls():
    assert "sioux_falls" in list_testbeds()


def test_read_tntp_sioux_falls_files(sioux_spec):
    nodes = read_tntp_nodes(sioux_spec.node_path())
    links = read_tntp_links(sioux_spec.net_path())
    trips = read_tntp_trips(sioux_spec.trips_path())

    assert len(nodes) == 24
    assert len(links) == 76
    assert trips["Car21"].sum() > 0
    assert set(links.columns) >= {
        "init_node",
        "term_node",
        "capacity",
        "b",
        "power",
        "toll",
    }


def test_load_tntp_trips_applies_scale_and_prefix(sioux_spec):
    raw = read_tntp_trips(sioux_spec.trips_path())
    scaled = load_tntp_trips(
        sioux_spec.trips_path(),
        demand_scale=sioux_spec.demand_scale,
        node_id_formatter=sioux_spec.node_id_formatter(),
    )
    assert scaled["Car21"].sum() == pytest.approx(
        raw["Car21"].sum() * sioux_spec.demand_scale
    )
    assert scaled["origin_node"].str.startswith("sf_").all()


def test_split_freight_passenger_conserves_total(sioux_spec):
    od = load_tntp_trips(
        sioux_spec.trips_path(),
        demand_scale=sioux_spec.demand_scale,
        node_id_formatter=sioux_spec.node_id_formatter(),
    )
    freight, passenger = split_freight_passenger(
        od, freight_share=sioux_spec.freight_share_of_passenger
    )
    assert freight["Car21"].sum() + passenger["Car21"].sum() == pytest.approx(
        od["Car21"].sum()
    )
