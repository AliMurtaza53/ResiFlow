"""Earthquake road liquefaction direct cost -- HAZUS 6.1 methodology, T31.

Closes the real, documented gap in ``hazards/hazus_bridge.py``:
``compute_row_direct_damage_musd()``'s earthquake branch returns ``$0`` for
every non-bridge road, because HAZUS's own roadway fragility (Table 7-5) is
ground-failure (PGD) only, and this project has never computed a
liquefaction-derived PGD for the earthquake hazard itself (only landslide's
separate Newmark PGD exists). ``parameters/tables/T31_earthquake_road_
liquefaction_pga_lookup.csv`` -- an intern-supplied, full HAZUS-methodology
grid (magnitude x susceptibility_class x road_tier x PGA -> direct cost) --
supplies exactly that missing PGA -> liquefaction -> PGD -> cost chain, GIVEN
a susceptibility_class per road segment.

That susceptibility class now has one real (if regional, not national)
source: ``scripts/prepare_cusec_liquefaction_susceptibility.py`` rasterizes 8
CUSEC state liquefaction-susceptibility maps (AL/AR/IL/IN/KY/MO/MS/TN) into
``liquefaction_class_code`` (0-5, HAZUS Table 4-8 scale), intersected per
segment the same way Sa(1.0s) is (see disruption/earthquake.py's
``liquefaction_class`` branch). This footprint matches the New Madrid M7.5
scenario (403) almost exactly (see hazards/real_events.py's
RealEarthquakeNewMadridScenarioSource) -- Mineral (401, VA) and Cascadia
(404, WA/OR) have no susceptibility coverage and correctly stay $0, not
backfilled with an assumed class.

Gated behind ``vulnerability.use_table_earthquake_liquefaction`` (default
``False``) -- see parameters/unified_parameters.json.
"""

from __future__ import annotations

import math
from functools import lru_cache

import pandas as pd

from resiflow.hazards.hazus_bridge import _MAJOR_ROAD_CLASSIFICATIONS, _safe_str
from resiflow.tables import interpolate, load_table

_TABLE_NAME = "T31_earthquake_road_liquefaction_pga_lookup"

# Confirmed directly from the CUSEC source shapefiles' own attribute tables
# (Arkansas ships both the numeric TYPE code and a text L_S_Class label in
# the same row) -- not an invented crosswalk. 0 ("unclassified/water" in the
# source) is intentionally absent: it means "no liquefiable unit mapped",
# not "no data", and is handled as a $0/"no" short-circuit below, same
# outcome as a missing code but a distinct real-world meaning.
_SUSCEPTIBILITY_CODE_TO_HAZUS = {1: "VeryLow", 2: "Low", 3: "Moderate", 4: "High", 5: "VeryHigh"}

# T31's own magnitude grid (5.0-8.0 step 0.5, confirmed from its header).
# Nearest-grid-point snapping -- see docs/HAZARD_TABLE_INTEGRATION_RUNBOOK.md
# Track A Step 2 ("nearest-grid-point lookup is probably fine given the
# table's fine PGA step; confirm no gaps before assuming interpolation is
# even necessary" -- true of magnitude here too, since New Madrid (403,
# M7.5) lands exactly on a grid point).
_MAGNITUDE_GRID = (5.0, 5.5, 6.0, 6.5, 7.0, 7.5, 8.0)

# Per-scenario magnitude -- HazardScenario carries no magnitude field, so
# this is the one place it's recorded for this lookup. Only scenarios with
# real susceptibility coverage need an entry; an unmapped hazard_subtype
# falls through to $0 in road_liquefaction_direct_cost_usd_per_km below.
SCENARIO_MAGNITUDE_MW: dict[str, float] = {
    "earthquake_new_madrid_m75_scenario": 7.5,
}


@lru_cache(maxsize=1)
def _load_t31() -> pd.DataFrame:
    return load_table(_TABLE_NAME)


def _nearest_magnitude(magnitude_mw: float) -> float:
    return min(_MAGNITUDE_GRID, key=lambda m: abs(m - magnitude_mw))


def road_liquefaction_direct_cost_usd_per_km(
    *,
    hazard_subtype: str | None,
    susceptibility_code: float | int | None,
    road_classification: str | None,
    pga_g: float | None,
) -> tuple[float, str]:
    """T31 lookup: (direct_cost_usd_per_km, governing damage level).

    Returns ``(0.0, "no")`` whenever any required input is missing or
    outside real coverage -- never fabricates a value for an unmapped
    scenario/segment (see module docstring).
    """
    magnitude_mw = SCENARIO_MAGNITUDE_MW.get(hazard_subtype or "")
    if magnitude_mw is None:
        return 0.0, "no"

    if pga_g is None or (isinstance(pga_g, float) and math.isnan(pga_g)) or pga_g <= 0:
        return 0.0, "no"

    if susceptibility_code is None or (isinstance(susceptibility_code, float) and math.isnan(susceptibility_code)):
        return 0.0, "no"
    code = int(round(float(susceptibility_code)))
    susceptibility_class = _SUSCEPTIBILITY_CODE_TO_HAZUS.get(code)
    if susceptibility_class is None:
        return 0.0, "no"  # code 0 (no liquefiable unit) or an unrecognized/nodata code

    tier = "HRD1_major" if _safe_str(road_classification).strip().lower() in _MAJOR_ROAD_CLASSIFICATIONS else "HRD2_urban"

    table = _load_t31()
    nearest_mag = _nearest_magnitude(magnitude_mw)
    subset = table[
        (table["magnitude_Mw"] == nearest_mag)
        & (table["susceptibility_class"] == susceptibility_class)
        & (table["road_tier"] == tier)
    ]
    if subset.empty:
        raise ValueError(
            f"T31 has no rows for magnitude={nearest_mag}, susceptibility_class={susceptibility_class!r}, "
            f"road_tier={tier!r} -- table schema may have changed."
        )

    pga_clamped = min(max(float(pga_g), 0.0), float(subset["pga_g"].max()))
    cost_usd_per_km = interpolate(subset, pga_clamped, "direct_cost_usd_per_km", axis_column="pga_g")
    # T31's p_slight/p_moderate/p_extensive_complete are DISCRETE (mutually
    # exclusive) state probabilities that partition p_liquefaction, NOT
    # cumulative exceedance probabilities like hazus_bridge.py's own
    # lognormal fragility curves -- confirmed by direct inspection: at a
    # fixed magnitude/class/tier, p_slight+p_moderate+p_extensive_complete
    # equals the table's own p_liquefaction column exactly (e.g. M7.5/
    # VeryHigh/HRD1_major/PGA=0.4g: 0.004225+0.047955+0.184457=0.236637 ~=
    # p_liquefaction 0.236893, rounding only), and
    # expected_damage_ratio == p_slight*0.05 + p_moderate*0.20 +
    # p_extensive_complete*0.70 (this project's own road damage ratios,
    # DAMAGE_RATIO_BY_ASSET_AND_STATE in hazus_bridge.py) confirms it, not a
    # cumulative-exceedance construction where p_slight >= p_moderate would
    # be required (the raw grid violates that inequality throughout,
    # ruling out the cumulative reading).
    p_slight = interpolate(subset, pga_clamped, "p_slight", axis_column="pga_g")
    p_moderate = interpolate(subset, pga_clamped, "p_moderate", axis_column="pga_g")
    p_ext_complete = interpolate(subset, pga_clamped, "p_extensive_complete", axis_column="pga_g")

    probs = {
        "no": max(0.0, 1.0 - p_slight - p_moderate - p_ext_complete),
        "minor": p_slight,
        "moderate": p_moderate,
        "extensive": p_ext_complete,
    }
    damage_level = max(probs, key=probs.get)
    return float(cost_usd_per_km), damage_level


__all__ = ["road_liquefaction_direct_cost_usd_per_km", "SCENARIO_MAGNITUDE_MW"]
