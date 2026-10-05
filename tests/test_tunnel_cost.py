"""Tests for the Rostami et al. (2013) tunnel costing module.

The doc/BRDIGE_COSTS.md validation example (L=1km, lanes=2, bores=1,
default geometry -> D=10.7536m, cost ~= $78.67 million 2008 USD) is the
primary correctness check.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from resiflow.hazards.tunnel_cost import (
    construction_value_usd,
    derive_tunnel_geometry,
    rostami_bore_cost_million_2008usd,
    tunnel_direct_damage_usd,
)

PARAMS_PATH = (
    Path(__file__).resolve().parents[1] / "parameters" / "tables" / "tunnel_cost_parameters.csv"
)


@pytest.fixture
def params_table() -> pd.DataFrame:
    return pd.read_csv(PARAMS_PATH)


def test_real_parameter_table_has_highway_conventional_row(params_table):
    row = params_table.loc[params_table["model_id"] == "highway_conventional"]
    assert len(row) == 1
    assert row.iloc[0]["source_doi"] == "10.1016/j.tust.2012.08.002"


def test_doc_validation_example_lanes_only_default_geometry(params_table):
    """docs/BRDIGE_COSTS.md's own worked example."""
    geometry = derive_tunnel_geometry(
        physical_asset_id="toy",
        tunnel_length_m=1000.0,
        n_bores=1,
        lanes_total=2,
        roadway_width_m=None,
        params=params_table.loc[params_table["model_id"] == "highway_conventional"].iloc[0],
    )
    assert geometry.span_or_diameter_m == pytest.approx(10.7536, abs=1e-4)
    assert geometry.geometry_basis == "estimated_from_lanes"

    result = construction_value_usd(geometry, params_table=params_table)
    assert result["construction_value_usd"] == pytest.approx(78.67e6, rel=1e-3)
    assert result["escalation_factor"] == 1.0
    assert result["bores"] == 1


def test_clear_width_preferred_over_lane_estimate(params_table):
    params = params_table.loc[params_table["model_id"] == "highway_conventional"].iloc[0]
    from_width = derive_tunnel_geometry(
        physical_asset_id="real",
        tunnel_length_m=2724.0,
        n_bores=1,
        lanes_total=2,
        roadway_width_m=8.0,
        params=params,
    )
    assert from_width.geometry_basis == "clear_width"
    # 8.0 + 2*0.5 lining = 9.0, NOT the lane-count estimate (10.7536)
    assert from_width.span_or_diameter_m == pytest.approx(9.0)


def test_two_bore_tunnel_sums_bore_costs(params_table):
    params = params_table.loc[params_table["model_id"] == "highway_conventional"].iloc[0]
    one_bore = derive_tunnel_geometry(
        physical_asset_id="x", tunnel_length_m=1000.0, n_bores=1, lanes_total=2,
        roadway_width_m=None, params=params,
    )
    two_bore = derive_tunnel_geometry(
        physical_asset_id="x", tunnel_length_m=1000.0, n_bores=2, lanes_total=4,
        roadway_width_m=None, params=params,
    )
    # Same geometry per bore (4 lanes / 2 bores = 2 lanes/bore, same as the
    # 1-bore case) -- total construction value should be exactly 2x.
    cost_one = construction_value_usd(one_bore, params_table=params_table)["construction_value_usd"]
    cost_two = construction_value_usd(two_bore, params_table=params_table)["construction_value_usd"]
    assert cost_two == pytest.approx(2 * cost_one)


def test_unequal_bore_lengths_flagged(params_table):
    params = params_table.loc[params_table["model_id"] == "highway_conventional"].iloc[0]
    geometry = derive_tunnel_geometry(
        physical_asset_id="x", tunnel_length_m=900.0, tunnel_length_m_min=600.0,
        n_bores=2, lanes_total=4, roadway_width_m=None, params=params,
    )
    assert "unequal_bore_lengths_used_longest" in geometry.assumption_flags


def test_nonpositive_geometry_raises_not_zeros(params_table):
    params = params_table.loc[params_table["model_id"] == "highway_conventional"].iloc[0]
    with pytest.raises(ValueError):
        derive_tunnel_geometry(
            physical_asset_id="x", tunnel_length_m=0.0, n_bores=1,
            lanes_total=2, roadway_width_m=None, params=params,
        )
    with pytest.raises(ValueError):
        derive_tunnel_geometry(
            physical_asset_id="x", tunnel_length_m=1000.0, n_bores=0,
            lanes_total=2, roadway_width_m=None, params=params,
        )


def test_subway_model_never_substituted_for_highway(params_table):
    """A highway tunnel must error, not silently fall back to a subway
    equation, if the highway row were ever missing."""
    highway_only = params_table.loc[params_table["application"] == "highway"]
    stripped = highway_only.iloc[0:0]  # empty but same columns
    params = highway_only.iloc[0]
    geometry = derive_tunnel_geometry(
        physical_asset_id="x", tunnel_length_m=1000.0, n_bores=1,
        lanes_total=2, roadway_width_m=None, params=params,
    )
    with pytest.raises(ValueError, match="no tunnel_cost_parameters.csv row"):
        construction_value_usd(geometry, params_table=stripped)


def test_direct_damage_uses_hazus_tunnel_ratio_by_state():
    # HAZUS Table 11-10 tunnel ratios: none=0, slight(minor)=0.01,
    # moderate=0.30, extensive=0.70, complete(severe)=1.00.
    assert tunnel_direct_damage_usd(1_000_000.0, "no") == pytest.approx(0.0)
    assert tunnel_direct_damage_usd(1_000_000.0, "minor") == pytest.approx(10_000.0)
    assert tunnel_direct_damage_usd(1_000_000.0, "severe") == pytest.approx(1_000_000.0)


def test_direct_damage_rejects_unknown_damage_level():
    with pytest.raises(ValueError):
        tunnel_direct_damage_usd(1_000_000.0, "catastrophic")
