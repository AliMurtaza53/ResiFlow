"""Tests for T30-based bridge replacement-value flood costing."""

from __future__ import annotations

import pandas as pd
import pytest

from resiflow.hazards.bridge_cost_t30 import (
    bridge_direct_damage_usd,
    bridge_replacement_value_usd,
    bridge_unit_cost_usd_per_sqft,
    load_t30,
)
from resiflow.us_states import state_name_from_fips_or_usps


def test_real_t30_table_loads_with_104_rows():
    t30 = load_t30()
    assert len(t30) == 104
    assert set(t30["bridge_class"].unique()) == {"NHS", "non-NHS"}


def test_fips_preferred_over_usps():
    fips = pd.Series(["06", None])
    usps = pd.Series(["TX", "BC"])  # BC = Canadian province, unresolvable
    names = state_name_from_fips_or_usps(fips, usps)
    assert names.iloc[0] == "California"  # from FIPS, not USPS "TX"
    assert pd.isna(names.iloc[1])  # Canadian province -- not guessed


def test_unit_cost_join_real_known_values():
    state_name = pd.Series(["California", "California"])
    on_nhs = pd.Series([True, False])
    costs = bridge_unit_cost_usd_per_sqft(state_name, on_nhs)
    assert costs.iloc[0] == pytest.approx(465)
    assert costs.iloc[1] == pytest.approx(483)


def test_unit_cost_join_unmatched_state_is_nan_not_fabricated():
    state_name = pd.Series(["Ontario"])  # Canadian province, not in T30
    on_nhs = pd.Series([True])
    costs = bridge_unit_cost_usd_per_sqft(state_name, on_nhs)
    assert costs.isna().all()


def test_replacement_value_area_times_unit_cost():
    # 10m wide x 50m long deck = 500 sqm = 5381.955 sqft; unit cost $465/sqft
    value = bridge_replacement_value_usd(
        pd.Series([10.0]), pd.Series([50.0]), pd.Series([465.0])
    )
    assert value.iloc[0] == pytest.approx(500 * 10.763910417 * 465.0)


def test_direct_damage_scales_by_hazus_bridge_ratio():
    assert bridge_direct_damage_usd(1_000_000.0, "no") == pytest.approx(0.0)
    assert bridge_direct_damage_usd(1_000_000.0, "minor") == pytest.approx(30_000.0)
    assert bridge_direct_damage_usd(1_000_000.0, "moderate") == pytest.approx(80_000.0)
    assert bridge_direct_damage_usd(1_000_000.0, "extensive") == pytest.approx(250_000.0)


def test_direct_damage_severe_uses_span_aware_complete_ratio():
    # bridge_complete_damage_ratio: 2/spans when spans > 2, else 1.00
    full = bridge_direct_damage_usd(1_000_000.0, "severe", num_spans=1)
    assert full == pytest.approx(1_000_000.0)
    partial = bridge_direct_damage_usd(1_000_000.0, "severe", num_spans=4)
    assert partial == pytest.approx(500_000.0)


def test_direct_damage_nan_replacement_value_propagates_nan():
    assert pd.isna(bridge_direct_damage_usd(float("nan"), "minor"))
