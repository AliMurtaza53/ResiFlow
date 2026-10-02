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
    Returns ``(profile_df, n_matched)``.
    """
    from resiflow.tables import load_table

    table = load_table(table_name, params_root=params_root)
    table = table.copy()
    table["lane_category"] = table["lane_category"].fillna("NA").astype(str)
    table["area_type"] = table["area_type"].fillna("NA").astype(str)

    keys = derive_t08b_join_keys(road_links)
    merged = keys.merge(
        table[["facility_type", "area_type", "lane_category", *_T08B_COLUMN_MAP]],
        on=["facility_type", "area_type", "lane_category"],
        how="left",
    )
    merged = merged.rename(columns=_T08B_COLUMN_MAP)
    n_matched = int(merged["flow_cap_plph"].notna().sum())
    return merged[["e_id", *_T08B_COLUMN_MAP.values()]], n_matched


__all__ = ["derive_t08b_join_keys", "compute_t08b_link_profile"]
