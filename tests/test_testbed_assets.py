"""Synthetic FAF-like asset attributes for the testbeds, and the loud failure of sourced costing when attributes are missing."""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from resiflow.testbeds import load_testbed
from resiflow.testbeds.assets import (
    HPMS_FCLASS_BY_ROAD_CLASS,
    apply_synthetic_asset_attributes,
    hpms_fclass_from_road_class,
    required_columns_for_sourced_costs,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _links(labels, classes=None):
    n = len(labels)
    return pd.DataFrame(
        {
            "e_id": [f"e{i}" for i in range(n)],
            "road_label": labels,
            "road_classification": classes or ["tertiary"] * n,
            "length": [100.0 + 50 * i for i in range(n)],
            "lanes": [2] * n,
        }
    )


def test_hpms_rule_maps_the_documented_classes():
    s = pd.Series(["motorway", "freeway", "trunk", "primary", "secondary", "tertiary", "unclassified", "local", "local_access"])
    assert hpms_fclass_from_road_class(s).tolist() == [1, 1, 2, 3, 4, 5, 6, 7, 7]
    assert set(HPMS_FCLASS_BY_ROAD_CLASS.values()) == {1, 2, 3, 4, 5, 6, 7}


def test_unknown_road_class_raises_instead_of_becoming_local():
    with pytest.raises(ValueError, match="no HPMS F-class rule"):
        hpms_fclass_from_road_class(pd.Series(["tertiary", "goat_track"]))


def test_attributes_are_added_for_roads_and_bridges():
    out = apply_synthetic_asset_attributes(
        _links(["road", "bridge"], ["primary", "tertiary"]), state_fips="46", state_usps="SD", urban_code="82252"
    )
    assert out["hpms_fclass"].tolist() == [3, 5]
    assert set(out["STATE"]) == {"SD"} and set(out["bridge_state"]) == {"46"} and set(out["urban_code"]) == {"82252"}
    assert out.loc[0, "nhs_designation"] == "NHS" and pd.isna(out.loc[1, "nhs_designation"])
    bridge = out.loc[1]
    assert bridge["structure_length_m"] == pytest.approx(150.0)
    assert bridge["main_unit_spans"] == 5 and bridge["averageWidth"] == pytest.approx(3.65 * 2 + 2.0)
    assert pd.isna(out.loc[0, "structure_length_m"])
    assert out["synthetic_assets"].all()


def test_tunnel_columns_are_assigned_only_to_tunnels():
    out = apply_synthetic_asset_attributes(_links(["road", "tunnel"]), state_fips="06", state_usps="CA", urban_code="51445")
    assert out.loc[1, "tunnel_bores"] == 2 and out.loc[1, "tunnel_lanes_total"] == 4
    assert out.loc[1, "tunnel_length_m"] == pytest.approx(150.0)
    assert pd.isna(out.loc[0, "tunnel_bores"])


def test_existing_values_are_never_overwritten():
    links = _links(["bridge"])
    links["hpms_fclass"] = 2
    links["structure_length_m"] = 999.0
    out = apply_synthetic_asset_attributes(links, state_fips="46", state_usps="SD", urban_code="82252")
    assert out.loc[0, "hpms_fclass"] == 2 and out.loc[0, "structure_length_m"] == 999.0


def test_missing_input_columns_raise():
    with pytest.raises(ValueError, match="missing columns"):
        apply_synthetic_asset_attributes(pd.DataFrame({"e_id": ["a"]}), state_fips="46", state_usps="SD", urban_code="82252")


def test_required_columns_depend_on_the_asset_types_present():
    assert "bridge" not in required_columns_for_sourced_costs(["road"])
    need = required_columns_for_sourced_costs(["road", "bridge", "tunnel"])
    assert {"road", "bridge", "tunnel", "all"} <= set(need)
    assert "hpms_fclass" in need["road"] and "structure_length_m" in need["bridge"] and "tunnel_bores" not in need["tunnel"]


@pytest.mark.parametrize("testbed,state_fips,usps,name_fragment", [("sioux_falls", "46", "SD", "Sioux Falls"), ("anaheim", "06", "CA", "Anaheim")])
def test_testbed_specs_carry_a_real_state_and_census_urban_area(testbed, state_fips, usps, name_fragment):
    spec = load_testbed(testbed)
    assert (spec.state_fips, spec.state_usps) == (state_fips, usps)
    t39 = pd.read_csv(REPO_ROOT / "parameters" / "tables" / "T39_census_urban_area_population_2010.csv", comment="#", dtype=str)
    row = t39.loc[t39["uace_code"].str.zfill(5) == spec.urban_code.zfill(5)]
    assert len(row) == 1, f"urban code {spec.urban_code} not in T39"
    assert name_fragment in row.iloc[0].astype(str).str.cat(sep=" ")


def test_sourced_costing_names_every_missing_attribute():
    pytest.importorskip("igraph")  # script 3 needs the full model environment
    scripts = REPO_ROOT / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    damage = import_module("3_damage_analysis")
    links = pd.DataFrame(
        {
            "road_label": ["road", "bridge"],
            "length": [10.0, 20.0],
            "lanes": [1, 1],
            "urban": [1, 1],
            "flood_depth_surface": [1.0, 1.0],
            "flood_depth_river": [0.0, 0.0],
        }
    )
    with pytest.raises(ValueError) as exc:
        damage.calculate_damage_sourced(links, {})
    message = str(exc.value)
    assert "hpms_fclass" in message and "structure_length_m" in message and "averageWidth" in message
