"""Tests for FAF5 local path resolution."""

from __future__ import annotations

from pathlib import Path

from resiflow.faf5_paths import resolve_faf5_data_root, resolve_regional_od_path, truck_factor_paths


def test_resolve_faf5_data_root_from_soge_sibling(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("NIRD_FAF5_DATA_ROOT", raising=False)
    data_root = tmp_path / "data"
    soge = data_root / "soge_clusters"
    faf5 = data_root / "faf5_data"
    soge.mkdir(parents=True)
    faf5.mkdir()
    (faf5 / "county_disaggregation_factors").mkdir()
    assert resolve_faf5_data_root(soge) == faf5


def test_resolve_regional_od_faf71_layout(tmp_path: Path) -> None:
    faf5 = tmp_path / "faf5_data"
    csv_path = faf5 / "FAF5.7.1" / "FAF5.7.1.csv"
    csv_path.parent.mkdir(parents=True)
    csv_path.write_text("dms_orig,dms_dest,sctg2,trade_type,tons_2022,dms_mode\n", encoding="utf-8")
    assert resolve_regional_od_path(faf5) == csv_path


def test_truck_factor_paths(tmp_path: Path) -> None:
    faf5 = tmp_path / "faf5_data"
    factors = faf5 / "county_disaggregation_factors"
    factors.mkdir(parents=True)
    origin, destination = truck_factor_paths(faf5)
    assert origin.name == "truck_origin_factors.csv"
    assert destination.name == "truck_destination_factors.csv"
