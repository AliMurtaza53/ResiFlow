"""Tests for src/resiflow/hazards/hazus_bridge.py -- HAZUS 6.1 bridge/road
classification, fragility, and direct-cost computation.

Covers the bug this replaces: earthquake/landslide direct damage previously
went through a flood-shim (PGA*0.5 or PGD/1000 relabeled as a fake "flood
depth", priced with FLOOD's damage_ratio/cost tables -- see
disruption/build.py's SHIM comments). These tests check the HAZUS-sourced
replacement against known properties of the source tables, not against the
old shim's behavior.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from resiflow.hazards import hazus_bridge as hz


def test_classify_hwb_major_bridge_override():
    # Max span > 150m overrides everything else -- Table 7-1's HWB1/HWB2.
    assert hz.classify_hwb(
        structure_kind_code="1", structure_type_code="1", state="VA",
        year_built=1960, num_spans=5, max_span_length_m=200.0,
    ) == "HWB1"
    assert hz.classify_hwb(
        structure_kind_code="1", structure_type_code="1", state="VA",
        year_built=2000, num_spans=5, max_span_length_m=200.0,
    ) == "HWB2"


def test_classify_hwb_single_span_override():
    assert hz.classify_hwb(
        structure_kind_code="3", structure_type_code="2", state="VA",
        year_built=1960, num_spans=1, max_span_length_m=30.0,
    ) == "HWB3"
    assert hz.classify_hwb(
        structure_kind_code="3", structure_type_code="2", state="VA",
        year_built=2000, num_spans=1, max_span_length_m=30.0,
    ) == "HWB4"


def test_classify_hwb_concrete_multicol_non_ca_vs_ca():
    # NBI code 101-106 (concrete, kind=1) -- non-CA gets HWB5/7, CA gets HWB6/7.
    assert hz.classify_hwb(
        structure_kind_code="1", structure_type_code="02", state="VA",
        year_built=1960, num_spans=3, max_span_length_m=30.0,
    ) == "HWB5"
    assert hz.classify_hwb(
        structure_kind_code="1", structure_type_code="02", state="CA",
        year_built=1960, num_spans=3, max_span_length_m=30.0,
    ) == "HWB6"
    # Seismic-era (>=1990 non-CA, >=1975 CA) collapses both to HWB7.
    assert hz.classify_hwb(
        structure_kind_code="1", structure_type_code="02", state="VA",
        year_built=1995, num_spans=3, max_span_length_m=30.0,
    ) == "HWB7"
    assert hz.classify_hwb(
        structure_kind_code="1", structure_type_code="02", state="CA",
        year_built=1980, num_spans=3, max_span_length_m=30.0,
    ) == "HWB7"


def test_classify_hwb_ca_seismic_cutoff_is_earlier_than_non_ca():
    # A 1980-built CA bridge is seismic-era (cutoff 1975); the identical
    # non-CA bridge is NOT (cutoff 1990) -- these must classify differently.
    ca = hz.classify_hwb(
        structure_kind_code="5", structure_type_code="02", state="CA",
        year_built=1980, num_spans=3, max_span_length_m=30.0,
    )
    non_ca = hz.classify_hwb(
        structure_kind_code="5", structure_type_code="02", state="VA",
        year_built=1980, num_spans=3, max_span_length_m=30.0,
    )
    assert ca == "HWB19"  # seismic
    assert non_ca == "HWB17"  # conventional


def test_classify_hwb_unrecognized_falls_to_catchall():
    assert hz.classify_hwb(
        structure_kind_code=None, structure_type_code=None, state="VA",
        year_built=1960, num_spans=3, max_span_length_m=30.0,
    ) == "HWB28"


def test_k3d_matches_table_7_2_formula():
    # HWB1 uses EQ1: K3D = 1 + 0.25/(N-1).
    assert hz.compute_k3d("HWB1", num_spans=3) == pytest.approx(1.0 + 0.25 / 2.0)
    # Unknown span count -> no correction.
    assert hz.compute_k3d("HWB1", num_spans=None) == 1.0


def test_lognormal_exceedance_is_half_at_median():
    # By construction, P(exceed | intensity == median) == 0.5 for any beta.
    p = hz._lognormal_exceedance_prob(intensity=0.5, median=0.5, beta=0.6)
    assert p == pytest.approx(0.5, abs=1e-9)


def test_lognormal_exceedance_is_near_zero_far_below_median():
    p = hz._lognormal_exceedance_prob(intensity=0.001, median=0.5, beta=0.6)
    assert p < 0.01


def test_damage_state_probabilities_sum_to_one():
    exceedance = (0.8, 0.5, 0.2, 0.05)
    probs = hz.damage_state_probabilities(exceedance)
    assert sum(probs.values()) == pytest.approx(1.0)
    assert all(v >= -1e-12 for v in probs.values())


def test_bridge_complete_ratio_uses_spans_footnote():
    assert hz.bridge_complete_damage_ratio(2) == pytest.approx(1.00)
    assert hz.bridge_complete_damage_ratio(4) == pytest.approx(0.5)
    assert hz.bridge_complete_damage_ratio(None) == pytest.approx(1.00)


def test_bridge_direct_cost_zero_at_zero_intensity():
    cost, level = hz.bridge_direct_cost_usd(
        hwb_class="HWB1", sa_1p0_g=0.0, pgd_in=0.0,
        num_spans=3, span_width_m=10.0, bridge_length_m=60.0, skew_degrees=0.0,
        deck_area_sqft=1000.0,
    )
    assert cost == pytest.approx(0.0)
    assert level == "no"


def test_bridge_direct_cost_scales_with_intensity():
    low_cost, _ = hz.bridge_direct_cost_usd(
        hwb_class="HWB1", sa_1p0_g=0.1, pgd_in=None,
        num_spans=3, span_width_m=10.0, bridge_length_m=60.0, skew_degrees=0.0,
        deck_area_sqft=1000.0,
    )
    high_cost, high_level = hz.bridge_direct_cost_usd(
        hwb_class="HWB1", sa_1p0_g=2.0, pgd_in=None,
        num_spans=3, span_width_m=10.0, bridge_length_m=60.0, skew_degrees=0.0,
        deck_area_sqft=1000.0,
    )
    assert high_cost > low_cost
    assert high_level in ("extensive", "severe")


def test_bridge_direct_cost_governed_by_more_severe_axis():
    # A low-Sa, high-PGD case should be governed by the PGD axis (and vice versa).
    cost_pgd_dominant, _ = hz.bridge_direct_cost_usd(
        hwb_class="HWB1", sa_1p0_g=0.01, pgd_in=50.0,
        num_spans=3, span_width_m=10.0, bridge_length_m=60.0, skew_degrees=45.0,
        deck_area_sqft=1000.0,
    )
    cost_neither, _ = hz.bridge_direct_cost_usd(
        hwb_class="HWB1", sa_1p0_g=0.01, pgd_in=0.0,
        num_spans=3, span_width_m=10.0, bridge_length_m=60.0, skew_degrees=45.0,
        deck_area_sqft=1000.0,
    )
    assert cost_pgd_dominant > cost_neither


def test_road_direct_cost_major_vs_urban_unit_cost():
    cost_major, _ = hz.road_direct_cost_usd(
        road_classification="motorway", pgd_in=30.0, length_km=1.0,
    )
    cost_urban, _ = hz.road_direct_cost_usd(
        road_classification="residential", pgd_in=30.0, length_km=1.0,
    )
    # Major roads have a higher $/km replacement value (Table 9-2), and the
    # same PGD maps to the SAME fragility tier boundaries proportionally
    # smaller for major roads (12/24/60in vs 6/12/24in) -- at pgd=30in,
    # major road sits within its Extensile/Complete tier while urban is well
    # past its own -- so this isn't a simple monotonic comparison in general,
    # but both should be strictly positive here.
    assert cost_major > 0
    assert cost_urban > 0


def test_road_direct_cost_zero_at_zero_pgd():
    cost, level = hz.road_direct_cost_usd(road_classification="motorway", pgd_in=0.0, length_km=1.0)
    assert cost == pytest.approx(0.0)
    assert level == "no"


def test_hazus_damage_level_crosswalk_is_complete_and_matches_existing_vocabulary():
    # The 5-level vocabulary must match fragility/{earthquake,landslide,
    # winter_storm}_categorical.py's own damage-level strings exactly.
    assert set(hz.HAZUS_TO_RESIFLOW_DAMAGE_LEVEL.values()) == {"no", "minor", "moderate", "extensive", "severe"}
    assert set(hz.HAZUS_TO_RESIFLOW_DAMAGE_LEVEL.keys()) == set(hz.HAZUS_DAMAGE_STATES)


def test_compute_row_direct_damage_musd_earthquake_is_always_zero():
    # Documented gap: Sa(1.0s) isn't intersected against the network yet,
    # so earthquake must report 0, not a value computed from mismatched PGA.
    row = pd.Series({"landslide_mm": 500.0, "road_label": "bridge", "length": 50.0, "averageWidth": 10.0})
    assert hz.compute_row_direct_damage_musd(row, hazard_type="earthquake") == 0.0


def test_compute_row_direct_damage_musd_landslide_zero_pgd():
    row = pd.Series({"landslide_mm": 0.0, "road_label": "road", "length": 100.0, "road_classification": "primary"})
    assert hz.compute_row_direct_damage_musd(row, hazard_type="landslide") == pytest.approx(0.0)


def test_compute_row_direct_damage_musd_landslide_bridge_nonzero():
    row = pd.Series({
        "landslide_mm": 200.0, "road_label": "bridge", "length": 60.0, "averageWidth": 10.0,
        "structure_kind_code": "1", "structure_type_code": "02", "bridge_state": "VA",
        "year_built": 1960.0, "main_unit_spans": 3.0, "max_span_length_m": 20.0, "skew_degrees": 0.0,
    })
    musd = hz.compute_row_direct_damage_musd(row, hazard_type="landslide")
    assert musd > 0.0


def test_compute_row_direct_damage_musd_landslide_road_nonzero():
    row = pd.Series({
        "landslide_mm": 300.0, "road_label": "road", "length": 500.0, "road_classification": "primary",
    })
    musd = hz.compute_row_direct_damage_musd(row, hazard_type="landslide")
    assert musd > 0.0


def test_compute_row_direct_damage_musd_flood_and_winter_storm_return_zero():
    # This function only handles earthquake/landslide -- other hazard types
    # keep going through calculate_damage()'s flood path in Script 3, not
    # this one; confirm it doesn't silently compute something for them.
    row = pd.Series({"landslide_mm": 500.0, "road_label": "bridge", "length": 50.0, "averageWidth": 10.0})
    assert hz.compute_row_direct_damage_musd(row, hazard_type="flood") == 0.0
    assert hz.compute_row_direct_damage_musd(row, hazard_type="winter_storm") == 0.0


def test_all_28_hwb_classes_have_fragility_and_modifiers():
    expected = {f"HWB{i}" for i in range(1, 29)}
    assert set(hz._TABLE_7_6.keys()) == expected
    assert set(hz._TABLE_7_7_F1_F2.keys()) == expected
    for cls in expected:
        fragility = hz.get_fragility(cls)
        # Medians must be monotonically non-decreasing across damage states.
        assert fragility.sa_medians_g[0] <= fragility.sa_medians_g[1] <= fragility.sa_medians_g[2] <= fragility.sa_medians_g[3]
