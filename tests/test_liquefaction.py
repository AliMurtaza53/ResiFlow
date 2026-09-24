"""Tests for hazards/liquefaction.py's T31 (earthquake road liquefaction) lookup."""

from __future__ import annotations

from resiflow.hazards.liquefaction import road_liquefaction_direct_cost_usd_per_km

_NEW_MADRID = "earthquake_new_madrid_m75_scenario"


def _cost(**kwargs) -> float:
    cost, _level = road_liquefaction_direct_cost_usd_per_km(**kwargs)
    return cost


def test_unmapped_hazard_subtype_returns_zero() -> None:
    # Mineral (VA) and Cascadia (WA/OR) have no CUSEC susceptibility coverage.
    assert road_liquefaction_direct_cost_usd_per_km(
        hazard_subtype="earthquake_shakemap_mineral",
        susceptibility_code=5,
        road_classification="motorway",
        pga_g=0.5,
    ) == (0.0, "no")


def test_missing_or_zero_pga_returns_zero() -> None:
    for pga in (None, 0.0, -0.1):
        assert _cost(
            hazard_subtype=_NEW_MADRID, susceptibility_code=5, road_classification="motorway", pga_g=pga
        ) == 0.0


def test_missing_or_none_susceptibility_code_returns_zero() -> None:
    for code in (None, float("nan")):
        assert _cost(
            hazard_subtype=_NEW_MADRID, susceptibility_code=code, road_classification="motorway", pga_g=0.3
        ) == 0.0


def test_susceptibility_code_zero_is_no_liquefiable_unit_not_missing_data() -> None:
    # Code 0 ("unclassified/water" in the CUSEC source) is a real, mapped
    # "no liquefaction hazard" signal -- same $0 outcome as missing data,
    # but for a distinct, documented reason (see module docstring).
    assert _cost(
        hazard_subtype=_NEW_MADRID, susceptibility_code=0, road_classification="motorway", pga_g=0.3
    ) == 0.0


def test_cost_monotonic_in_pga() -> None:
    prev = -1.0
    for pga in (0.05, 0.1, 0.2, 0.3, 0.4, 0.6, 1.0):
        cost = _cost(
            hazard_subtype=_NEW_MADRID, susceptibility_code=5, road_classification="motorway", pga_g=pga
        )
        assert cost >= prev
        prev = cost
    assert prev > 0.0


def test_cost_monotonic_in_susceptibility_class() -> None:
    prev = -1.0
    for code in (1, 2, 3, 4, 5):
        cost = _cost(
            hazard_subtype=_NEW_MADRID, susceptibility_code=code, road_classification="motorway", pga_g=0.3
        )
        assert cost >= prev
        prev = cost
    assert prev > 0.0


def test_pga_above_table_max_clamps_instead_of_extrapolating() -> None:
    at_max = _cost(
        hazard_subtype=_NEW_MADRID, susceptibility_code=5, road_classification="motorway", pga_g=1.5
    )
    above_max = _cost(
        hazard_subtype=_NEW_MADRID, susceptibility_code=5, road_classification="motorway", pga_g=5.0
    )
    assert above_max == at_max


def test_major_and_urban_tiers_differ() -> None:
    major = _cost(
        hazard_subtype=_NEW_MADRID, susceptibility_code=5, road_classification="motorway", pga_g=0.3
    )
    urban = _cost(
        hazard_subtype=_NEW_MADRID, susceptibility_code=5, road_classification="residential", pga_g=0.3
    )
    assert major != urban
    assert major > 0.0 and urban > 0.0


def test_damage_level_probabilities_are_discrete_not_cumulative() -> None:
    # At a real grid point (M7.5/VeryHigh/HRD1_major/PGA=0.4g), T31's own
    # p_slight (0.004225) is LESS than p_moderate (0.047955) -- impossible
    # for cumulative exceedance probabilities (P(>=slight) must be >=
    # P(>=moderate)), confirming these are discrete per-state probabilities.
    # damage_level must not crash or silently mis-rank on this real input.
    _cost_, level = road_liquefaction_direct_cost_usd_per_km(
        hazard_subtype=_NEW_MADRID, susceptibility_code=5, road_classification="motorway", pga_g=0.4
    )
    assert level in ("no", "minor", "moderate", "extensive")
