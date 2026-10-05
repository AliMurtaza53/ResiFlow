"""Minimal tests for NTAD tunnel load + spatial index."""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, Point

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from build_nti_tunnel_index import build_tunnel_index  # noqa: E402
from load_ntad_tunnel_gpkg import load_ntad_tunnels  # noqa: E402


def test_build_tunnel_index_flags_nearest_link(tmp_path):
    links = gpd.GeoDataFrame(
        {"e_id": ["a", "b"]},
        geometry=[
            LineString([(0, 0), (1000, 0)]),
            LineString([(0, 5000), (1000, 5000)]),
        ],
        crs="EPSG:9311",
    )
    links_path = tmp_path / "links.gpq"
    links.to_parquet(links_path)

    # Portal near midpoint of link a (in EPSG:4326 via transform of projected mid)
    mid_a = gpd.GeoSeries([Point(500, 0)], crs="EPSG:9311").to_crs("EPSG:4326").iloc[0]
    nti = pd.DataFrame(
        {
            "tunnel_number": ["T1"],
            "latitude": [mid_a.y],
            "longitude": [mid_a.x],
            "tunnel_length_m": [100.0],
            "roadway_width_m": [10.0],
        }
    )
    nti_path = tmp_path / "nti.parquet"
    nti.to_parquet(nti_path)

    index, stats = build_tunnel_index(nti_path, links_path, max_distance_m=100.0)
    assert stats["matched_tunnels"] == 1
    assert list(index["e_id"]) == ["a"]
    assert (index["road_tunnel"] == "yes").all()


def test_build_tunnel_index_uses_longest_bore_not_sum(tmp_path):
    """Two bores at the same portal must not have their lengths summed --
    docs/BRDIGE_COSTS.md step 2: 'Grouped NTI records use longest-bore length.'
    A naive sum() would double the real tunnel length for a 2-bore tunnel."""
    links = gpd.GeoDataFrame(
        {"e_id": ["a"]},
        geometry=[LineString([(0, 0), (1000, 0)])],
        crs="EPSG:9311",
    )
    links_path = tmp_path / "links.gpq"
    links.to_parquet(links_path)

    mid_a = gpd.GeoSeries([Point(500, 0)], crs="EPSG:9311").to_crs("EPSG:4326").iloc[0]
    nti = pd.DataFrame(
        {
            "tunnel_number": ["BORE1", "BORE2"],
            "latitude": [mid_a.y, mid_a.y],
            "longitude": [mid_a.x, mid_a.x],
            "tunnel_length_m": [900.0, 880.0],
            "roadway_width_m": [9.0, 9.0],
            "lanes": [2, 2],
        }
    )
    nti_path = tmp_path / "nti.parquet"
    nti.to_parquet(nti_path)

    index, _ = build_tunnel_index(nti_path, links_path, max_distance_m=100.0)
    row = index.iloc[0]
    assert row["n_tunnels"] == 2
    assert row["tunnel_length_m"] == pytest.approx(900.0)
    assert row["tunnel_length_m_min"] == pytest.approx(880.0)
    assert row["lanes_total"] == 4


def test_load_ntad_tunnels_from_gpkg(tmp_path):
    gdf = gpd.GeoDataFrame(
        {
            "tunnel_number_i1": ["T9"],
            "tunnel_name_i2": ["Demo"],
            "state_code_i3": ["51"],
            "portal_latitude_i13": [38.9],
            "portal_longitude_i14": [-77.0],
            "tunnel_length_g1": [200.0],
            "roadway_width_curb_to_curb_g3": [12.0],
            "total_number_of_lanes_a3": [2],
            "year_built_a1": [1990],
            "service_in_tunnel_a8": [1],
            "functional_classification_c7": [1],
            "nhs_designation_c5": [1],
            "facility_carried_i10": ["I-66"],
        },
        geometry=[Point(-77.0, 38.9)],
        crs="EPSG:4326",
    )
    gpkg = tmp_path / "nti.gpkg"
    gdf.to_file(gpkg, layer="National_Tunnel_Inventory", driver="GPKG")
    df = load_ntad_tunnels(gpkg)
    assert len(df) == 1
    assert df.iloc[0]["tunnel_number"] == "T9"
    assert df.iloc[0]["latitude"] == pytest.approx(38.9)
    # NTI coding-guide G.1/G.3 are feet; must come back converted to real
    # meters (0.3048 m/ft), not the raw feet value under a "_m" name.
    assert df.iloc[0]["tunnel_length_m"] == pytest.approx(200.0 * 0.3048)
    assert df.iloc[0]["roadway_width_m"] == pytest.approx(12.0 * 0.3048)
