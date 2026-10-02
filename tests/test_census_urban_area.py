"""Tests for census_urban_area.py's FAF5 Urban_Code -> real population/tier join."""

from __future__ import annotations

import pandas as pd
import pytest

from resiflow.census_urban_area import urban_area_profile


@pytest.fixture()
def t39_root(tmp_path):
    tables_dir = tmp_path / "tables"
    tables_dir.mkdir()
    (tables_dir / "manifest.csv").write_text(
        "file,audit_matrix_rows,status,note\n"
        "T39_census_urban_area_population_2010.csv,n/a,SOURCED,test fixture\n",
        encoding="utf-8",
    )
    # Mirrors the real table's int-round-trip-loses-leading-zeros quirk
    # (uace_code written zero-padded, read back as a bare int) on purpose.
    (tables_dir / "T39_census_urban_area_population_2010.csv").write_text(
        "# T39 test fixture\n"
        "uace_code,name,population_2010,housing_units_2010,lsadc,census_area_type,"
        "hpms_urban_size_tier,nchrp825_population_gt_250k\n"
        "63217,New York--Newark NY--NJ--CT,18351295,7074896,75,urbanized_area,major_urbanized,True\n"
        "217,Smallville XX,65000,28000,75,urbanized_area,small_urbanized,False\n"
        "309,Tinytown XX,12000,5000,76,urban_cluster,small_urban,False\n",
        encoding="utf-8",
    )
    return tmp_path


def test_real_uace_code_resolves_tier_and_population(t39_root):
    codes = pd.Series(["63217", "00217"])
    out = urban_area_profile(codes, params_root=t39_root)
    assert out["hpms_urban_size_tier"].tolist() == ["major_urbanized", "small_urbanized"]
    assert out["population_2010"].iloc[0] == pytest.approx(18351295)
    assert out["nchrp825_population_gt_250k"].tolist() == [True, False]


def test_small_urban_sentinel_99998(t39_root):
    out = urban_area_profile(pd.Series(["99998"]), params_root=t39_root)
    assert out["hpms_urban_size_tier"].iloc[0] == "small_urban"
    assert pd.isna(out["population_2010"].iloc[0])  # no fabricated population
    assert out["nchrp825_population_gt_250k"].iloc[0] == False  # noqa: E712


def test_rural_sentinel_and_missing(t39_root):
    out = urban_area_profile(pd.Series(["99999", None]), params_root=t39_root)
    assert out["hpms_urban_size_tier"].tolist() == ["rural", "rural"]
    assert out["population_2010"].isna().all()


def test_unknown_code_resolves_to_missing_not_a_guess(t39_root):
    out = urban_area_profile(pd.Series(["00001"]), params_root=t39_root)
    assert pd.isna(out["hpms_urban_size_tier"].iloc[0])
    assert pd.isna(out["population_2010"].iloc[0])
