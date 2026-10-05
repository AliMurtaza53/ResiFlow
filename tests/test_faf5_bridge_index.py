"""Tests for the FAF5 -> NBI bridge-index wiring in faf5_network.py.

Covers the bug this fixes: road_bridge previously defaulted to 'no' for
every link unconditionally, since FAF5's own schema carries no bridge/
structure field (see parameter_diff_final.xlsx audit item 36 and
scripts/build_nbi_bridge_index.py's docstring for the full diagnosis).
"""

from __future__ import annotations

import json

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString

from resiflow.parameters import clear_cache
from resiflow.preprocess import faf5_network

_OVERRIDES_ENV = "RESIFLOW_PARAM_OVERRIDES"


@pytest.fixture(autouse=True)
def _clean_parameter_state(monkeypatch):
    monkeypatch.delenv(_OVERRIDES_ENV, raising=False)
    clear_cache()
    yield
    clear_cache()


def _toy_faf5_links() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "ID": [1, 2, 3],
            "LENGTH": [1.0, 1.0, 1.0],
            "DIR": [0, 0, 0],
            "Class": [1, 1, 1],
            "AB_Lanes": [2, 2, 2],
            "BA_Lanes": [2, 2, 2],
            "TRUCKTOLL": [0.0, 1.25, 0.0],
        },
        geometry=[
            LineString([(0, 0), (1000, 0)]),
            LineString([(0, 0), (0, 1000)]),
            LineString([(0, 0), (-1000, 0)]),
        ],
        crs="EPSG:9311",
    )


def test_trucktoll_maps_to_average_toll_cost():
    result = faf5_network.convert_faf5_links(_toy_faf5_links(), filter_centroids=False)
    by_id = result.set_index("e_id")["average_toll_cost"]
    assert by_id["1"] == pytest.approx(0.0)
    assert by_id["2"] == pytest.approx(1.25)
    assert by_id["3"] == pytest.approx(0.0)


def test_missing_trucktoll_raises():
    links = _toy_faf5_links().drop(columns=["TRUCKTOLL"])
    with pytest.raises(KeyError, match="TRUCKTOLL"):
        faf5_network.convert_faf5_links(links, filter_centroids=False)


def _toy_faf5_links_harmonization() -> gpd.GeoDataFrame:
    """One link per DIR/F_Class/Urban_Code/NHS scenario under test."""
    return gpd.GeoDataFrame(
        {
            "ID": [1, 2, 3, 4, 5],
            "LENGTH": [1.0] * 5,
            "DIR": [0, 1, 0, 0, 0],  # 1: two-way; 2: one-way; 3-5: two-way
            "Class": [11, 11, 14, 14, 41],  # 5: ferry (no fallback F-class)
            "AB_Lanes": [2, 3, 2, 2, 1],
            "BA_Lanes": [2, 0, 2, 2, 1],
            "F_Class": [1.0, 1.0, None, 10.0, None],  # 3: null -> fallback; 4: out-of-range -> fallback
            "Urban_Code": ["99999", "63217", "99998", None, "51445"],  # 1: rural; 4: missing -> rural
            "NHS": [1.0, None, 7.0, None, None],
            "TRUCKTOLL": [0.0] * 5,
        },
        geometry=[
            LineString([(0, 0), (1000, 0)]),
            LineString([(0, 0), (0, 1000)]),
            LineString([(0, 0), (-1000, 0)]),
            LineString([(0, 0), (0, -1000)]),
            LineString([(100, 0), (1100, 0)]),
        ],
        crs="EPSG:9311",
    )


def test_lanes_sum_for_two_way_max_for_one_way():
    result = faf5_network.convert_faf5_links(_toy_faf5_links_harmonization(), filter_centroids=False)
    by_id = result.set_index("e_id")["lanes"]
    assert by_id["1"] == 4  # DIR=0: AB(2) + BA(2)
    assert by_id["2"] == 3  # DIR=1: AB(3) only, not max(3, 0)


def test_urban_code_fix_handles_string_comparison_and_missing():
    result = faf5_network.convert_faf5_links(_toy_faf5_links_harmonization(), filter_centroids=False)
    by_id = result.set_index("e_id")["urban"]
    assert by_id["1"] == 0  # "99999" rural
    assert by_id["2"] == 1  # real urbanized-area code
    assert by_id["3"] == 1  # "99998" small urban area -- still urban
    assert by_id["4"] == 0  # missing Urban_Code -> defaults rural, not urban


def test_hpms_fclass_real_value_and_fallback():
    result = faf5_network.convert_faf5_links(_toy_faf5_links_harmonization(), filter_centroids=False)
    by_id = result.set_index("e_id")["hpms_fclass"]
    assert by_id["1"] == 1  # real F_Class
    assert by_id["3"] == 3  # null F_Class, faf5_class=14 -> fallback F3
    assert by_id["4"] == 3  # F_Class=10 (out of range) -> same fallback
    assert pd.isna(by_id["5"])  # ferry: no fallback entry, stays null

    tiers = result.set_index("e_id")["assignment_tier"]
    assert tiers["1"] == "freeway"
    assert tiers["3"] == "arterial"


def test_nhs_designation_passthrough():
    result = faf5_network.convert_faf5_links(_toy_faf5_links_harmonization(), filter_centroids=False)
    by_id = result.set_index("e_id")["nhs_designation"]
    assert by_id["1"] == 1
    assert pd.isna(by_id["2"])
    assert by_id["3"] == 7


def test_hpms_tunnel_flags_and_road_label(tmp_path, monkeypatch):
    csv_path = tmp_path / "hpms_enriched.csv"
    pd.DataFrame(
        {
            "ID": [3, 99],
            "hpms_STRUCTURE_TYPE": [2, 1],
        }
    ).to_csv(csv_path, index=False)
    ov = tmp_path / "ov.json"
    ov.write_text(
        json.dumps({"preprocess": {"hpms_lrs_enriched_csv": str(csv_path)}}),
        encoding="utf-8",
    )
    monkeypatch.setenv(_OVERRIDES_ENV, str(ov))
    clear_cache()

    result = faf5_network.convert_faf5_links(_toy_faf5_links(), filter_centroids=False)
    row3 = result.loc[result["e_id"] == "3"].iloc[0]
    assert row3["road_tunnel"] == "yes"
    assert row3["road_label"] == "tunnel"
    assert (result.loc[result["e_id"] != "3", "road_tunnel"] == "no").all()


def test_nti_tunnel_index_preferred_over_hpms(tmp_path, monkeypatch):
    nti_index = tmp_path / "tunnel_index.parquet"
    pd.DataFrame({"e_id": ["1"], "road_tunnel": ["yes"], "tunnel_length_m": [120.0]}).to_parquet(
        nti_index, index=False
    )
    hpms_csv = tmp_path / "hpms.csv"
    pd.DataFrame({"ID": [3], "hpms_STRUCTURE_TYPE": [2]}).to_csv(hpms_csv, index=False)
    ov = tmp_path / "ov.json"
    ov.write_text(
        json.dumps(
            {
                "preprocess": {
                    "nti_tunnel_index_path": str(nti_index),
                    "hpms_lrs_enriched_csv": str(hpms_csv),
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(_OVERRIDES_ENV, str(ov))
    clear_cache()

    result = faf5_network.convert_faf5_links(_toy_faf5_links(), filter_centroids=False)
    assert result.loc[result["e_id"] == "1", "road_tunnel"].iloc[0] == "yes"
    assert result.loc[result["e_id"] == "1", "road_label"].iloc[0] == "tunnel"
    # HPMS would have flagged 3; NTI primary must win (3 stays road).
    assert result.loc[result["e_id"] == "3", "road_tunnel"].iloc[0] == "no"


def test_bridge_and_tunnel_conflict_raises_when_error():
    links = gpd.GeoDataFrame(
        {
            "e_id": ["1"],
            "road_bridge": ["yes"],
            "road_tunnel": ["yes"],
        },
        geometry=[LineString([(0, 0), (1, 0)])],
        crs="EPSG:9311",
    )
    with pytest.raises(ValueError, match="both bridge and tunnel"):
        faf5_network.derive_road_label(links, on_conflict="error")


def test_prefer_tunnel_clears_bridge_on_conflict():
    links = gpd.GeoDataFrame(
        {
            "e_id": ["1"],
            "road_bridge": ["yes"],
            "road_tunnel": ["yes"],
        },
        geometry=[LineString([(0, 0), (1, 0)])],
        crs="EPSG:9311",
    )
    out = faf5_network.derive_road_label(links, on_conflict="prefer_tunnel")
    assert out.iloc[0]["road_label"] == "tunnel"
    assert out.iloc[0]["road_bridge"] == "no"
    assert out.iloc[0]["road_tunnel"] == "yes"


def test_apply_tunnel_index_sets_fraction():
    links = gpd.GeoDataFrame(
        {
            "e_id": ["a", "b"],
            "length": [1000.0, 500.0],
            "road_bridge": ["no", "no"],
        },
        geometry=[
            LineString([(0, 0), (1000, 0)]),
            LineString([(0, 100), (500, 100)]),
        ],
        crs="EPSG:9311",
    )
    idx = pd.DataFrame({"e_id": ["a"], "tunnel_length_m": [200.0]})
    out = faf5_network.apply_tunnel_index(links, idx)
    assert out.loc[out["e_id"] == "a", "road_tunnel"].iloc[0] == "yes"
    assert out.loc[out["e_id"] == "a", "tunnel_length_m"].iloc[0] == pytest.approx(200.0)
    assert out.loc[out["e_id"] == "a", "tunnel_fraction"].iloc[0] == pytest.approx(0.2)
    assert pd.isna(out.loc[out["e_id"] == "b", "tunnel_length_m"].iloc[0])


def test_apply_tunnel_index_excludes_zero_length():
    links = gpd.GeoDataFrame(
        {
            "e_id": ["a"],
            "length": [1000.0],
            "road_bridge": ["no"],
        },
        geometry=[LineString([(0, 0), (1000, 0)])],
        crs="EPSG:9311",
    )
    idx = pd.DataFrame({"e_id": ["a"], "tunnel_length_m": [0.0]})
    out = faf5_network.apply_tunnel_index(links, idx)
    assert out.iloc[0]["road_tunnel"] == "no"
    assert pd.isna(out.iloc[0]["tunnel_length_m"])


def test_apply_tunnel_index_carries_through_bore_geometry():
    links = gpd.GeoDataFrame(
        {
            "e_id": ["a"],
            "length": [1000.0],
            "road_bridge": ["no"],
        },
        geometry=[LineString([(0, 0), (1000, 0)])],
        crs="EPSG:9311",
    )
    idx = pd.DataFrame(
        {
            "e_id": ["a"],
            "tunnel_length_m": [900.0],
            "n_tunnels": [2],
            "tunnel_length_m_min": [880.0],
            "lanes_total": [4],
            "roadway_width_m": [9.0],
        }
    )
    out = faf5_network.apply_tunnel_index(links, idx)
    row = out.iloc[0]
    assert row["tunnel_bores"] == 2
    assert row["tunnel_length_m_min"] == pytest.approx(880.0)
    assert row["tunnel_lanes_total"] == 4
    assert row["tunnel_roadway_width_m"] == pytest.approx(9.0)


def test_apply_tunnel_index_bore_geometry_optional():
    """An index built before bore-geometry columns existed must not error."""
    links = gpd.GeoDataFrame(
        {"e_id": ["a"], "length": [1000.0], "road_bridge": ["no"]},
        geometry=[LineString([(0, 0), (1000, 0)])],
        crs="EPSG:9311",
    )
    idx = pd.DataFrame({"e_id": ["a"], "tunnel_length_m": [200.0]})
    out = faf5_network.apply_tunnel_index(links, idx)
    assert "tunnel_bores" not in out.columns


def test_apply_bridge_index_sets_fraction_and_excludes_bad_geometry():
    links = gpd.GeoDataFrame(
        {
            "e_id": ["1", "2", "3"],
            "length": [1000.0, 2000.0, 500.0],
            "averageWidth": [7.0, 7.0, 7.0],
            "road_tunnel": ["no", "no", "no"],
        },
        geometry=[
            LineString([(0, 0), (1000, 0)]),
            LineString([(0, 0), (2000, 0)]),
            LineString([(0, 100), (500, 100)]),
        ],
        crs="EPSG:9311",
    )
    idx = pd.DataFrame(
        {
            "e_id": ["1", "2", "3"],
            "deck_width_m": [12.5, 0.0, 10.0],  # 2: zero deck → exclude
            "structure_length_m": [40.0, 50.0, float("nan")],  # 3: null length → exclude
        }
    )
    out = faf5_network.apply_bridge_index(links, idx)
    row1 = out.loc[out["e_id"] == "1"].iloc[0]
    assert row1["road_bridge"] == "yes"
    assert row1["structure_length_m"] == pytest.approx(40.0)
    assert row1["bridge_fraction"] == pytest.approx(0.04)
    assert row1["averageWidth"] == pytest.approx(12.5)
    assert out.loc[out["e_id"] == "2", "road_bridge"].iloc[0] == "no"
    assert out.loc[out["e_id"] == "3", "road_bridge"].iloc[0] == "no"
    assert pd.isna(out.loc[out["e_id"] == "2", "bridge_fraction"].iloc[0])


def test_no_bridge_index_configured_defaults_to_no(capsys):
    result = faf5_network.convert_faf5_links(_toy_faf5_links(), filter_centroids=False)
    assert (result["road_bridge"] == "no").all()
    captured = capsys.readouterr()
    assert "NO NBI bridge index configured" in captured.out


def test_bridge_index_flags_matched_links_and_overrides_width(tmp_path, monkeypatch):
    bridge_index_path = tmp_path / "faf5_bridge_index.parquet"
    pd.DataFrame(
        {
            "e_id": ["1"],
            "deck_width_m": [12.5],
            "structure_length_m": [40.0],
            "n_structures": [1],
        }
    ).to_parquet(bridge_index_path, index=False)

    ov = tmp_path / "ov.json"
    ov.write_text(
        json.dumps({"preprocess": {"nbi_bridge_index_path": str(bridge_index_path)}}),
        encoding="utf-8",
    )
    monkeypatch.setenv(_OVERRIDES_ENV, str(ov))
    clear_cache()

    result = faf5_network.convert_faf5_links(_toy_faf5_links(), filter_centroids=False)

    bridge_row = result.loc[result["e_id"] == "1"].iloc[0]
    assert bridge_row["road_bridge"] == "yes"
    assert bridge_row["averageWidth"] == pytest.approx(12.5)
    assert bridge_row["structure_length_m"] == pytest.approx(40.0)
    # toy FAF LENGTH=1 mile ≈ 1609.34 m → fraction 40/1609.34
    assert bridge_row["bridge_fraction"] == pytest.approx(40.0 / 1609.34, rel=1e-3)

    non_bridge = result.loc[result["e_id"] != "1"]
    assert (non_bridge["road_bridge"] == "no").all()
    # Unmatched links keep the lanes-based width estimate, not NBI's.
    assert (non_bridge["averageWidth"] != 12.5).all()


def test_bridge_index_missing_file_falls_back_loudly(tmp_path, monkeypatch, capsys):
    ov = tmp_path / "ov.json"
    ov.write_text(
        json.dumps({"preprocess": {"nbi_bridge_index_path": str(tmp_path / "does_not_exist.parquet")}}),
        encoding="utf-8",
    )
    monkeypatch.setenv(_OVERRIDES_ENV, str(ov))
    clear_cache()

    result = faf5_network.convert_faf5_links(_toy_faf5_links(), filter_centroids=False)
    assert (result["road_bridge"] == "no").all()
    captured = capsys.readouterr()
    assert "NO NBI bridge index configured" in captured.out
