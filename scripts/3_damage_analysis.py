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

_base_path: Path | None = None


def _base_path_lazy() -> Path:
    """Lazily resolve soge_clusters path -- importing this module (e.g. for
    unit tests against its pure functions) must not require a real
    config.json to exist."""
    global _base_path
    if _base_path is None:
        _base_path = Path(load_config()["paths"]["soge_clusters"])
    return _base_path


class _BasePathProxy:
    """Drop-in replacement for the old eager module-level ``base_path``
    variable: ``base_path / "x"`` keeps working, but resolution is deferred
    to first actual use."""

    def __truediv__(self, other):
        return _base_path_lazy() / other

    @property
    def parent(self):
        return _base_path_lazy().parent


base_path = _BasePathProxy()


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


def calculate_damage_sourced(disrupted_links: pd.DataFrame, damage_curves: Dict) -> pd.DataFrame:
    """Flood direct-damage from real sourced unit costs. This is the only flood costing path (the legacy
    damage_cost_road_flood workbook path was retired 2026-11-12); ``vulnerability.use_sourced_asset_costs`` defaults to
    true and Script 3 refuses to run with it false.

    SA seams: ``damage_costs.road_cost_scale`` scales roads and tunnels, ``damage_costs.bridge_cost_scale`` scales bridges.

    - Roads: T24 CP25 reconstruction cost ($/lane-mile, real HPMS
      functional-class/region/terrain-or-urban-tier join -- see
      resiflow.networks.cp25_road_cost) x lane-miles x the continuous
      van Ginkel C1-C6 damage FRACTION
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
    # Sourced costing has no fallback: name every missing attribute at once instead of failing on the first KeyError.
    from resiflow.testbeds.assets import required_columns_for_sourced_costs

    _needed = required_columns_for_sourced_costs(out["road_label"] if "road_label" in out.columns else [])
    _missing = {
        group: [c for c in cols if c not in out.columns] for group, cols in _needed.items()
    }
    _missing = {group: cols for group, cols in _missing.items() if cols}
    if _missing:
        raise ValueError(
            "sourced flood costing needs link attributes that are missing: "
            + "; ".join(f"{group}: {cols}" for group, cols in _missing.items())
            + ". Add them to the network (testbeds: resiflow.testbeds.assets.apply_synthetic_asset_attributes)."
        )
    flood_types = ["surface", "river"]
    _METERS_PER_MILE = 1609.344
    # SA seams (damage_costs.road_cost_scale scales roads and tunnels, bridge_cost_scale scales bridges); 1.0 is neutral.
    road_cost_scale = float(get_parameter("damage_costs", "road_cost_scale", 1.0))
    bridge_cost_scale = float(get_parameter("damage_costs", "bridge_cost_scale", 1.0))

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
        from resiflow.hazards.tunnel_cost import default_escalation_factor as tunnel_escalation_factor

        tcp = load_table("tunnel_cost_parameters")
        hwy_params = tcp.loc[
            (tcp["application"] == "highway") & (tcp["excavation"] == "conventional")
        ].iloc[0]
        # NHCCI 2008 Q4 -> latest available quarter (DECISION 2026-10-08,
        # docs/FLOOD_TABLE_REVIEW.md): harmonizes tunnel costs onto the same
        # dollar-year as T24/T30 instead of leaving three different years.
        tunnel_escalation = tunnel_escalation_factor()
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
                result = construction_value_usd(
                    geometry, params_table=tcp, escalation_factor=tunnel_escalation
                )
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
            out.loc[road_idx, "direct_damage_mean_usd"] += road_damage.fillna(0.0) * road_cost_scale

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
            out.loc[bridge_idx, "direct_damage_mean_usd"] += np.asarray(bridge_values, dtype=float) * bridge_cost_scale

        if is_tunnel.any():
            tunnel_idx = out.index[is_tunnel]
            tunnel_values = [
                tunnel_direct_damage_usd(tunnel_construction_value.loc[idx], damage_level.loc[idx])
                if not pd.isna(tunnel_construction_value.loc[idx])
                else 0.0
                for idx in tunnel_idx
            ]
            out.loc[tunnel_idx, "direct_damage_mean_usd"] += np.asarray(tunnel_values, dtype=float) * road_cost_scale

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
        - damage_ratio_road_flood.csv:
            Damage curves for various road classifications and flow conditions.
        - damage_cost_road_flood/ (one CSV per sheet: roads, tunnels,
          bridges-surface, bridges-river):
            Asset damage values for roads, tunnels, and bridges.
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
            base_path / "damage_curves" / "damage_ratio_road_flood.csv",
            base_path / "inputs" / "lookup" / "damage_ratio_road_flood.csv",
            base_path / "tables" / "damage_ratio_road_flood.csv",
        ]
    )
    if damage_ratio_path is None:
        raise FileNotFoundError(
            "Could not find damage_ratio_road_flood.csv in standard or toy lookup "
            "paths. If only a legacy .xlsx exists, convert it: "
            "pd.read_excel(xlsx_path).to_csv(xlsx_path.with_suffix('.csv'), index=False)"
        )

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
        from resiflow.tables import read_damage_ratio_table

        damages_ratio_df = read_damage_ratio_table(damage_ratio_path)

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

    use_sourced_asset_costs = get_parameter("vulnerability", "use_sourced_asset_costs", True)
    if use_sourced_asset_costs and "urban_code" in road_links.columns:
        # T24 CP25's Urban subcategory needs the real Census urban-size tier
        # (resiflow.census_urban_area) -- computed once here, not per-row in
        # calculate_damage_sourced().
        from resiflow.census_urban_area import urban_area_profile

        profile = urban_area_profile(road_links["urban_code"]).reset_index(drop=True)
        road_links = road_links.reset_index(drop=True)
        road_links["hpms_urban_size_tier"] = profile["hpms_urban_size_tier"]

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
            # Price each results directory by ITS OWN scenario_param. resolve_active_scenario() lets the
            # RESIFLOW_SCENARIO_PARAM env override the argument, so a run for one hazard used to reprice every
            # other scenario directory it walked as that hazard (found 2026-11-12 on the Sioux Falls multihazard
            # inspection: earlier hazards' damage files were overwritten, mostly empty).
            from resiflow.hazards.scenario_registry import lookup_scenario_by_param

            active_scenario = lookup_scenario_by_param(int(scenario_param), base_path=base_path)
            if active_scenario is None:
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
        elif hazard_type == "flood":
            # Sourced unit costs only (T24 CP25 roads, T30 bridges, Rostami tunnels); the legacy cost-workbook
            # path was retired 2026-11-12 (see docs/testbed_suite/SPEC.md). damage_ratio_road_flood (T22) is unchanged.
            if not use_sourced_asset_costs:
                raise RuntimeError(
                    "vulnerability.use_sourced_asset_costs is false, but the legacy flood costing path was retired "
                    "2026-11-12. Set it to true (the default) and make sure the links carry the attributes "
                    "listed in docs/testbed_suite/SPEC.md section 3a."
                )
            intersections_with_damage = calculate_damage_sourced(intersections, damage_curves)
            intersections_with_damage = intersections_with_damage[
                intersections_with_damage["direct_damage_mean_usd"] > 0
            ].reset_index(drop=True)
        else:
            raise ValueError(f"no direct-damage costing path for hazard_type {hazard_type!r}")
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
