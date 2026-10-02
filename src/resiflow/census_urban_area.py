"""FAF5 Urban_Code -> real Census population -> HPMS/HERS urban-size tier.

Closes the blocker shared by T08b (its own unapplied 8% small-metro
population adjustment) and T24's CP25 table (Small Urban/Small Urbanized/
Large Urbanized/Major Urbanized tiers) -- see
``parameters/tables/T39_census_urban_area_population_2010.csv`` and
``scripts/prepare_census_urban_area_population.py`` for the full
provenance (real Census 2010 Urban Area list, confirmed exact-match
vintage against FAF5's own Urban_Code, and the FHWA HERS/C&P Appendix A
source for the tier thresholds, quoted verbatim there).

FAF5's raw ``Urban_Code`` has three kinds of values, all handled here:
  - a real 5-digit Census UACE code (~65% of links) -> joined against T39.
  - ``99998`` ("small urban area", generic -- no specific UACE exists for
    it) -- treated as ``hpms_urban_size_tier="small_urban"`` directly
    (that is literally what the sentinel means), with no population
    figure (not fabricated) and ``nchrp825_population_gt_250k=False``
    (small urban areas by definition cap under 50,000, well under the
    250,000 cutoff).
  - ``99999`` (rural) or missing -- ``hpms_urban_size_tier="rural"``,
    no population, ``nchrp825_population_gt_250k=False``.
"""

from __future__ import annotations

import pandas as pd

_SMALL_URBAN_SENTINEL = "99998"
_RURAL_SENTINEL = "99999"


def _load_t39(params_root=None) -> pd.DataFrame:
    from resiflow.tables import load_table

    table = load_table("T39_census_urban_area_population_2010", params_root=params_root)
    table = table.copy()
    # uace_code round-trips through CSV as an int (leading zeros lost) --
    # see T39's own header note. Re-pad before using as a join key.
    table["uace_code"] = table["uace_code"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(5)
    return table


def urban_area_profile(urban_code: pd.Series, *, params_root=None) -> pd.DataFrame:
    """{hpms_urban_size_tier, population_2010, nchrp825_population_gt_250k}
    per link, from FAF5's own ``Urban_Code`` -- see module docstring for
    how the two sentinel values and real UACE codes are each handled.
    """
    t39 = _load_t39(params_root)
    by_code = t39.set_index("uace_code")

    code = urban_code.astype(str).str.strip()
    code = code.where(code.str.len() > 0, None)
    try:
        code = code.str.replace(r"\.0$", "", regex=True).str.zfill(5)
    except AttributeError:
        pass

    tier = code.map(by_code["hpms_urban_size_tier"])
    population = pd.to_numeric(code.map(by_code["population_2010"]), errors="coerce")
    gt_250k = code.map(by_code["nchrp825_population_gt_250k"])

    is_small_urban_sentinel = code == _SMALL_URBAN_SENTINEL
    tier.loc[is_small_urban_sentinel] = "small_urban"
    gt_250k.loc[is_small_urban_sentinel] = False

    is_rural = (code == _RURAL_SENTINEL) | code.isna()
    tier.loc[is_rural] = "rural"
    gt_250k.loc[is_rural] = False

    return pd.DataFrame(
        {
            "hpms_urban_size_tier": tier,
            "population_2010": population,
            "nchrp825_population_gt_250k": gt_250k.astype("boolean"),
        },
        index=urban_code.index,
    )


__all__ = ["urban_area_profile"]
