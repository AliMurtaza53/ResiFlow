"""Tests for resiflow.damage_aggregation: bridges and tunnels carry a whole-structure damage value on
every raster-cell piece of the link, so totals must count them once per link. Road pieces are priced
per piece and are summed. Regression for the Harvey run (2026-11-12): $500B reported vs about $4.9B
with each bridge counted once."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest

from resiflow import damage_aggregation as da


def _rows(spec):
    """spec: list of (e_id, road_label, musd) -> DataFrame with the columns Script 3 writes."""
    return pd.DataFrame(spec, columns=["e_id", "road_label", "direct_damage_mean_musd"])


def test_bridge_repeated_on_every_piece_is_counted_once():
    df = _rows([(1, "bridge", 146.78)] * 161)
    assert da.total_direct_damage_musd(df) == pytest.approx(146.78)


def test_road_pieces_are_summed():
    df = _rows([(7, "road", 0.01), (7, "road", 0.02), (7, "road", 0.03)])
    assert da.total_direct_damage_musd(df) == pytest.approx(0.06)


def test_tunnel_is_counted_once_like_a_bridge():
    df = _rows([(3, "tunnel", 50.0)] * 12)
    assert da.total_direct_damage_musd(df) == pytest.approx(50.0)


def test_mixed_frame_counts_each_asset_correctly():
    df = _rows([(1, "bridge", 10.0)] * 5 + [(2, "tunnel", 4.0)] * 3 + [(3, "road", 0.5)] * 4 + [(4, "road", 0.25)])
    # bridge 10 once + tunnel 4 once + road 3: 4 x 0.5 + road 4: 0.25
    assert da.total_direct_damage_musd(df) == pytest.approx(10.0 + 4.0 + 2.0 + 0.25)


def test_asset_with_unequal_piece_values_takes_the_maximum_not_the_sum():
    df = _rows([(1, "bridge", 2.0), (1, "bridge", 5.0), (1, "bridge", 3.0)])
    assert da.total_direct_damage_musd(df) == pytest.approx(5.0)


def test_label_matching_is_case_and_whitespace_insensitive():
    df = _rows([(1, " Bridge ", 8.0)] * 4)
    assert da.total_direct_damage_musd(df) == pytest.approx(8.0)


def test_frame_without_e_id_falls_back_to_a_row_sum():
    df = pd.DataFrame({"road_label": ["bridge", "bridge"], "direct_damage_mean_musd": [3.0, 3.0]})
    assert da.total_direct_damage_musd(df) == pytest.approx(6.0)


def test_frame_without_road_label_sums_pieces_per_edge():
    df = pd.DataFrame({"e_id": [1, 1, 2], "direct_damage_mean_musd": [1.0, 2.0, 4.0]})
    assert da.total_direct_damage_musd(df) == pytest.approx(7.0)


def test_usd_only_column_is_accepted():
    df = pd.DataFrame({"e_id": [1] * 10, "road_label": ["bridge"] * 10, "direct_damage_mean_usd": [2_000_000.0] * 10})
    assert da.total_direct_damage_musd(df) == pytest.approx(2.0)
    assert da.total_direct_damage_usd(df) == pytest.approx(2_000_000.0)


def test_nan_values_are_treated_as_zero():
    df = _rows([(1, "bridge", float("nan")), (1, "bridge", 4.0), (2, "road", float("nan"))])
    assert da.total_direct_damage_musd(df) == pytest.approx(4.0)


def test_edge_level_damage_matches_the_total():
    df = _rows([(1, "bridge", 10.0)] * 6 + [(2, "road", 0.5)] * 4)
    edges = da.edge_level_damage_musd(df).set_index("e_id")["edge_direct_damage_mean_musd"]
    assert edges.loc[1] == pytest.approx(10.0)
    assert edges.loc[2] == pytest.approx(2.0)
    assert edges.sum() == pytest.approx(da.total_direct_damage_musd(df))


def test_bounds_count_a_bridge_once():
    cols = {
        "e_id": [1] * 20,
        "road_label": ["bridge"] * 20,
        "C1_surface_damage_value_mean": [10.0] * 20,
        "C1_surface_damage_value_min": [8.0] * 20,
        "C1_surface_damage_value_max": [12.0] * 20,
    }
    low, high = da.total_direct_damage_bounds_musd(pd.DataFrame(cols))
    assert (low, high) == (pytest.approx(8.0), pytest.approx(12.0))


def test_consolidated_columns_still_average_the_curve_pair_once():
    row = {"e_id": 5, "road_label": "road", "C1_surface_damage_value_mean": 2.0, "C2_surface_damage_value_mean": 4.0}
    out = da.add_consolidated_damage_columns(pd.DataFrame([row]))
    assert out.loc[0, "direct_damage_mean_musd"] == pytest.approx(3.0)


def test_harvey_pattern_regression_total_is_two_orders_of_magnitude_below_the_row_sum():
    # shape of the Harvey table: 546 bridge links averaging 8.7 $M repeated on ~27 pieces each, plus road pieces
    bridges = [(i, "bridge", 8.7) for i in range(546) for _ in range(27)]
    roads = [(10_000 + i, "road", 0.0001) for i in range(2224) for _ in range(7)]
    df = _rows(bridges + roads)
    row_sum = float(df["direct_damage_mean_musd"].sum())
    total = da.total_direct_damage_musd(df)
    assert row_sum / total > 20
    assert total == pytest.approx(546 * 8.7 + 2224 * 7 * 0.0001)


def test_postprocess_compute_edge_damage_uses_the_corrected_aggregation(monkeypatch, tmp_path):
    """3_postprocess_damage.compute_edge_damage must not sum a bridge's repeated whole-structure value."""
    pytest.importorskip("igraph")  # resiflow.utils needs the full model environment
    script = Path(__file__).resolve().parents[1] / "scripts" / "3_postprocess_damage.py"
    import resiflow.utils as utils

    monkeypatch.setattr(utils, "load_config", lambda *a, **k: {"paths": {"soge_clusters": str(tmp_path / "soge")}})
    spec = importlib.util.spec_from_file_location("postprocess_damage_under_test", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    df = pd.DataFrame(
        {
            "e_id": [1] * 30 + [2] * 3,
            "road_label": ["bridge"] * 30 + ["road"] * 3,
            "C1_surface_damage_value_mean": [10_000_000.0 / 1e6] * 30 + [0.1] * 3,
        }
    )
    edges = mod.compute_edge_damage(df).set_index("e_id")["edge_direct_damage_mean_musd"]
    assert edges.loc[1] == pytest.approx(10.0)
    assert edges.loc[2] == pytest.approx(0.3)
