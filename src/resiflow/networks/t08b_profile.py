"""T08b facility x area-type capacity/speed/congestion table -- per-link join.

Unlike T08's flat tier-keyed profile (one value per freeway/arterial/
collector/local_access tier -- see profiles.py's ``map_tier_profile``),
T08b's real NCHRP 825 Exhibit 128 design varies by THREE keys per link
(facility_type, area_type, lane_category), not one, so it can't be
represented as a ``{tier: value}`` dict the way T08's machinery expects.
This module instead computes T08b's three join keys directly from each
link's real attributes and joins T08b onto the link table, producing
genuine per-link columns that ``road_revised.py``'s ``edge_init``/
``edge_initial_speed_func``/``update_edge_speed`` already know how to
prefer over their tier-dict fallback when present (``flow_cap_plph``,
``congestion_factor``, and the new ``flow_breakpoint_plph`` those
functions now also check for).

Join keys, derived from real network attributes -- none invented:

  facility_type: from hpms_fclass (F1,F2->freeway; F3,F4->arterial;
    F5,F6->collector; F7->local_access) -- resiflow.hpms_fclass.

  area_type: "NA" for local_access (T08b has one undifferentiated row);
    else "Rural" (urban==0) or "Urban" (urban==1). T08b's own Downtown/
    Urban/Suburban 3-way split within urbanized areas is NOT derived here
    -- there is no real urbanized-area-size/CBD-distance signal in this
    project yet (the same gap T08b's own header flags for its unapplied
    8%-small-metro adjustment, and T24's CP25 table flags for its own
    Small/Large/Major Urbanized tiers). Collapsing every urbanized link
    onto T08b's "Urban" row is a documented approximation, not a guess at
    which one a given link "really" is.

  lane_category: T08b only splits this for Rural arterial/collector rows
    (freeway and local_access rows are all lane_category="NA" even when
    Rural) -- "Multilane" (lanes>=2) or "Two-lane" (lanes==1) from the
    link's own corrected lane count (resiflow.preprocess.faf5_network's
    DIR-aware AB_Lanes+BA_Lanes fix).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from resiflow.hpms_fclass import assignment_tier_from_fclass

# T08b column -> output column. Matches road_revised.py's existing
# "prefer this per-link column over the tier dict" checks for
# flow_cap_plph/congestion_factor; flow_breakpoint_plph is a new column
# those functions now also check for.
_T08B_COLUMN_MAP = {
    "free_flow_speed_mph": "free_flow_speed_t08b",
    "hcm_capacity_pc_per_lane_hr": "flow_cap_plph",
    "flow_breakpoint_Qbp_pc_per_lane_hr": "flow_breakpoint_plph",
    "congestion_slope_mph_per_pcu": "congestion_factor",
}

_LANE_SPLIT_TIERS = frozenset({"arterial", "collector"})


def derive_t08b_join_keys(road_links: pd.DataFrame) -> pd.DataFrame:
    """{e_id, facility_type, area_type, lane_category} per link."""
    if "hpms_fclass" not in road_links.columns:
        raise KeyError(
            "road_links has no hpms_fclass column -- T08b's facility_type join key "
            "requires it (resiflow.preprocess.faf5_network.convert_faf5_links "
            "populates it from the raw FAF5 F_Class field)."
        )
    if "urban" not in road_links.columns:
        raise KeyError("road_links has no urban column -- required for T08b's area_type join key.")
    if "lanes" not in road_links.columns:
        raise KeyError("road_links has no lanes column -- required for T08b's lane_category join key.")

    facility_type = assignment_tier_from_fclass(road_links["hpms_fclass"]).astype(object)

    urban_numeric = pd.to_numeric(road_links["urban"], errors="coerce").fillna(0)
    area_type = pd.Series(np.where(urban_numeric == 1, "Urban", "Rural"), index=road_links.index, dtype=object)
    area_type.loc[facility_type == "local_access"] = "NA"

    lane_category = pd.Series("NA", index=road_links.index, dtype=object)
    lanes_numeric = pd.to_numeric(road_links["lanes"], errors="coerce").fillna(0)
    splits = facility_type.isin(_LANE_SPLIT_TIERS) & (area_type == "Rural")
    lane_category.loc[splits & (lanes_numeric >= 2)] = "Multilane"
    lane_category.loc[splits & (lanes_numeric < 2)] = "Two-lane"

    return pd.DataFrame(
        {
            "e_id": road_links["e_id"].astype(str),
            "facility_type": facility_type,
            "area_type": area_type,
            "lane_category": lane_category,
        }
    )


# NCHRP 825 Exhibit 128's own stated adjustment (T08b's header): Downtown/
# Urban/Suburban arterial and collector values -- i.e. every row this
# module's collapsed "Urban" area_type can represent -- get reduced 8% in
# metro areas at or under 250,000 population; freeway, Rural, and
# local_access rows are explicitly unaffected.
_SMALL_METRO_ADJUSTABLE_TIERS = frozenset({"arterial", "collector"})
_SMALL_METRO_CAPACITY_SCALE = 0.92


def _apply_small_metro_adjustment(
    merged: pd.DataFrame, keys: pd.DataFrame, road_links: pd.DataFrame, *, params_root=None
) -> pd.DataFrame:
    """Re-derive flow_cap_plph/flow_breakpoint_plph/congestion_factor for
    small-metro Downtown/Urban/Suburban arterial/collector rows, using
    T08b's own documented formulas (Q_bp = 0.85 x capacity; congestion_
    slope = free_flow_speed / (1.15 x capacity)) so the three stay
    internally consistent after the capacity cut, not just independently
    guessed at. Skipped (not fabricated) when ``urban_code`` isn't on the
    network at all -- real population can't be determined without it.
    """
    if "urban_code" not in road_links.columns:
        return merged

    from resiflow.census_urban_area import urban_area_profile

    # Positional alignment throughout (merge() resets the index) -- see
    # this function's own comment at the call site for why.
    profile = urban_area_profile(road_links["urban_code"]).reset_index(drop=True)
    small_metro = (profile["nchrp825_population_gt_250k"] == False).to_numpy()  # noqa: E712
    applies = (
        keys["facility_type"].isin(_SMALL_METRO_ADJUSTABLE_TIERS).to_numpy()
        & (keys["area_type"] == "Urban").to_numpy()
        & small_metro
    )

    out = merged.copy()
    # T08b's own capacity/breakpoint columns are int64 (whole pc/h/ln
    # counts) until now -- the 8% cut produces fractional values, so these
    # three columns become float from here on (explicit astype, not an
    # implicit/fragile upcast-on-assignment).
    out["hcm_capacity_pc_per_lane_hr"] = out["hcm_capacity_pc_per_lane_hr"].astype(float)
    out["flow_breakpoint_Qbp_pc_per_lane_hr"] = out["flow_breakpoint_Qbp_pc_per_lane_hr"].astype(float)
    out["congestion_slope_mph_per_pcu"] = out["congestion_slope_mph_per_pcu"].astype(float)
    capacity = pd.to_numeric(out["hcm_capacity_pc_per_lane_hr"], errors="coerce")
    free_flow = pd.to_numeric(out["free_flow_speed_mph"], errors="coerce")
    adjusted_capacity = capacity * _SMALL_METRO_CAPACITY_SCALE
    out.loc[applies, "hcm_capacity_pc_per_lane_hr"] = adjusted_capacity[applies]
    out.loc[applies, "flow_breakpoint_Qbp_pc_per_lane_hr"] = (0.85 * adjusted_capacity)[applies]
    out.loc[applies, "congestion_slope_mph_per_pcu"] = (free_flow / (1.15 * adjusted_capacity))[applies]
    return out


def compute_t08b_link_profile(
    road_links: pd.DataFrame,
    *,
    table_name: str = "T08b_facility_area_capacity_speed_US_candidate",
    params_root=None,
) -> tuple[pd.DataFrame, int]:
    """Per-link ``{e_id, free_flow_speed_t08b, flow_cap_plph,
    flow_breakpoint_plph, congestion_factor}`` from a real 3-key T08b join.

    Links whose derived key doesn't match any T08b row (e.g. missing/null
    hpms_fclass) get NaN in all four output columns -- callers must keep
    their existing tier-dict fallback for those, never invent a value.
    When ``road_links`` carries ``urban_code`` (resiflow.preprocess.
    faf5_network's raw FAF5 Urban_Code passthrough), also applies NCHRP
    825's own unapplied 8% small-metro-population adjustment (see
    _apply_small_metro_adjustment) before returning. Returns
    ``(profile_df, n_matched)``.
    """
    from resiflow.tables import load_table

    table = load_table(table_name, params_root=params_root)
    table = table.copy()
    table["lane_category"] = table["lane_category"].fillna("NA").astype(str)
    table["area_type"] = table["area_type"].fillna("NA").astype(str)

    keys = derive_t08b_join_keys(road_links)
    join_cols = ["facility_type", "area_type", "lane_category"]
    source_cols = list(_T08B_COLUMN_MAP)
    merged = keys.merge(table[[*join_cols, *source_cols]], on=join_cols, how="left")
    merged = _apply_small_metro_adjustment(merged, keys, road_links, params_root=params_root)
    merged = merged.rename(columns=_T08B_COLUMN_MAP)
    n_matched = int(merged["flow_cap_plph"].notna().sum())
    return merged[["e_id", *_T08B_COLUMN_MAP.values()]], n_matched


__all__ = ["derive_t08b_join_keys", "compute_t08b_link_profile"]
