"""T24 CP25 road reconstruction unit cost, per link.

T24_asset_unit_costs_US_candidate_CP25.csv is FHWA's HERS/C&P Report
Exhibits A-5..A-8 cost table: $K per lane-mile (2018 USD) by
region (Rural|Urban) x functional_class x subcategory x improvement_type.
``functional_class`` is spelled out with the official HPMS F1-F7 names
(Interstate, Other Freeway and Expressway, Other Principal Arterial, Minor
Arterial, Major Collector, Minor Collector, Local) -- a direct match to
this project's own ``hpms_fclass`` integers (1-7), confirmed by inspecting
the real table's own functional_class values.

``subcategory_or_terrain`` splits two different ways depending on region:
Rural rows use real terrain (Flat/Rolling/Mountainous); Urban rows use the
exact same Small Urban/Small Urbanized/Large Urbanized/Major Urbanized
tiers this project's own T39/resiflow.census_urban_area already derives
from FAF5's Urban_Code -- so the Urban side of this join is fully real,
sourced data end to end. The Rural/terrain side has no reliable per-link
terrain source yet (see TERRAIN_DEFAULT below) and uses a single flagged
default for every rural link until a real terrain source is wired in.

This gives a per-lane-mile REPLACEMENT/RECONSTRUCTION cost -- the role
damage_cost_road_flood.xlsx's "roads"/"tunnels" sheets used to play in
scripts/3_damage_analysis.py. The continuous van Ginkel C1-C6 damage
FRACTION (from damage_ratio_road_flood.xlsx, unchanged -- see that
script's calculate_damage()) still applies on top of this cost, exactly as
it did before; only the $ magnitude's source has changed.
"""

from __future__ import annotations

import pandas as pd

_TABLE_NAME = "T24_asset_unit_costs_US_candidate_CP25"

_FCLASS_TO_T24_NAME = {
    1: "Interstate",
    2: "Other Freeway and Expressway",
    3: "Other Principal Arterial",
    4: "Minor Arterial",
    5: "Major Collector",
    6: "Minor Collector",
    7: "Local",
}

# T39's hpms_urban_size_tier values -> T24's own Title-Case subcategory spelling.
_URBAN_TIER_TO_T24_SUBCATEGORY = {
    "small_urban": "Small Urban",
    "small_urbanized": "Small Urbanized",
    "large_urbanized": "Large Urbanized",
    "major_urbanized": "Major Urbanized",
}

# ANALYST DEFAULT, flagged (not sourced): applied to every Rural link
# because this project has no per-link terrain source with usable coverage
# yet. scripts/hpms_to_faf_lrs_transfer.py's real HPMS Terrain_Type exists
# but matches only ~22% of national FAF5 miles (docs/HPMS_FAF_LRS_TRANSFER.md)
# and is not merged into the production road_links this costing reads --
# wiring it is a documented open item, not done here. "Rolling" (the middle
# of Flat/Rolling/Mountainous) is used rather than "Flat" specifically so
# this default doesn't systematically understate cost for the (unknown)
# share of rural mileage that is actually hilly.
TERRAIN_DEFAULT = "Rolling"

# ANALYST DEFAULT, flagged: of T24's 17 improvement types, this one is used
# as the single "repair in kind" basis for continuous flood-damage costing
# (no widening/capacity-adding scope, matching what a flood repair actually
# is) -- T24 itself has no "flood damage repair" row to select instead.
IMPROVEMENT_TYPE_DEFAULT = "Total Reconstruct Existing Lane"

_USD_PER_THOUSAND = 1_000.0


def load_t24_cp25(params_root=None) -> pd.DataFrame:
    from resiflow.tables import load_table

    return load_table(_TABLE_NAME, params_root=params_root)


def cp25_road_cost_usd_per_lane_mile(
    hpms_fclass: pd.Series,
    urban: pd.Series,
    urban_size_tier: pd.Series,
    *,
    terrain_type: pd.Series | None = None,
    improvement_type: str = IMPROVEMENT_TYPE_DEFAULT,
    params_root=None,
) -> pd.Series:
    """Per-link T24 CP25 reconstruction unit cost, in real USD per lane-mile.

    Parameters
    ----------
    hpms_fclass : real HPMS F-class (1-7), e.g. resiflow.hpms_fclass.
    urban : binary urban flag (1 = urban, 0 = rural) -- same field already
        used throughout this codebase (faf5_network.py's own ``urban``).
    urban_size_tier : T39's hpms_urban_size_tier (small_urban/.../rural),
        from resiflow.census_urban_area.urban_area_profile. Only consulted
        where urban == 1.
    terrain_type : optional real Flat/Rolling/Mountainous per link (not yet
        available project-wide -- see TERRAIN_DEFAULT). Falls back to
        TERRAIN_DEFAULT wherever None/missing.
    """
    t24 = load_t24_cp25(params_root=params_root)
    # Normalize every input to a plain 0..n-1-indexed Series immediately --
    # callers routinely pass boolean-mask-sliced subsets (non-contiguous
    # original index), which would otherwise misalign against the fresh
    # RangeIndex-backed Series built below (pandas raises IndexingError
    # rather than silently misaligning, which is how this was first caught).
    hpms_fclass = pd.Series(hpms_fclass).reset_index(drop=True)
    urban = pd.Series(urban).reset_index(drop=True)
    urban_size_tier = pd.Series(urban_size_tier).reset_index(drop=True)
    if terrain_type is not None:
        terrain_type = pd.Series(terrain_type).reset_index(drop=True)

    region = pd.Series(["Urban" if u == 1 else "Rural" for u in urban])
    functional_class = hpms_fclass.map(_FCLASS_TO_T24_NAME)

    subcategory = pd.Series(index=region.index, dtype=object)
    is_urban = region == "Urban"
    subcategory.loc[is_urban] = urban_size_tier[is_urban].map(
        _URBAN_TIER_TO_T24_SUBCATEGORY
    )
    # Real small-urban/rural overlap: Urban_Code==99998 ("small urban area",
    # urban==1) resolves to hpms_urban_size_tier=="small_urban" (correct,
    # maps above). The defensive fallback below only matters if urban==1 but
    # the tier join itself failed (e.g. missing urban_code) -- never silently
    # substitute "rural" terrain logic onto an urban link.
    subcategory.loc[is_urban & subcategory.isna()] = "Small Urban"

    if terrain_type is not None:
        subcategory.loc[~is_urban] = terrain_type[~is_urban].where(
            terrain_type[~is_urban].notna(), TERRAIN_DEFAULT
        )
    else:
        subcategory.loc[~is_urban] = TERRAIN_DEFAULT

    key = pd.DataFrame(
        {
            "region": region.to_numpy(),
            "functional_class": functional_class.to_numpy(),
            "subcategory_or_terrain": subcategory.to_numpy(),
            "improvement_type": improvement_type,
        }
    )
    merged = key.merge(
        t24[["region", "functional_class", "subcategory_or_terrain", "improvement_type",
             "cost_thousand_2018usd_per_lane_mile"]],
        on=["region", "functional_class", "subcategory_or_terrain", "improvement_type"],
        how="left",
    )
    return merged["cost_thousand_2018usd_per_lane_mile"] * _USD_PER_THOUSAND
