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
