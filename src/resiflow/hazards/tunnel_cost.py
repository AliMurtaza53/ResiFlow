"""Tunnel construction-value and flood direct-damage costing.

Source: Rostami, J., Sepehrmanesh, M., Gharahbagh, E.A., Mojtabai, N.
(2013), "Planning level tunnel cost estimation based on statistical
analysis of historical data", Tunnelling and Underground Space Technology
33:22-33, Table 9. DOI: 10.1016/j.tust.2012.08.002. The equations estimate
construction/bid contract cost, not complete program cost -- design,
construction management, financing, and legal costs are excluded; contract
scope varies by project.

This module implements the method exactly as specified in
docs/BRDIGE_COSTS.md, reading coefficients from
parameters/tables/tunnel_cost_parameters.csv (never hardcoded). FAF5's
tunnels are all highway tunnels -- the ``highway_conventional`` model is
the only one in scope for this project; the subway models in the parameter
table exist only because they're part of Rostami et al.'s Table 9 and are
never applied here (see ``construction_value_usd``'s ``application``
check).

Direct damage reuses ``hazus_bridge.DAMAGE_RATIO_BY_ASSET_AND_STATE["tunnel"]``
(a discrete fraction-of-replacement-value-by-damage-state crosswalk, HAZUS
6.1 Table 11-10) rather than this project's continuous van Ginkel C1-C6
road damage-fraction curves -- those are a road-surface model (sophisticated/
simple/ordinary by NHS+tunnel presence) with no tunnel-structure analogue,
and per docs/BRDIGE_COSTS.md step 5: "Reuse the existing damage model only
if it applies to tunnels" -- the HAZUS table already has a tunnel row and is
already used identically for bridges in this same pipeline (flood bridge
costing also switched to it -- see hazards/bridge_cost_t30.py), so this is
the one apples-to-apples reuse available, not a new invention.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import pandas as pd

_FT_TO_M = 0.3048

# Rostami et al.'s own published dollar year (the model's base_price_date).
_TUNNEL_BASE_YEAR, _TUNNEL_BASE_QUARTER = 2008, 4


def default_escalation_factor(params_root=None) -> float:
    """NHCCI escalation from the Rostami et al. model's December 2008 USD
    to the latest available NHCCI quarter -- see resiflow.nhcci. DECISION
    2026-10-08 (docs/FLOOD_TABLE_REVIEW.md): harmonizes T24/T30/tunnel
    costs, which were otherwise three different dollar-years, onto one
    common basis. Pass this (or 1.0 for the literal December 2008 USD) as
    ``construction_value_usd``'s own ``escalation_factor`` argument -- that
    function stays a pure, no-invented-default calculation per
    docs/BRDIGE_COSTS.md's own instruction."""
    from resiflow.nhcci import escalation_factor

    return escalation_factor(_TUNNEL_BASE_YEAR, _TUNNEL_BASE_QUARTER, params_root=params_root)


@dataclass(frozen=True)
class TunnelGeometry:
    physical_asset_id: str
    length_km: float
    bores: int
    lanes_per_bore: float
    span_or_diameter_m: float
    geometry_basis: str  # "clear_width" | "estimated_from_lanes"
    assumption_flags: tuple[str, ...] = field(default_factory=tuple)


def derive_tunnel_geometry(
    *,
    physical_asset_id: str,
    tunnel_length_m: float,
    n_bores: int,
    params: pd.Series,
    tunnel_length_m_min: float | None = None,
    lanes_total: float | None = None,
    roadway_width_m: float | None = None,
) -> TunnelGeometry:
    """Derive bore-level geometry per docs/BRDIGE_COSTS.md step 2.

    Geometry basis preference order: verified per-bore clear width (from
    NTI's real curb-to-curb roadway width) over the lane-count estimate.
    FAF5/NTI carry no directly "measured excavated span" field, so that
    top-preference tier (mentioned in the spec) is never reachable from
    this project's real inputs and is not implemented as a branch here.
    """
    if tunnel_length_m is None or pd.isna(tunnel_length_m) or tunnel_length_m <= 0:
        raise ValueError(f"{physical_asset_id}: tunnel_length_m must be > 0, got {tunnel_length_m}")
    if n_bores is None or pd.isna(n_bores) or n_bores < 1:
        raise ValueError(f"{physical_asset_id}: bore count must be >= 1, got {n_bores}")
    n_bores = int(n_bores)

    flags: list[str] = []
    if tunnel_length_m_min is not None and not pd.isna(tunnel_length_m_min):
        if not math.isclose(tunnel_length_m_min, tunnel_length_m, rel_tol=0.02):
            flags.append("unequal_bore_lengths_used_longest")
    else:
        flags.append("bore_lengths_assumed_equal")

    length_km = tunnel_length_m / 1000.0

    if lanes_total is not None and not pd.isna(lanes_total) and lanes_total > 0:
        lanes_per_bore = float(lanes_total) / n_bores
        if float(lanes_total) % n_bores != 0:
            flags.append("unequal_bore_lane_split_averaged")
    else:
        lanes_per_bore = 2.0
        flags.append("lanes_per_bore_defaulted_to_2_no_nti_lane_count")

    lining = float(params["assumed_lining_m_per_side"])

    if roadway_width_m is not None and not pd.isna(roadway_width_m) and roadway_width_m > 0:
        span_m = float(roadway_width_m) + 2.0 * lining
        basis = "clear_width"
        flags.append("span_from_nti_roadway_width_plus_lining_allowance")
    else:
        lane_width = float(params["assumed_lane_width_m"])
        extra_clear = float(params["assumed_extra_clear_width_m"])
        span_m = lanes_per_bore * lane_width + extra_clear + 2.0 * lining
        basis = "estimated_from_lanes"
        flags.append("span_estimated_from_lane_count_and_analyst_defaults")

    return TunnelGeometry(
        physical_asset_id=physical_asset_id,
        length_km=length_km,
        bores=n_bores,
        lanes_per_bore=lanes_per_bore,
        span_or_diameter_m=span_m,
        geometry_basis=basis,
        assumption_flags=tuple(flags),
    )


def rostami_bore_cost_million_2008usd(length_km: float, size_m: float, params: pd.Series) -> float:
    """Evaluate the selected CSV equation (docs/BRDIGE_COSTS.md step 3)."""
    if length_km <= 0 or size_m <= 0:
        raise ValueError(f"length_km and size_m must be > 0 (got {length_km}, {size_m})")
    intercept = float(params["intercept"])
    length_coef = float(params["length_coefficient"])
    size_coef = float(params["size_coefficient"])
    cost_form = str(params["cost_form"])
    if cost_form == "log10":
        return 10 ** (
            intercept + length_coef * math.log10(length_km) + size_coef * math.log10(size_m)
        )
    if cost_form == "linear":
        return intercept + length_coef * length_km + size_coef * size_m
    raise ValueError(f"Unknown cost_form {cost_form!r} in tunnel_cost_parameters.csv")


def construction_value_usd(
    geometry: TunnelGeometry,
    *,
    params_table: pd.DataFrame,
    application: str = "highway",
    excavation: str = "conventional",
    escalation_factor: float = 1.0,
) -> dict:
    """Construction value (docs/BRDIGE_COSTS.md steps 3-4).

    ``escalation_factor`` defaults to 1.0 = December 2008 USD (the
    workbook's own base_price_date), NOT current USD -- the spec is
    explicit that no inflation factor should be invented here; pass a real
    ENR CCI or NHCCI ratio to escalate.
    """
    rows = params_table.loc[
        (params_table["application"] == application) & (params_table["excavation"] == excavation)
    ]
    if rows.empty:
        raise ValueError(
            f"{geometry.physical_asset_id}: no tunnel_cost_parameters.csv row for "
            f"application={application!r}, excavation={excavation!r} -- "
            "flagging rather than substituting a different model (e.g. subway)."
        )
    params = rows.iloc[0]

    cost_2008_musd_per_bore = rostami_bore_cost_million_2008usd(
        geometry.length_km, geometry.span_or_diameter_m, params
    )
    if cost_2008_musd_per_bore < 0:
        raise ValueError(
            f"{geometry.physical_asset_id}: negative model prediction "
            f"({cost_2008_musd_per_bore} MUSD/bore) -- flagging, not zeroing."
        )
    total_cost_2008_usd = cost_2008_musd_per_bore * geometry.bores * 1_000_000.0
    value_usd = total_cost_2008_usd * escalation_factor

    return {
        "physical_asset_id": geometry.physical_asset_id,
        "model_id": params["model_id"],
        "length_km": geometry.length_km,
        "bores": geometry.bores,
        "lanes_per_bore": geometry.lanes_per_bore,
        "span_or_diameter_m": geometry.span_or_diameter_m,
        "geometry_basis": geometry.geometry_basis,
        "cost_2008_usd": total_cost_2008_usd,
        "escalation_factor": escalation_factor,
        "target_price_year": params["base_price_date"],
        "construction_value_usd": value_usd,
        "assumption_flags": ";".join(geometry.assumption_flags),
    }


def tunnel_direct_damage_usd(construction_value_usd_: float, damage_level: str) -> float:
    """direct_damage_usd = construction_value * damage ratio (step 5).

    Reuses the existing HAZUS tunnel damage-ratio-by-state crosswalk (see
    module docstring) keyed by this project's own no/minor/moderate/
    extensive/severe flood damage_level labels.
    """
    from resiflow.hazards.hazus_bridge import (
        DAMAGE_RATIO_BY_ASSET_AND_STATE,
        HAZUS_TO_RESIFLOW_DAMAGE_LEVEL,
    )

    reverse = {v: k for k, v in HAZUS_TO_RESIFLOW_DAMAGE_LEVEL.items()}
    hazus_state = reverse.get(damage_level)
    if hazus_state is None:
        raise ValueError(f"Unknown damage_level {damage_level!r}; expected one of {sorted(reverse)}")
    ratio = DAMAGE_RATIO_BY_ASSET_AND_STATE["tunnel"][hazus_state]
    return construction_value_usd_ * ratio
