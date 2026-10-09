"""Bridge replacement-value costing from T30 (state x NHS/non-NHS $/ft2).

T30_bridge_replacement_unit_costs_US.csv gives a 2024 replacement unit cost
(USD per square foot of deck) for each (state, NHS|non-NHS) pair. This
module turns that into a per-bridge replacement value (unit cost x deck
area) and then a flood direct-damage figure, reusing
``hazus_bridge.DAMAGE_RATIO_BY_ASSET_AND_STATE["bridge"]`` (HAZUS 6.1 Table
11-10's fraction-of-replacement-value-by-damage-state) so bridge costing is
internally consistent between flood and earthquake in this pipeline instead
of carrying two independently-invented damage-ratio schemes for the same
asset type.
"""

from __future__ import annotations

import pandas as pd

_SQM_TO_SQFT = 10.763910417

_TABLE_NAME = "T30_bridge_replacement_unit_costs_US"

# T30's own published dollar year.
_T30_BASE_YEAR, _T30_BASE_QUARTER = 2024, 4


def default_escalation_factor(params_root=None) -> float:
    """NHCCI escalation from T30's 2024 USD to the latest available NHCCI
    quarter -- see resiflow.nhcci. DECISION 2026-10-08
    (docs/FLOOD_TABLE_REVIEW.md): harmonizes T24/T30/tunnel costs, which
    were otherwise three different dollar-years, onto one common basis."""
    from resiflow.nhcci import escalation_factor

    return escalation_factor(_T30_BASE_YEAR, _T30_BASE_QUARTER, params_root=params_root)


def load_t30(params_root=None) -> pd.DataFrame:
    from resiflow.tables import load_table

    table = load_table(_TABLE_NAME, params_root=params_root)
    return table[["state", "bridge_class", "cost_used_for_2024_estimate_usd_per_ft2"]].copy()


def bridge_unit_cost_usd_per_sqft(
    state_name: pd.Series,
    on_nhs: pd.Series,
    *,
    escalation_factor: float | None = None,
    params_root=None,
) -> pd.Series:
    """Join real T30 rows on (state name, NHS|non-NHS). Unmatched (e.g. a
    Canadian/Mexican cross-border FAF5 link, or a state name T30 doesn't
    carry) comes back as NaN -- never a fabricated national-average cost.

    ``escalation_factor`` multiplies the table's own 2024 USD onto a common
    dollar-year with T24/tunnel costing. Defaults to
    :func:`default_escalation_factor` (NHCCI, 2024 Q4 -> latest available
    quarter); pass 1.0 for the table's literal, unescalated 2024 USD values.
    """
    if escalation_factor is None:
        escalation_factor = default_escalation_factor(params_root=params_root)
    t30 = load_t30(params_root=params_root)
    bridge_class = pd.Series(on_nhs).map({True: "NHS", False: "non-NHS"})
    key = pd.DataFrame({"state": state_name, "bridge_class": bridge_class})
    merged = key.merge(t30, on=["state", "bridge_class"], how="left")
    return merged["cost_used_for_2024_estimate_usd_per_ft2"] * escalation_factor


def bridge_replacement_value_usd(
    deck_width_m: pd.Series, structure_length_m: pd.Series, unit_cost_usd_per_sqft: pd.Series
) -> pd.Series:
    area_sqft = pd.to_numeric(deck_width_m, errors="coerce") * pd.to_numeric(
        structure_length_m, errors="coerce"
    ) * _SQM_TO_SQFT
    return area_sqft * pd.to_numeric(unit_cost_usd_per_sqft, errors="coerce")


def bridge_direct_damage_usd(
    replacement_value_usd, damage_level: str, *, num_spans: float | None = None
) -> float:
    """direct_damage = replacement_value * HAZUS bridge damage ratio for
    this project's own no/minor/moderate/extensive/severe damage_level.

    ``num_spans``, when known, refines the "severe" (HAZUS "complete") ratio
    via ``bridge_complete_damage_ratio`` (Table 11-10 footnote: 2/spans for
    spans > 2, else 1.00) -- the same span-aware rule the earthquake
    pathway already applies to this exact table, reused here instead of
    always taking the flat 1.00 default.
    """
    from resiflow.hazards.hazus_bridge import (
        DAMAGE_RATIO_BY_ASSET_AND_STATE,
        HAZUS_TO_RESIFLOW_DAMAGE_LEVEL,
        bridge_complete_damage_ratio,
    )

    reverse = {v: k for k, v in HAZUS_TO_RESIFLOW_DAMAGE_LEVEL.items()}
    hazus_state = reverse.get(damage_level)
    if hazus_state is None:
        raise ValueError(f"Unknown damage_level {damage_level!r}; expected one of {sorted(reverse)}")
    if hazus_state == "complete":
        ratio = bridge_complete_damage_ratio(num_spans)
    else:
        ratio = DAMAGE_RATIO_BY_ASSET_AND_STATE["bridge"][hazus_state]
    if replacement_value_usd is None or pd.isna(replacement_value_usd):
        return float("nan")
    return float(replacement_value_usd) * ratio
