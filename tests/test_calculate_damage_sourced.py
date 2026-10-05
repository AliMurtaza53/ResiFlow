"""Integration test for scripts/3_damage_analysis.py's calculate_damage_sourced():
real T24 CP25 (roads) + T30 (bridges) + Rostami et al. (tunnels) flood costing,
gated behind vulnerability.use_sourced_asset_costs."""

from __future__ import annotations

import sys
from importlib import import_module
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

_damage = import_module("3_damage_analysis")
calculate_damage_sourced = _damage.calculate_damage_sourced
create_damage_curves = _damage.create_damage_curves

_SQM_TO_SQFT = 10.763910417


@pytest.fixture
def linear_damage_curves():
    """A deliberately simple ratio table: every curve is fraction = depth/10
    for depth in [0, 10], so a depth of 5 always gives exactly 0.5 -- makes
    expected values easy to hand-verify regardless of which curve pair
    compute_damage_fraction selects."""
    ratio_df = pd.DataFrame(
        {
            "intensity": [0.0, 10.0],
            "C1": [0.0, 1.0], "C2": [0.0, 1.0],
            "C3": [0.0, 1.0], "C4": [0.0, 1.0],
            "C5": [0.0, 1.0], "C6": [0.0, 1.0],
        }
    )
    return create_damage_curves(ratio_df)


def _base_row(**overrides):
    row = {
        "flood_depth_surface": 5.0,
        "flood_depth_river": 0.0,
        "damage_level_surface": "moderate",
        "damage_level_river": "no",
        "road_label": "road",
        "road_classification": "motorway",
        "trunk_road": True,
        "hpms_fclass": 1,
        "urban": 0,
        "hpms_urban_size_tier": pd.NA,
        "nhs_designation": 1,
        "length": 1609.344,  # 1 mile
        "lanes": 2,
        "averageWidth": 3.65,
        "structure_length_m": np.nan,
        "main_unit_spans": np.nan,
        "bridge_state": None,
        "STATE": None,
        "tunnel_length_m": np.nan,
        "tunnel_length_m_min": np.nan,
        "tunnel_bores": np.nan,
        "tunnel_lanes_total": np.nan,
        "tunnel_roadway_width_m": np.nan,
        "e_id": "e1",
    }
    row.update(overrides)
    return row


def test_road_uses_t24_cp25_times_lane_miles_times_fraction(linear_damage_curves):
    df = pd.DataFrame([_base_row(road_label="road", e_id="road1")])
    out = calculate_damage_sourced(df, linear_damage_curves)
    # Rural Interstate, default terrain (Rolling), Total Reconstruct Existing
    # Lane = 2041 $K/lane-mi -> $2,041,000/lane-mile x 2 lane-miles x 0.5
    expected = 2041 * 1000.0 * 2.0 * 0.5
    assert out.loc[0, "direct_damage_mean_usd"] == pytest.approx(expected, rel=1e-6)


def test_bridge_uses_t30_times_deck_area_times_hazus_ratio(linear_damage_curves):
    df = pd.DataFrame(
        [
            _base_row(
                road_label="bridge",
                bridge_state="06",  # CA FIPS
                nhs_designation=1,
                structure_length_m=50.0,
                averageWidth=10.0,
                damage_level_surface="moderate",
                e_id="bridge1",
            )
        ]
    )
    out = calculate_damage_sourced(df, linear_damage_curves)
    # CA NHS = $465/ft2; 50m x 10m deck; HAZUS bridge moderate ratio = 0.08
    replacement_value = 50.0 * 10.0 * _SQM_TO_SQFT * 465.0
    expected = replacement_value * 0.08
    assert out.loc[0, "direct_damage_mean_usd"] == pytest.approx(expected, rel=1e-6)


def test_tunnel_uses_rostami_construction_value_times_hazus_ratio(linear_damage_curves):
    df = pd.DataFrame(
        [
            _base_row(
                road_label="tunnel",
                tunnel_length_m=1000.0,
                tunnel_bores=1,
                tunnel_lanes_total=2,
                damage_level_surface="severe",
                e_id="tunnel1",
            )
        ]
    )
    out = calculate_damage_sourced(df, linear_damage_curves)
    # docs/BRDIGE_COSTS.md's own validation example: 1km, 2 lanes, 1 bore,
    # default geometry -> ~$78.67M construction value; HAZUS tunnel
    # "complete" (severe) ratio = 1.00 -> full construction value.
    assert out.loc[0, "direct_damage_mean_usd"] == pytest.approx(78.67e6, rel=1e-3)


def test_bridge_missing_state_match_contributes_zero_not_nan(linear_damage_curves):
    df = pd.DataFrame(
        [
            _base_row(
                road_label="bridge",
                bridge_state=None,
                STATE="BC",  # Canadian province, unresolvable against T30
                structure_length_m=50.0,
                averageWidth=10.0,
                e_id="bridge_ca",
            )
        ]
    )
    out = calculate_damage_sourced(df, linear_damage_curves)
    assert out.loc[0, "direct_damage_mean_usd"] == pytest.approx(0.0)


def test_mixed_batch_sums_independently(linear_damage_curves):
    df = pd.DataFrame(
        [
            _base_row(road_label="road", e_id="road1"),
            _base_row(
                road_label="bridge", bridge_state="06", structure_length_m=50.0,
                averageWidth=10.0, e_id="bridge1",
            ),
        ]
    )
    out = calculate_damage_sourced(df, linear_damage_curves)
    assert len(out) == 2
    assert (out["direct_damage_mean_usd"] > 0).all()
    assert out["direct_damage_mean_musd"].equals(out["direct_damage_mean_usd"] / 1_000_000.0)
