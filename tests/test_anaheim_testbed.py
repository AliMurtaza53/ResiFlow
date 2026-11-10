"""Anaheim TNTP testbed: counts, zone connectors, and real link geometry from GeoJSON."""

from __future__ import annotations

import pytest

from resiflow.networks.tntp import (
    links_to_geodataframe,
    read_link_geojson,
    read_tntp_links,
    read_tntp_nodes,
    read_tntp_trips,
)
from resiflow.testbeds import list_testbeds, load_testbed

N_ZONES = 38


@pytest.fixture(scope="module")
def spec():
    return load_testbed("anaheim")


@pytest.fixture(scope="module")
def links(spec):
    return read_tntp_links(spec.net_path())


def test_registered():
    assert "anaheim" in list_testbeds()


def test_counts_and_demand(spec, links):
    nodes = read_tntp_nodes(spec.node_path())
    assert (len(nodes), len(links)) == (416, 914)
    trips = read_tntp_trips(spec.trips_path())
    assert trips.Car21.sum() == pytest.approx(104_694.4, rel=1e-4)
    assert set(trips.origin_node.astype(int)) <= set(range(1, N_ZONES + 1))


def test_centroid_connectors(links):
    is_zone = lambda col: links[col].astype(int) <= N_ZONES  # noqa: E731
    assert (is_zone("init_node") | is_zone("term_node")).sum() == 118


def test_real_geometry_used(spec, links):
    nodes = read_tntp_nodes(spec.node_path())
    geoms = read_link_geojson(spec.link_geojson_path(), links)
    gdf = links_to_geodataframe(nodes, links, link_geometries=geoms)
    straight = links_to_geodataframe(nodes, links)
    assert len(gdf) == 914 and gdf.crs.to_epsg() == 4326
    assert (gdf.geometry.apply(lambda g: len(g.coords)) > 2).any()  # polylines, not chords
    assert gdf.geometry.apply(lambda g: g.is_valid).all()
    # endpoints still agree with the node layer
    assert gdf.geometry.apply(lambda g: g.coords[0]).tolist() == straight.geometry.apply(
        lambda g: g.coords[0]
    ).tolist()


def test_link_geojson_order_mismatch_fails(spec, links):
    with pytest.raises(ValueError):
        read_link_geojson(spec.link_geojson_path(), links.iloc[::-1].reset_index(drop=True))
