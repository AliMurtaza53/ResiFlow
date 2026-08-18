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
        },
        geometry=[
            LineString([(0, 0), (1000, 0)]),
            LineString([(0, 0), (0, 1000)]),
            LineString([(0, 0), (-1000, 0)]),
        ],
        crs="EPSG:9311",
    )


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
