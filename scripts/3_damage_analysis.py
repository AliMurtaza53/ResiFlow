import os
import sys
import warnings
from collections import defaultdict
from pathlib import Path
from typing import Dict, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import geopandas as gpd
import numpy as np
import pandas as pd

from resiflow.utils import get_results_variant, load_config
from resiflow.classification import is_major_road as _is_major_road
from resiflow.parameters import active_overrides_path, get_parameter
from resiflow.sa.curves import mix_damage_curves, scale_depth_axis
from snail import damages

warnings.simplefilter("ignore")

base_path = Path(load_config()["paths"]["soge_clusters"])


def first_existing(paths):
    """Return first existing path from a sequence, else None."""
    for path in paths:
        p = Path(path)
        if p.exists():
            return p
    return None


def _load_damage_ratio_table(table_name: str) -> pd.DataFrame:
    """Adapt a T22-shaped parameter table to damage_ratio_road_flood.xlsx's schema.

    The xlsx (ungitted, damage_curves/damage_ratio_road_flood.xlsx) has columns
    ``intensity`` (flood depth in METERS -- confirmed against the actual file:
    values run 0, 0.05, 0.10, ...) and bare ``C1``..``C6``. T22's CSV uses
    ``depth_cm`` (CENTIMETERS -- a real, easy-to-miss unit mismatch) and
    verbose column names like ``C1_sophisticated_lowflow``. Convert both here
    so create_damage_curves() and the C1..C6 dict lookups downstream
    (compute_damage_fraction) work identically regardless of source.
    """
    from resiflow.tables import load_table

    table = load_table(table_name)
    df = table.rename(columns={"depth_cm": "intensity"})
    df["intensity"] = pd.to_numeric(df["intensity"], errors="raise") / 100.0  # cm -> m
    c_columns = {c: c.split("_")[0] for c in df.columns if c != "intensity"}
    df = df.rename(columns=c_columns)
    return df[["intensity", *sorted(c_columns.values())]]


def create_damage_curves(damage_ratio_df: pd.DataFrame) -> Dict:
    """Create a dictionary of piecewise linear damage curves for the real
    van Ginkel/Li et al. road categories, from a damage_ratio_road_flood.xlsx
    -shaped frame (bare ``C1``..``C6`` columns, ``intensity`` in meters).

    Parameters
    ----------
    damage_ratio_df: pd.DataFrame
        A sample of flood depths and their corresponding road flood damage
        ratios, with columns ``intensity``, ``C1``, ``C2``, ``C3``, ``C4``,
        ``C5``, ``C6`` -- both of this project's real sources already
        produce exactly this shape: the xlsx itself, read directly, and
        ``_load_damage_ratio_table()`` for the T22 CSV alternative (which
        renames its own verbose column names down to bare C1..C6 for
        exactly this reason).

    Returns
    -------
    Dict
        ``{"C1": curve, ..., "C6": curve}``.

    Notes (van Ginkel/Li sophistication scheme -- see
    resiflow.hpms_fclass.flood_road_class_sophistication, which selects
    the active pair per link from real NHS + tunnel-presence data):
    C1: sophisticated (NHS + tunnel), low flow
    C2: sophisticated (NHS + tunnel), high flow
    C3: simple (NHS, no tunnel), low flow
    C4: simple (NHS, no tunnel), high flow
    C5: ordinary (not on NHS), low flow
    C6: ordinary (not on NHS), high flow
    """
    keys = ("C1", "C2", "C3", "C4", "C5", "C6")
    missing = [k for k in keys if k not in damage_ratio_df.columns]
    if missing:
        raise ValueError(
            f"damage_ratio_df is missing required column(s) {missing}; expected "
            f"bare {keys} (plus 'intensity') -- got {list(damage_ratio_df.columns)}"
        )

    damage_curve_dict = {}
    for key in keys:
        damage_ratios = damage_ratio_df[["intensity", key]].rename(columns={key: "damage"})
        damage_curve_dict[key] = damages.PiecewiseLinearDamageCurve(damage_ratios)
    return damage_curve_dict


def compute_damage_fraction(
    road_classification: str,
    trunk_road: bool,
    road_label: str,
    flood_depth: float,
    damage_curves: Dict,
    nhs_designation=None,
) -> Tuple[str, float, str, float]:
    """Compute the damage fraction for a road asset based on its classification,
    label, and flood depth.

    Parameters
    ----------
    road_classification : str
        FAF/OSM road class (motorway, primary, tertiary, local, ...).
    trunk_road : bool
        Specifies whether the road is a trunk road (True) or not (False).
    road_label : str
        The type of infrastructure, such as "bridge", "tunnel", or "road".
    flood_depth : float
        The depth of floodwater on the road asset in meters.
    damage_curves : Dict
        A dictionary containing damage curves for different road and flow conditions.
    nhs_designation : optional
        Real FAF5 NHS field value (resiflow.hpms_fclass), non-null meaning
        "on NHS". When present, selects the curve family by van Ginkel's own
        sophisticated/simple/ordinary scheme (C1/C2 = NHS + tunnel, C3/C4 =
        NHS no tunnel, C5/C6 = non-NHS) instead of the legacy name/trunk_road
        "major road" proxy -- docs/FLOOD_TABLE_REVIEW.md Section 4, item 3:
        the legacy proxy put FAF5 Class 14 (70% of network length) on C3/C4
        when van Ginkel/T22 intend "other roads" (primary and below) on
        C5/C6, because "major by name" and "on the real NHS" are not the
        same set. Falls back to the legacy proxy when nhs_designation is
        None (non-FAF5 networks with no NHS attribute).

    Returns
    -------
    Tuple[str, float, str, float]
        A tuple containing:
        - The first damage curve label (e.g., "C1", "C3", or "C5").
        - The computed damage fraction from the first curve.
        - The second damage curve label (e.g., "C2", "C4", or "C6").
        - The computed damage fraction from the second curve.
    """
    if nhs_designation is not None:
        from resiflow.hpms_fclass import flood_road_class_sophistication

        sophistication = flood_road_class_sophistication(
            pd.Series([nhs_designation]), pd.Series([road_label])
        ).iloc[0]
        curve_pair = {
            "sophisticated": ("C1", "C2"),
            "simple": ("C3", "C4"),
            "ordinary": ("C5", "C6"),
        }[sophistication]
    else:
        major = _is_major_road(road_classification, trunk_road)
        if road_label == "tunnel" and major:
            curve_pair = ("C1", "C2")
        elif road_label != "tunnel" and major:
            curve_pair = ("C3", "C4")
        else:
            curve_pair = ("C5", "C6")

    c1, c2 = curve_pair
    damage_fraction1 = damage_curves[c1].damage_fraction(flood_depth)
    damage_fraction2 = damage_curves[c2].damage_fraction(flood_depth)
    return (c1, damage_fraction1, c2, damage_fraction2)


def compute_damage_values(
    length: float,  # in meters
    flood_type: str,
    damage_fraction: float,
    road_classification: str,
    form_of_way: str,
    urban: int,
    lanes: int,
    road_label: str,
    damage_level: str,
    damage_values: float,  # million $/unit
    bridge_width=None,
    tunnel_length_m=None,
    structure_length_m=None,
) -> Tuple[float, float, float]:
    """
    Calculate the damage costs (minimum, maximum, and mean) for different types of road
    infrastructure (bridges, tunnels, and ordinary roads) caused by flooding.

    Asset geometry for costing comes from inventory attributes when present:
    - bridge: structure_length_m (NBI) x bridge_width (NBI deck); not full FAF length
    - tunnel: min(FAF length, tunnel_length_m from NTI) — tunnel fraction of the edge
    - road: FAF link length
    """

    def compute_bridge_damage(asset_length, width, flood_type, damage_level):
        """Calculate min and max damage for bridges."""
        min_damage = (
            width * asset_length * damage_values[f"bridge_{flood_type}"][damage_level]["min"]
        )
        max_damage = (
            width * asset_length * damage_values[f"bridge_{flood_type}"][damage_level]["max"]
        )
        return min_damage, max_damage

    def compute_tunnel_or_road_damage(asset_length, lanes, key1, key2, damage_fraction):
        """Calculate min and max damage for tunnels or roads."""
        min_damage = (
            asset_length * 1e-3 * lanes * damage_values[key1][key2]["min"] * damage_fraction
        )
        max_damage = (
            asset_length * 1e-3 * lanes * damage_values[key1][key2]["max"] * damage_fraction
        )
        return min_damage, max_damage

    def fallback_asset_label(road_classification: str) -> str:
        """Map FAF/OSM road class to toy asset-cost labels."""
        rc = "" if road_classification is None else str(road_classification).strip().lower()
        if rc in {"motorway", "motorway_link", "trunk", "interstate"}:
            return "Interstate"
        if rc in {"primary", "secondary", "us route"}:
            return "US Route"
        if rc in {"tertiary", "service", "state route"}:
            return "State Route"
        return "Local"

    if road_label == "bridge":
        if bridge_width is None:
            raise ValueError("Bridge width is required for bridges!")
        # Prefer NBI structure length; refuse to silently price full FAF length.
        if structure_length_m is None or pd.isna(structure_length_m):
            raise ValueError(
                "structure_length_m (NBI) is required for bridge costing; "
                "FAF link length alone is not an asset length"
            )
        asset_length = float(structure_length_m)
        if asset_length <= 0:
            raise ValueError(f"structure_length_m must be > 0, got {asset_length}")
        min_cost, max_cost = compute_bridge_damage(
            asset_length, bridge_width, flood_type, damage_level
        )

    elif road_label == "tunnel":
        urban_key = "urb" if urban == 1 else "sub"
        rc = "" if road_classification is None else str(road_classification).strip().lower()
        if rc in {"motorway", "motorway_link"}:
            lane_key = "ge8" if lanes >= 8 else "lt8"
            key = f"m_{lane_key}_{urban_key}"
        elif rc in {"trunk", "primary", "secondary"}:
            if form_of_way == "Single Carriageway":
                key = f"asingle_{urban_key}"
            else:
                lane_key = "ge6" if lanes >= 6 else "lt6"
                key = f"abdual_{lane_key}_{urban_key}"
        elif form_of_way == "Single Carriageway":
            key = f"bsingle_{urban_key}"
        else:
            lane_key = "ge6" if lanes >= 6 else "lt6"
            key = f"bdual_{lane_key}_{urban_key}"

        if key not in damage_values[road_label]:
            key = fallback_asset_label(road_classification)

        if tunnel_length_m is None or pd.isna(tunnel_length_m):
            raise ValueError(
                "tunnel_length_m (NTI) is required for tunnel costing; "
                "refusing to price the full FAF link length as tunnel"
            )
        # Tunnel fraction: cost only min(edge length, inventory tunnel length).
        asset_length = min(float(length), float(tunnel_length_m))
        if asset_length <= 0:
            raise ValueError(
                f"tunnel asset length must be > 0 (length={length}, tunnel_length_m={tunnel_length_m})"
            )
        min_cost, max_cost = compute_tunnel_or_road_damage(
            asset_length, lanes, road_label, key, damage_fraction
        )

    elif road_label == "road":
        urban_key = "urb" if urban == 1 else "sub"
        rc = "" if road_classification is None else str(road_classification).strip().lower()
        if rc in {"motorway", "motorway_link"}:
            lane_key = "ge8" if lanes >= 8 else "lt8"
            key = f"m_{lane_key}_{urban_key}"
        elif rc in {"trunk", "primary", "secondary"}:
            if form_of_way == "Single Carriageway":
                key = f"asingle_{urban_key}"
            else:
                lane_key = "ge6" if lanes >= 6 else "lt6"
                key = f"abdual_{lane_key}_{urban_key}"
        elif form_of_way == "Single Carriageway":
            key = f"bsingle_{urban_key}"
        else:
            lane_key = "ge6" if lanes >= 6 else "lt6"
            key = f"bdual_{lane_key}_{urban_key}"

        if key not in damage_values[road_label]:
            key = fallback_asset_label(road_classification)

        min_cost, max_cost = compute_tunnel_or_road_damage(
            length, lanes, road_label, key, damage_fraction
        )
    else:
        raise ValueError("Invalid road_label. Must be 'bridge', 'tunnel', or 'road'.")

    mean_cost = 0.5 * (min_cost + max_cost)
    return min_cost, max_cost, mean_cost

    mean_cost = np.mean([min_cost, max_cost])

    return min_cost, max_cost, mean_cost


def calculate_damage(
    disrupted_links: pd.DataFrame,
    damage_curves: Dict,
    damage_values: Dict,
) -> pd.DataFrame:
    """
    Calculate damage fractions and costs for disrupted road links based on flood depth.

    Flood-only by construction -- hardcoded flood_types=["surface","river"],
    no hazard_type parameter, reads/prices via damage_ratio_road_flood.xlsx
    and damage_cost_road_flood.xlsx exclusively.

    STATUS CORRECTED 2026-08-29 (the prior version of this comment, dated
    2026-08-20, described a real gap that a6b6f0b then fixed for two of the
    three hazards named below and is now stale/misleading for those two):
    scripts/3_damage_analysis.py's main() only calls this function for
    hazard_type == "flood". Earthquake and landslide route around it
    entirely, through hazards/hazus_bridge.py's compute_row_direct_damage_
    musd() (real FEMA HAZUS 6.1 Ch.7 fragility/cost) -- their
    direct_damage_total IS trustworthy at the scope hazus_bridge.py itself
    documents (earthquake: bridges only, ground-shaking only; landslide:
    HAZUS's ground-failure/PGD fragility for both bridges and roads).
    winter_storm has no such branch and still falls through to this
    function -- disruption/build.py's build_winter_storm_link_disruption()
    repackages ice/snow depth (mm) into a column literally named
    flood_depth_max via an arbitrary unit-matching multiplier, which this
    function then prices with FLOOD repair costs. There is no HAZUS module
    or other domain-appropriate cost table for winter storm anywhere in this
    repo -- do not trust direct_damage_total for that hazard (see
    disruption/build.py's build_winter_storm_link_disruption() comment).

    Parameters
    ----------
    disrupted_links: pd.DataFrame
        A DataFrame containing disrupted road links and their attributes with required
        columns such as "flood_depth_surface" and "flood_depth_river".
    damage_curves: Dict
        A dictionary containing damage curves.
    damage_values: Dict
        A dictionary containing damage cost values for different damage levels,
        road asset types, and flood types.

    Returns
    -------
    pd.DataFrame
        Updated DataFrame with calculated damage fractions and costs. Includes columns
        for damage fractions and cost stats (min, max, mean).
    """

    # Validate required columns
    required_columns = {"flood_depth_surface", "flood_depth_river"}
    missing_columns = required_columns - set(disrupted_links.columns)
    assert not missing_columns, f"Missing required columns: {missing_columns}"

    # Define damage categories and flood types
    curves = ["C1", "C2", "C3", "C4", "C5", "C6"]
    flood_types = ["surface", "river"]

    # Add default columns using MultiIndex for efficiency
    col_tuples = [
        (f"{curve}_{flood_type}_damage_fraction", np.nan)
        for curve in curves
        for flood_type in flood_types
    ] + [
        (f"{curve}_{flood_type}_damage_value_{stat}", np.nan)
        for curve in curves
        for flood_type in flood_types
        for stat in ["min", "max", "mean"]
    ]
    for col, default in col_tuples:
        disrupted_links[col] = default

    def calculate_for_row(row, flood_type):
        """
        Helper function to calculate damage fractions and costs for a single row.
        """
        def _to_float(x):
            arr = np.asarray(x)
            if arr.size == 0:
                return np.nan
            try:
                return float(arr.reshape(-1)[0])
            except Exception:
                return np.nan

        # Compute damage fractions
        curve1, damage_fraction1, curve2, damage_fraction2 = compute_damage_fraction(
            row.road_classification,
            row.trunk_road,
            row.road_label,
            row[f"flood_depth_{flood_type}"],
            damage_curves,
            nhs_designation=getattr(row, "nhs_designation", None),
        )

        structure_length_m = getattr(row, "structure_length_m", None)
        tunnel_length_m = getattr(row, "tunnel_length_m", None)

        # Compute damage values for both curves
        damage_values_1 = compute_damage_values(
            row.length,
            flood_type,
            damage_fraction1,
            row.road_classification,
            row.form_of_way,
            row.urban,
            row.lanes,
            row.road_label,
            row[f"damage_level_{flood_type}"],
            damage_values,
            row.averageWidth,
            tunnel_length_m=tunnel_length_m,
            structure_length_m=structure_length_m,
        )
        damage_values_2 = compute_damage_values(
            row.length,
            flood_type,
            damage_fraction2,
            row.road_classification,
            row.form_of_way,
            row.urban,
            row.lanes,
            row.road_label,
            row[f"damage_level_{flood_type}"],
            damage_values,
            row.averageWidth,
            tunnel_length_m=tunnel_length_m,
            structure_length_m=structure_length_m,
        )

        # Return a dictionary of results for easier assignment
        return {
            f"{curve1}_{flood_type}_damage_fraction": _to_float(damage_fraction1),
            f"{curve2}_{flood_type}_damage_fraction": _to_float(damage_fraction2),
            f"{curve1}_{flood_type}_damage_value_min": _to_float(damage_values_1[0]),
            f"{curve1}_{flood_type}_damage_value_max": _to_float(damage_values_1[1]),
            f"{curve1}_{flood_type}_damage_value_mean": _to_float(damage_values_1[2]),
            f"{curve2}_{flood_type}_damage_value_min": _to_float(damage_values_2[0]),
            f"{curve2}_{flood_type}_damage_value_max": _to_float(damage_values_2[1]),
            f"{curve2}_{flood_type}_damage_value_mean": _to_float(damage_values_2[2]),
        }

    # Apply calculation for each flood type
    for flood_type in flood_types:
        flood_results = disrupted_links.apply(
            lambda row: calculate_for_row(row, flood_type), axis=1
        )
        flood_results_df = pd.DataFrame(
            list(flood_results)
        )  # Convert results to DataFrame
        # Assign columns explicitly (more robust with newer pandas dtypes)
        for col in flood_results_df.columns:
            disrupted_links[col] = flood_results_df[col]

    return disrupted_links


def calculate_damage_sourced(disrupted_links: pd.DataFrame, damage_curves: Dict) -> pd.DataFrame:
    """Flood direct-damage using real sourced unit costs instead of the
    ungitted damage_cost_road_flood.xlsx workbook.

    Gated behind ``vulnerability.use_sourced_asset_costs`` (default False
    -- the legacy ``calculate_damage()`` path above is unchanged and stays
    the default, same SA-seam convention as every other real-table swap in
    this project, e.g. ``assignment.use_table_t08b``).

    - Roads: T24 CP25 reconstruction cost ($/lane-mile, real HPMS
      functional-class/region/terrain-or-urban-tier join -- see
      resiflow.networks.cp25_road_cost) x lane-miles x the SAME continuous
      van Ginkel C1-C6 damage FRACTION already used by the legacy path
      (damage_ratio_road_flood.xlsx is unchanged, per this project's own
      instruction -- only the $ magnitude's source changed).
    - Bridges: T30 replacement cost ($/ft2 by state x NHS/non-NHS -- see
      resiflow.hazards.bridge_cost_t30) x deck area x a discrete HAZUS
      damage-state ratio (Table 11-10), keyed by this link's own flood
      damage_level. Bridges never used the continuous fraction curve
      (that's a road-surface model); this mirrors the EXACT ratio table
      the earthquake pathway already uses for the same bridges, so flood
      and earthquake bridge costing are now internally consistent instead
      of using two independently-invented schemes for the same asset.
    - Tunnels: Rostami et al. (2013) construction value (see
      resiflow.hazards.tunnel_cost) x the same discrete HAZUS tunnel ratio,
      per docs/BRDIGE_COSTS.md step 5 ("reuse the existing damage model
      only if it applies to tunnels").

    Produces ``direct_damage_mean_usd``/``direct_damage_mean_musd`` (summed
    across surface + river, matching damage_aggregation's own summing
    convention for the legacy path) rather than the legacy path's full
    C1..C6 matrix -- this is a new, independent output shape, not a
    drop-in replacement for the legacy CSV columns.
    """
    required_columns = {"flood_depth_surface", "flood_depth_river"}
    missing_columns = required_columns - set(disrupted_links.columns)
    assert not missing_columns, f"Missing required columns: {missing_columns}"

    from resiflow.hazards.bridge_cost_t30 import (
        bridge_direct_damage_usd,
        bridge_replacement_value_usd,
        bridge_unit_cost_usd_per_sqft,
    )
    from resiflow.hazards.tunnel_cost import (
        construction_value_usd,
        derive_tunnel_geometry,
        tunnel_direct_damage_usd,
    )
    from resiflow.networks.cp25_road_cost import cp25_road_cost_usd_per_lane_mile
    from resiflow.tables import load_table
    from resiflow.us_states import state_name_from_fips_or_usps

    out = disrupted_links.reset_index(drop=True).copy()
    flood_types = ["surface", "river"]
    _METERS_PER_MILE = 1609.344

    is_road = out["road_label"] == "road"
    is_bridge = out["road_label"] == "bridge"
    is_tunnel = out["road_label"] == "tunnel"

    # --- Roads: vectorized T24 CP25 $/lane-mile join ---
    road_cost_per_lane_mile = pd.Series(np.nan, index=out.index)
    if is_road.any():
        road_cost_per_lane_mile.loc[is_road] = cp25_road_cost_usd_per_lane_mile(
            hpms_fclass=out.loc[is_road, "hpms_fclass"],
            urban=out.loc[is_road, "urban"],
            urban_size_tier=out.loc[is_road].get(
                "hpms_urban_size_tier", pd.Series(index=out.loc[is_road].index)
            ),
        ).to_numpy()
    lane_miles = (
        pd.to_numeric(out["length"], errors="coerce") / _METERS_PER_MILE
    ) * pd.to_numeric(out["lanes"], errors="coerce")

    # --- Bridges: vectorized T30 $/ft2 join + replacement value ---
    bridge_replacement_value = pd.Series(np.nan, index=out.index)
    if is_bridge.any():
        bridge_idx = out.index[is_bridge]
        fips = out.loc[bridge_idx].get("bridge_state", pd.Series(index=bridge_idx, dtype=object))
        usps = out.loc[bridge_idx].get("STATE", pd.Series(index=bridge_idx, dtype=object))
        state_name = state_name_from_fips_or_usps(fips, usps)
        on_nhs = out.loc[bridge_idx, "nhs_designation"].notna() if "nhs_designation" in out.columns else pd.Series(False, index=bridge_idx)
        # bridge_unit_cost_usd_per_sqft() merges internally, which resets the
        # index to a fresh RangeIndex -- re-index onto bridge_idx positionally
        # (same merge-resets-index discipline as networks/t08b_profile.py)
        # before using it in index-aligned arithmetic below.
        unit_cost = pd.Series(
            bridge_unit_cost_usd_per_sqft(state_name, on_nhs).to_numpy(), index=bridge_idx
        )
        bridge_replacement_value.loc[bridge_idx] = bridge_replacement_value_usd(
            out.loc[bridge_idx, "averageWidth"], out.loc[bridge_idx, "structure_length_m"], unit_cost
        ).to_numpy()

    # --- Tunnels: per-asset Rostami et al. construction value (rare -- loop is fine) ---
    tunnel_construction_value = pd.Series(np.nan, index=out.index)
    tunnel_flags: dict = {}
    if is_tunnel.any():
        tcp = load_table("tunnel_cost_parameters")
        hwy_params = tcp.loc[
            (tcp["application"] == "highway") & (tcp["excavation"] == "conventional")
        ].iloc[0]
        for idx in out.index[is_tunnel]:
            row = out.loc[idx]
            n_bores = row.get("tunnel_bores")
            # `or 1` is unsafe here: NaN is truthy in Python, so it would
            # NOT replace a NaN bore count -- explicit isnan check instead.
            if n_bores is None or pd.isna(n_bores):
                n_bores = 1
            try:
                geometry = derive_tunnel_geometry(
                    physical_asset_id=str(row.get("e_id", idx)),
                    tunnel_length_m=row.get("tunnel_length_m"),
                    tunnel_length_m_min=row.get("tunnel_length_m_min"),
                    n_bores=n_bores,
                    lanes_total=row.get("tunnel_lanes_total"),
                    roadway_width_m=row.get("tunnel_roadway_width_m"),
                    params=hwy_params,
                )
                result = construction_value_usd(geometry, params_table=tcp)
                tunnel_construction_value.loc[idx] = result["construction_value_usd"]
                tunnel_flags[idx] = result["assumption_flags"]
            except ValueError as exc:
                tunnel_flags[idx] = f"COST_UNAVAILABLE: {exc}"

    out["direct_damage_mean_usd"] = 0.0
    out["tunnel_cost_assumption_flags"] = pd.Series(tunnel_flags, dtype=object)

    for flood_type in flood_types:
        depth = out[f"flood_depth_{flood_type}"]
        damage_level = out[f"damage_level_{flood_type}"]

        if is_road.any():
            road_idx = out.index[is_road]
            # Average the low-flow/high-flow curve pair's fraction (C1&C2,
            # C3&C4, or C5&C6), matching damage_aggregation.py's own
            # consolidated_row_damage_musd combination convention for the
            # legacy path, rather than inventing a different rule here.
            fractions = []
            for idx in road_idx:
                row = out.loc[idx]
                _, frac1, _, frac2 = compute_damage_fraction(
                    row.get("road_classification"),
                    row.get("trunk_road"),
                    "road",
                    depth.loc[idx],
                    damage_curves,
                    nhs_designation=row.get("nhs_designation"),
                )
                fractions.append(float(np.mean([frac1, frac2])))
            road_damage = (
                road_cost_per_lane_mile.loc[road_idx]
                * lane_miles.loc[road_idx]
                * pd.Series(fractions, index=road_idx)
            )
            out.loc[road_idx, "direct_damage_mean_usd"] += road_damage.fillna(0.0)

        if is_bridge.any():
            bridge_idx = out.index[is_bridge]
            # `or 0.0` is unsafe here: NaN is truthy in Python, so it would
            # NOT replace a NaN damage value -- explicit isnan check instead
            # (same footgun documented in hazus_bridge.py's own helpers).
            bridge_values = []
            for idx in bridge_idx:
                value = bridge_direct_damage_usd(
                    bridge_replacement_value.loc[idx],
                    damage_level.loc[idx],
                    num_spans=out.loc[idx].get("main_unit_spans"),
                )
                bridge_values.append(0.0 if pd.isna(value) else value)
            out.loc[bridge_idx, "direct_damage_mean_usd"] += bridge_values

        if is_tunnel.any():
            tunnel_idx = out.index[is_tunnel]
            out.loc[tunnel_idx, "direct_damage_mean_usd"] += [
                tunnel_direct_damage_usd(tunnel_construction_value.loc[idx], damage_level.loc[idx])
                if not pd.isna(tunnel_construction_value.loc[idx])
                else 0.0
                for idx in tunnel_idx
            ]

    out["direct_damage_mean_usd"] = pd.to_numeric(out["direct_damage_mean_usd"], errors="coerce").fillna(0.0)
    out["direct_damage_mean_musd"] = out["direct_damage_mean_usd"] / 1_000_000.0
    return out


def format_intersections(
    intersections: pd.DataFrame,
    road_links: gpd.GeoDataFrame,
) -> pd.DataFrame:
    """Format intersection data and enrich it with road link attributes.

    Parameters
    ----------
    intersections: pd.DataFrame
        A DataFrame containing intersection results (module 2), such as
        flood depth and damage level based on road intersections.
    road_links: gpd.GeoDataFrame
        Original road links of the network.

    Returns
    -------
    pd.DataFrame
        A formatted and enriched DataFrame of intersections.
    """

    # ---------------------------------------------------------------------
    # PERFORMANCE / DATA-CLEANLINESS NOTE
    # ---------------------------------------------------------------------
    # Script 2 can emit sentinel rows with index_i/index_j == -1 when a
    # segment does not map onto a valid raster grid cell index. These rows
    # do not represent actionable flooded intersections and typically carry
    # null flood-depth / damage-level fields downstream.
    #
    # Keeping them creates large, noisy outputs and unnecessary per-row
    # damage computations in Script 3. We drop them early to:
    #   1) reduce processing time,
    #   2) keep output CSVs focused on real intersection segments,
    #   3) prevent NaN-only C*_damage_* rows in final outputs.
    # ---------------------------------------------------------------------
    if {"index_i", "index_j"}.issubset(intersections.columns):
        sentinel_mask = (intersections["index_i"] == -1) & (intersections["index_j"] == -1)
        intersections = intersections.loc[~sentinel_mask].copy()

    # Define default values for missing columns
    columns_to_add = {
        "flood_depth_surface": 0.0,
        "flood_depth_river": 0.0,
        "damage_level_surface": "no",
        "damage_level_river": "no",
    }

    # Define mappings for damage levels
    damage_level_dict = {
        "no": 0,
        "minor": 1,
        "moderate": 2,
        "extensive": 3,
        "severe": 4,
    }
    damage_level_dict_reverse = {v: k for k, v in damage_level_dict.items()}

    # Ensure all required columns exist with default values
    for col, default_value in columns_to_add.items():
        if col not in intersections.columns:
            intersections[col] = default_value
        else:
            # Avoid inplace chained-assignment behavior; assign explicitly.
            intersections[col] = intersections[col].fillna(default_value)

    # Map damage levels to numeric values
    for col in ["damage_level_surface", "damage_level_river"]:
        intersections[col] = intersections[col].map(damage_level_dict)

    # Group by specific columns and take the max value for each group
    group_columns = ["e_id", "length", "index_i", "index_j"]
    intersections_gp = intersections.groupby(group_columns, as_index=False).max(
        numeric_only=True
    )  # Ensure numeric columns are aggregated

    # Reverse map numeric damage levels back to strings
    for col in ["damage_level_surface", "damage_level_river"]:
        intersections_gp[col] = intersections_gp[col].map(damage_level_dict_reverse)

    # Defensive normalization after groupby/map in case any NaNs remain.
    # This ensures downstream filtering (`== "no"`) behaves consistently.
    intersections_gp["flood_depth_surface"] = intersections_gp["flood_depth_surface"].fillna(0.0)
    intersections_gp["flood_depth_river"] = intersections_gp["flood_depth_river"].fillna(0.0)
    intersections_gp["damage_level_surface"] = intersections_gp["damage_level_surface"].fillna("no")
    intersections_gp["damage_level_river"] = intersections_gp["damage_level_river"].fillna("no")
    # Build attributes from FAF5 assignment links.
    rl = road_links.copy()
    if "road_label" not in rl.columns:
        if "road_bridge" in rl.columns or "road_tunnel" in rl.columns:
            from resiflow.preprocess.faf5_network import derive_road_label

            rl = derive_road_label(rl)
        else:
            rl["road_label"] = "road"

    if "form_of_way" not in rl.columns:
        rl["form_of_way"] = "Single Carriageway"
    if "trunk_road" not in rl.columns:
        rl["trunk_road"] = False
    if "urban" not in rl.columns:
        rl["urban"] = 0
    if "lanes" not in rl.columns:
        rl["lanes"] = 2
    if "averageWidth" not in rl.columns:
        rl["averageWidth"] = 3.65

    # HAZUS bridge-classification fields (added 2026-08-20, see
    # preprocess/faf5_network.py's apply_bridge_index() and
    # hazards/hazus_bridge.py) -- must be carried through this merge
    # explicitly like every other road_links attribute above, or they
    # silently vanish here even though they survive all the way from
    # road_links through disruption/build.py.
    hazus_cols = [
        "year_built", "main_unit_spans", "max_span_length_m",
        "skew_degrees", "structure_kind_code", "structure_type_code", "bridge_state",
    ]
    for col in hazus_cols:
        if col not in rl.columns:
            rl[col] = np.nan

    # Asset geometry from inventory (NBI/NTI); required for bridge/tunnel costing.
    asset_cols = []
    for col in ("structure_length_m", "tunnel_length_m", "tunnel_fraction", "bridge_fraction"):
        if col in rl.columns:
            asset_cols.append(col)

    # hpms_fclass/nhs_designation (resiflow.hpms_fclass): real HPMS F_Class +
    # NHS attributes -- compute_damage_fraction()'s nhs_designation arg uses
    # these to pick the C1-C6 family via van Ginkel's own sophisticated/
    # simple/ordinary scheme instead of the legacy name-based "major road"
    # proxy. Optional -- absent on non-FAF5/legacy networks, same pattern as
    # the asset_cols above.
    for col in ("hpms_fclass", "nhs_designation"):
        if col in rl.columns:
            asset_cols.append(col)

    # Sourced-cost columns (calculate_damage_sourced(), gated behind
    # vulnerability.use_sourced_asset_costs): T24 CP25 road costing needs
    # urban-size tier + state; T30 bridge costing needs state; Rostami
    # tunnel costing needs real bore geometry (see faf5_network.py's
    # apply_tunnel_index()). All optional -- same pattern as above.
    for col in (
        "hpms_urban_size_tier", "STATE",
        "tunnel_bores", "tunnel_length_m_min", "tunnel_lanes_total", "tunnel_roadway_width_m",
    ):
        if col in rl.columns:
            asset_cols.append(col)

    intersections_gp = intersections_gp.merge(
        rl[
            [
                "e_id",
                "road_classification",
                "form_of_way",
                "trunk_road",
                "urban",
                "lanes",
                "averageWidth",
                "road_label",
                *hazus_cols,
                *asset_cols,
            ]
        ],
        on="e_id",
        how="left",
    )

    # Final normalization to avoid invalid labels during damage calculation
    intersections_gp["road_label"] = (
        intersections_gp["road_label"].astype(str).str.lower().replace({"nan": "road", "": "road"})
    )
    intersections_gp.loc[
        ~intersections_gp["road_label"].isin(["road", "bridge", "tunnel"]), "road_label"
    ] = "road"
    intersections_gp["form_of_way"] = intersections_gp["form_of_way"].fillna("Single Carriageway")
    intersections_gp["trunk_road"] = intersections_gp["trunk_road"].fillna(False)

    return intersections_gp


def main():
    """
    Main function to calculate damage fractions and costs for disrupted road links
        based on flood depth.

    Model Inputs:
        - damage_ratio_road_flood.xlsx:
            Excel file containing damage curves for various road classifications and
                flow conditions.
        - damage_cost_road_flood.xlsx:
            Excel file containing asset damage values for roads, tunnels, and bridges.
        - faf5_road_links.gpq:
            GeoDataFrame of road network links with attributes.
        - intersections:
            Output from module 2 containing intersection results with flood depth and
                damage levels.

    Model Outputs:
        - intersections_with_damages.csv:
            CSV file containing damage fractions and costs (min, max, mean) for
                disrupted road links.

    Parameters:
        depth_thres (int): Flood depth threshold in centimeters for road closure.

    Returns:
        None: Outputs are saved to files.
    """
    damage_ratio_path = first_existing(
        [
            base_path / "damage_curves" / "damage_ratio_road_flood.xlsx",
            base_path / "inputs" / "lookup" / "damage_ratio_road_flood.xlsx",
            base_path / "tables" / "damage_ratio_road_flood.xlsx",
        ]
    )
    if damage_ratio_path is None:
        raise FileNotFoundError("Could not find damage_ratio_road_flood.xlsx in standard or toy lookup paths")

    damage_cost_path = first_existing(
        [
            base_path / "asset_costs" / "damage_cost_road_flood.xlsx",
            base_path / "inputs" / "lookup" / "damage_cost_road_flood.xlsx",
            base_path / "tables" / "damage_cost_road_flood.xlsx",
        ]
    )
    if damage_cost_path is None:
        raise FileNotFoundError("Could not find damage_cost_road_flood.xlsx in standard or toy lookup paths")
    if active_overrides_path() is not None:
        print(f"Parameter overrides in force: {active_overrides_path()}")

    # damage curves
    if get_parameter("vulnerability", "use_table_damage_ratio_curves", False):
        damages_ratio_df = _load_damage_ratio_table(
            get_parameter(
                "vulnerability", "damage_ratio_curves_table", "T22_damage_ratio_curves_TEMPLATE"
            )
        )
    else:
        damages_ratio_df = pd.read_excel(damage_ratio_path)

    # SA seam: optional vulnerability-curve perturbations, applied to the
    # loaded frame (the workbook itself stays pristine). Both parameters are
    # baseline-neutral: null/absent in unified_parameters.json means no-op.
    curve_theta = get_parameter("vulnerability", "curve_theta", None)
    depth_scale_lambda = get_parameter("vulnerability", "depth_scale_lambda", None)
    if curve_theta is not None:
        print(f"Applying damage-curve mixing theta={curve_theta}")
        damages_ratio_df = mix_damage_curves(damages_ratio_df, float(curve_theta))
    if depth_scale_lambda is not None:
        print(f"Applying depth-axis scale lambda={depth_scale_lambda}")
        damages_ratio_df = scale_depth_axis(damages_ratio_df, float(depth_scale_lambda))

    damage_curves = create_damage_curves(damages_ratio_df)

    faf5_links_path = first_existing(
        [
            base_path / "networks" / "faf5" / "faf5_road_links.gpq",
            base_path / "inputs" / "networks" / "faf5" / "faf5_road_links.gpq",
        ]
    )
    if faf5_links_path is None:
        raise FileNotFoundError("Could not find faf5_road_links.gpq under soge_clusters")
    road_links = gpd.read_parquet(faf5_links_path)

    use_sourced_asset_costs = get_parameter("vulnerability", "use_sourced_asset_costs", False)
    if use_sourced_asset_costs and "urban_code" in road_links.columns:
        # T24 CP25's Urban subcategory needs the real Census urban-size tier
        # (resiflow.census_urban_area) -- computed once here, not per-row in
        # calculate_damage_sourced().
        from resiflow.census_urban_area import urban_area_profile

        profile = urban_area_profile(road_links["urban_code"]).reset_index(drop=True)
        road_links = road_links.reset_index(drop=True)
        road_links["hpms_urban_size_tier"] = profile["hpms_urban_size_tier"]

    xls = pd.ExcelFile(damage_cost_path)
    available_sheets = set(xls.sheet_names)

    def normalize_cost_df(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        out.columns = [str(c).strip().lower() for c in out.columns]
        return out

    road_damage_file = normalize_cost_df(pd.read_excel(damage_cost_path, sheet_name="roads"))

    if "tunnels" in available_sheets:
        tunnel_damage_file = normalize_cost_df(pd.read_excel(damage_cost_path, sheet_name="tunnels"))
    else:
        # Toy workbook fallback: reuse road costs for tunnel costs.
        tunnel_damage_file = road_damage_file.copy()

    if "bridges-surface" in available_sheets:
        bridge_surface_damage_file = normalize_cost_df(
            pd.read_excel(damage_cost_path, sheet_name="bridges-surface")
        )
    elif "bridges" in available_sheets:
        bridge_surface_damage_file = normalize_cost_df(pd.read_excel(damage_cost_path, sheet_name="bridges"))
    else:
        raise FileNotFoundError("Bridge damage-cost sheet not found in damage_cost workbook")

    if "bridges-river" in available_sheets:
        bridge_river_damage_file = normalize_cost_df(
            pd.read_excel(damage_cost_path, sheet_name="bridges-river")
        )
    elif "bridges" in available_sheets:
        bridge_river_damage_file = normalize_cost_df(pd.read_excel(damage_cost_path, sheet_name="bridges"))
    else:
        raise FileNotFoundError("Bridge damage-cost sheet not found in damage_cost workbook")
    dv_road_dict = defaultdict(lambda: defaultdict(float))
    for row in road_damage_file.itertuples():
        dv_road_dict[row.label]["min"] = row.min
        dv_road_dict[row.label]["max"] = row.max
        dv_road_dict[row.label]["mean"] = row.mean

    dv_tunnel_dict = defaultdict(lambda: defaultdict(float))
    for row in tunnel_damage_file.itertuples():
        dv_tunnel_dict[row.label]["min"] = row.min
        dv_tunnel_dict[row.label]["max"] = row.max
        dv_tunnel_dict[row.label]["mean"] = row.mean

    dv_bridge_surface_dict = defaultdict(lambda: defaultdict(float))
    for row in bridge_surface_damage_file.itertuples():
        # support both detailed (damage-level rows) and toy single-row bridge costs
        label = row.label
        if label not in {"no", "minor", "moderate", "extensive", "severe"}:
            for lvl in ["no", "minor", "moderate", "extensive", "severe"]:
                dv_bridge_surface_dict[lvl]["min"] = row.min
                dv_bridge_surface_dict[lvl]["max"] = row.max
                dv_bridge_surface_dict[lvl]["mean"] = row.mean
        else:
            dv_bridge_surface_dict[label]["min"] = row.min
            dv_bridge_surface_dict[label]["max"] = row.max
            dv_bridge_surface_dict[label]["mean"] = row.mean

    dv_bridge_river_dict = defaultdict(lambda: defaultdict(float))
    for row in bridge_river_damage_file.itertuples():
        label = row.label
        if label not in {"no", "minor", "moderate", "extensive", "severe"}:
            for lvl in ["no", "minor", "moderate", "extensive", "severe"]:
                dv_bridge_river_dict[lvl]["min"] = row.min
                dv_bridge_river_dict[lvl]["max"] = row.max
                dv_bridge_river_dict[lvl]["mean"] = row.mean
        else:
            dv_bridge_river_dict[label]["min"] = row.min
            dv_bridge_river_dict[label]["max"] = row.max
            dv_bridge_river_dict[label]["mean"] = row.mean

    damage_values = {
        "road": dv_road_dict,
        "tunnel": dv_tunnel_dict,
        "bridge_surface": dv_bridge_surface_dict,
        "bridge_river": dv_bridge_river_dict,
    }

    # SA seam: asset unit-cost scales, applied after the pristine cost
    # workbook loads. Defaults of 1.0 are baseline-neutral (multiplying by
    # 1.0 is exact for floats).
    road_cost_scale = float(get_parameter("damage_costs", "road_cost_scale", 1.0))
    bridge_cost_scale = float(get_parameter("damage_costs", "bridge_cost_scale", 1.0))
    if road_cost_scale != 1.0 or bridge_cost_scale != 1.0:
        print(
            f"Applying asset-cost scales: road/tunnel x{road_cost_scale}, "
            f"bridge x{bridge_cost_scale}"
        )
        for asset_label, scale in (
            ("road", road_cost_scale),
            ("tunnel", road_cost_scale),
            ("bridge_surface", bridge_cost_scale),
            ("bridge_river", bridge_cost_scale),
        ):
            if scale == 1.0:
                continue
            for stats in damage_values[asset_label].values():
                for stat in list(stats):
                    stats[stat] = stats[stat] * scale

    # Load intersection data and assign attributes for damage calculations
    # batch process
    results_variant = get_results_variant()

    intersections_list = []
    for root, _, files in os.walk(
        base_path.parent / "results" / "disruption_analysis" / results_variant
    ):
        for file in files:
            if file.startswith("intersections_") and file.endswith(".pq"):
                intersections_path = Path(root) / file
                intersections_list.append(intersections_path)

    if len(intersections_list) == 0:
        print("No intersections files found under results/disruption_analysis/revision. Skipping.")
        return

    for intersections_path in intersections_list:
        flood_key = intersections_path.stem
        scenario_param = intersections_path.parent.parent.name
        out_path = (
            base_path.parent
            / "results"
            / "damage_analysis"
            / results_variant
            / str(scenario_param)
        )

        print(f"Calculate damages for scenario={scenario_param} event={flood_key}...")
        # format intersections
        intersections = pd.read_parquet(intersections_path)
        intersections = format_intersections(intersections, road_links)

        if intersections.empty:
            print(f"Skipping {flood_key}: no valid raster-intersection segments after filtering")
            continue

        # append a few more columns into the table
        intersections["surface_unit_cost_min"] = np.nan
        intersections["surface_unit_cost_max"] = np.nan
        intersections["river_unit_cost_min"] = np.nan
        intersections["river_unit_cost_max"] = np.nan

        # Resolve hazard_type for this scenario -- earthquake/landslide route
        # through the real HAZUS 6.1 methodology (hazards/hazus_bridge.py)
        # instead of calculate_damage()'s flood-only path (hardcoded
        # flood_types=["surface","river"], priced with FLOOD's
        # damage_ratio_road_flood.xlsx/damage_cost_road_flood.xlsx --
        # confirmed 2026-08-20 that every earthquake/landslide
        # direct_damage_total up to that point was flood repair costs
        # applied to a relabeled non-flood intensity value, see
        # disruption/build.py's SHIM comments and this function's own
        # docstring for the full history).
        from resiflow.hazards.scenario_registry import resolve_active_scenario

        try:
            active_scenario = resolve_active_scenario(
                scenario_param=int(scenario_param), event_id=str(flood_key), base_path=base_path
            )
            hazard_type = active_scenario.hazard_type
        except Exception:
            hazard_type = "flood"

        if hazard_type in ("earthquake", "landslide"):
            from resiflow.hazards.hazus_bridge import compute_row_direct_damage_musd

            if hazard_type == "earthquake":
                print(
                    "  earthquake: HAZUS bridge ground-shaking cost uses Sa(1.0s) "
                    "(psa1p0_g), computed only for bridges -- roads report $0 "
                    "(HAZUS's road fragility, Table 7-5, is PGD/ground-failure-only, "
                    "no shaking curve; no liquefaction PGD is computed for earthquake "
                    "in this pipeline). Bridges also report $0 if the active hazard "
                    "source has no Sa(1.0s) companion raster. "
                    "See hazards/hazus_bridge.py's compute_row_direct_damage_musd docstring."
                )
            intersections_with_damage = intersections.copy()
            active_hazard_subtype = getattr(active_scenario, "hazard_subtype", None)
            intersections_with_damage["direct_damage_mean_musd"] = intersections_with_damage.apply(
                lambda row: compute_row_direct_damage_musd(
                    row, hazard_type=hazard_type, hazard_subtype=active_hazard_subtype
                ),
                axis=1,
            )
            intersections_with_damage["direct_damage_mean_usd"] = (
                intersections_with_damage["direct_damage_mean_musd"] * 1_000_000.0
            )
            # Filter on the computed cost itself, not a "damage_level_max"
            # string column -- format_intersections()'s groupby uses
            # numeric_only=True and doesn't special-case damage_level_max
            # the way it does damage_level_surface/river, so that column
            # doesn't reliably survive to this point.
            intersections_with_damage = intersections_with_damage[
                intersections_with_damage["direct_damage_mean_musd"] > 0
            ].reset_index(drop=True)
        elif hazard_type == "winter_storm" and get_parameter(
            "vulnerability", "use_table_winter_storm_cost", False
        ):
            # T32's real DOT-regression direct cleanup cost formula (see
            # hazards/winter_storm_cost.py), replacing the flood-shim path
            # below for winter_storm specifically. duration_hours/air_temp_F
            # come from real-but-approximate companion rasters (see
            # scripts/prepare_winter_storm_duration_temp.py) when the active
            # hazard_source has them (all 4 real winter-storm sources do);
            # missing on a given segment falls back to winter_storm_cost.py's
            # own documented defaults, not a fabricated value.
            from resiflow.hazards.winter_storm_cost import winter_storm_direct_cost_usd_per_lane_mile

            _METERS_PER_MILE = 1609.344

            def _winter_storm_row_cost_musd(row: pd.Series) -> float:
                cost_per_lane_mile = winter_storm_direct_cost_usd_per_lane_mile(
                    snow_depth_mm=row.get("winter_storm_mm"),
                    duration_hours=row.get("duration_hours"),
                    air_temp_F=row.get("air_temp_F"),
                    road_classification=row.get("road_classification"),
                )
                if cost_per_lane_mile <= 0.0:
                    return 0.0
                # `or` is unsafe here: NaN is truthy in Python, so
                # `row.get("length") or 0.0` would NOT replace a NaN length
                # -- explicit isnan checks instead (same footgun documented
                # in hazus_bridge.py's own _safe_str/_safe_float helpers).
                length_m = row.get("length")
                length_m = 0.0 if length_m is None or pd.isna(length_m) else float(length_m)
                lanes = row.get("lanes")
                lanes = 2.0 if lanes is None or pd.isna(lanes) else float(lanes)
                lane_miles = (length_m / _METERS_PER_MILE) * lanes
                return (cost_per_lane_mile * lane_miles) / 1_000_000.0

            intersections_with_damage = intersections.copy()
            intersections_with_damage["direct_damage_mean_musd"] = intersections_with_damage.apply(
                _winter_storm_row_cost_musd, axis=1
            )
            intersections_with_damage["direct_damage_mean_usd"] = (
                intersections_with_damage["direct_damage_mean_musd"] * 1_000_000.0
            )
            intersections_with_damage = intersections_with_damage[
                intersections_with_damage["direct_damage_mean_musd"] > 0
            ].reset_index(drop=True)
        elif hazard_type == "flood" and use_sourced_asset_costs:
            # Real sourced unit costs (T24 CP25 roads, T30 bridges, Rostami
            # et al. tunnels) instead of the ungitted damage_cost_road_flood
            # .xlsx workbook -- see calculate_damage_sourced()'s own
            # docstring. damage_ratio_road_flood.xlsx (T22) is unchanged.
            intersections_with_damage = calculate_damage_sourced(intersections, damage_curves)
            intersections_with_damage = intersections_with_damage[
                intersections_with_damage["direct_damage_mean_usd"] > 0
            ].reset_index(drop=True)
        else:
            # run damage analysis
            intersections_with_damage = calculate_damage(
                intersections, damage_curves, damage_values
            )
            from resiflow.damage_aggregation import add_consolidated_damage_columns

            intersections_with_damage = add_consolidated_damage_columns(intersections_with_damage)
            # filter out undamaged intersections
            intersections_with_damage = intersections_with_damage[
                ~(
                    (intersections_with_damage.damage_level_river == "no")
                    & (intersections_with_damage.damage_level_surface == "no")
                )
            ].reset_index(drop=True)
        # export results
        # Atomic write (tmp file + os.replace): this CSV is shared -- every
        # hazard job's Script 3 step walks and rewrites EVERY scenario's file
        # under this results tree, every time it runs (not just its own), so
        # concurrent jobs routinely rewrite the same path. A plain to_csv()
        # in place is not atomic: a concurrent reader (Script 4, or this same
        # script from a sibling job) can observe a partially-written file
        # mid-write. Confirmed as the root cause of a real bug (2026-08-26):
        # earthquake_401 and landslide_501's Script 4 runs read direct-damage
        # totals 393x and 9.3x too low respectively, because their own
        # damage CSV was mid-overwrite by a concurrently-running sibling
        # hazard job's Script 3 pass at the exact moment Script 4 read it.
        # os.replace() is atomic on both POSIX and Windows, so a reader always
        # sees either the complete old file or the complete new one.
        (out_path).mkdir(parents=True, exist_ok=True)
        final_path = out_path / f"{flood_key}_with_damage_values.csv"
        tmp_path = out_path / f".{flood_key}_with_damage_values.csv.tmp{os.getpid()}"
        intersections_with_damage.to_csv(tmp_path, index=False)
        os.replace(tmp_path, final_path)


if __name__ == "__main__":
    main()  # direct damages are irrelevant with depth threshold
