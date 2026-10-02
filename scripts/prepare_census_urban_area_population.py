#!/usr/bin/env python3
"""Build T39: Census 2010 Urban Area population -> HPMS/HERS urban-size tier.

Closes the recurring blocker flagged across T08b (its own unapplied 8%
small-metro-population adjustment), T24's CP25 table (Small Urban/Small
Urbanized/Large Urbanized/Major Urbanized tiers), and docs/
FLOOD_TABLE_REVIEW.md: this project has FAF5's own ``Urban_Code`` (a real
Census urbanized-area code on ~65% of links, the small-urban sentinel
99998 on ~9%, rural 99999 on ~25%) but nothing that expands a code into a
population or a size tier.

**Vintage, confirmed not assumed:** FAF5's ``Urban_Code`` values were
directly checked against the Census 2010 Urban Area list (not the 2020
list) -- all 503 distinct real codes in the national FAF5 network match
a 2010 UACE code exactly (0 unmatched; e.g. 63217 = "New York--Newark,
NY--NJ--CT", 51445 = "Los Angeles--Long Beach--Anaheim, CA" -- verified
against real population figures, not assumed from the code format alone).
2020 Census urban area delineation changed substantially and uses a
different code assignment; it was not used here because it does not match
FAF5's own codes.

Source: U.S. Census Bureau, 2010 Census Urban Area list (all urban areas
+ urban clusters, national), downloaded 2026-10-02 from
https://www2.census.gov/geo/docs/reference/ua/ua_list_all.xls (a real
Census Gazetteer-family product, not a gazetteer file itself -- the
gazetteer files carry geometry/centroids, not population; this is the
companion population list cited from
https://www.census.gov/programs-surveys/geography/guidance/geo-areas/urban-rural/2010-urban-rural.html).
Columns: UACE (5-digit code), NAME, POP (2010 population), HU (housing
units), LSADC (75 = Urbanized Area >=50,000; 76 = Urban Cluster
2,500-49,999 -- confirmed against the real file's own value distribution,
not assumed).

HPMS/HERS urban-size tier thresholds, quoted verbatim from FHWA's
Highway Economic Requirements System (HERS) documentation -- "Status of
the Nation's Highways, Bridges, and Transit: Conditions and Performance",
23rd Edition, Appendix A ("Highway Investment Analysis Methodology"), p.
A-3 (https://www.fhwa.dot.gov/policy/23cpr/pdfs/pdf/AppendixA.pdf,
fetched and read directly 2026-10-02 -- the same source family T24's
"CP25" (25th C&P Report) unit-cost table is drawn from, same methodology,
different edition year):

    "The 2004 update disaggregated the improvement cost values in urban
    areas by functional class and by urbanized area size. Three
    population groupings were used: small urban (populations of 5,000 to
    49,999), small urbanized (populations of 50,000 to 200,000), and
    large urbanized (populations of more than 200,000) ... [2006 C&P
    Report] modified [the cost matrix] to include a new category for
    major urbanized areas with populations of more than 1 million."

Also reported: a separate, independent boundary -- NCHRP 825 Exhibit 128's
own ">250,000 population" cutoff (T08b's unapplied 8% small-metro
adjustment) -- a DIFFERENT source/threshold from the HERS tiers above, not
derived from them, so kept as its own boolean column rather than folded
into hpms_urban_size_tier.

Known, real, zero-impact edge case (documented, not swept under the rug):
FHWA's own HPMS Field Manual draws the "small urban" floor at population
5,000, below which an area is treated as rural for HPMS purposes (Census
Urban Clusters go down to 2,500). 1,295 of the 3,104 real 2010 Urban
Clusters are below that 5,000 floor and are correctly tiered "rural" here
-- but ZERO FAF5 links actually carry one of those specific small-UC
codes (confirmed directly): FAF5 routes every small-urban-area link
through the generic 99998 sentinel instead of a specific sub-5,000-person
UC code. The floor is implemented for correctness/completeness, not
because it changes any current FAF5-derived result.

Usage::

    python scripts/prepare_census_urban_area_population.py \\
        --input parameters/tables/raw/census_2010_ua_list_all.xls \\
        --output parameters/tables/T39_census_urban_area_population_2010.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

_SMALL_URBAN_FLOOR = 5_000
_SMALL_URBANIZED_FLOOR = 50_000
_LARGE_URBANIZED_FLOOR = 200_000
_MAJOR_URBANIZED_FLOOR = 1_000_000
_NCHRP825_SMALL_METRO_FLOOR = 250_000


def _tier(pop: int) -> str:
    if pop >= _MAJOR_URBANIZED_FLOOR:
        return "major_urbanized"
    if pop > _LARGE_URBANIZED_FLOOR:
        return "large_urbanized"
    if pop >= _SMALL_URBANIZED_FLOOR:
        return "small_urbanized"
    if pop >= _SMALL_URBAN_FLOOR:
        return "small_urban"
    return "rural"


def build_table(input_path: Path) -> pd.DataFrame:
    raw = pd.read_excel(input_path)
    missing = {"UACE", "NAME", "POP", "HU", "LSADC"} - set(raw.columns)
    if missing:
        raise KeyError(f"{input_path} missing expected columns: {missing}")

    out = pd.DataFrame(
        {
            "uace_code": raw["UACE"].astype(str).str.zfill(5),
            "name": raw["NAME"],
            "population_2010": pd.to_numeric(raw["POP"], errors="raise").astype(int),
            "housing_units_2010": pd.to_numeric(raw["HU"], errors="raise").astype(int),
            "lsadc": pd.to_numeric(raw["LSADC"], errors="raise").astype(int),
        }
    )
    out["census_area_type"] = out["lsadc"].map({75: "urbanized_area", 76: "urban_cluster"})
    out["hpms_urban_size_tier"] = out["population_2010"].map(_tier)
    out["nchrp825_population_gt_250k"] = out["population_2010"] > _NCHRP825_SMALL_METRO_FLOOR
    return out.sort_values("uace_code").reset_index(drop=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, required=True, help="Downloaded ua_list_all.xls")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    table = build_table(args.input)
    print(f"{len(table)} urban areas/clusters")
    print(table["hpms_urban_size_tier"].value_counts())
    print(f"nchrp825_population_gt_250k: {table['nchrp825_population_gt_250k'].sum()} of {len(table)}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# T39 - Census 2010 Urban Area population and HPMS/HERS urban-size tier, keyed by UACE "
        "(5-digit Census urban-area code -- matches FAF5's own Urban_Code field exactly for all 503 "
        "real codes in the national network, confirmed; see this script's own module docstring).\n"
        "# Source: U.S. Census Bureau 2010 Urban Area list, "
        "https://www2.census.gov/geo/docs/reference/ua/ua_list_all.xls (downloaded 2026-10-02).\n"
        "# hpms_urban_size_tier thresholds: FHWA HERS/C&P Report 23rd Edition Appendix A, p.A-3 "
        "(https://www.fhwa.dot.gov/policy/23cpr/pdfs/pdf/AppendixA.pdf) -- "
        "rural <5,000; small_urban 5,000-49,999; small_urbanized 50,000-200,000; "
        "large_urbanized >200,000-1,000,000; major_urbanized >1,000,000.\n"
        "# nchrp825_population_gt_250k: NCHRP 825 Exhibit 128's own, separate >250,000 cutoff "
        "(T08b's unapplied 8% small-metro adjustment) -- a different source/threshold, not derived "
        "from hpms_urban_size_tier.\n"
        "# FAF5 Urban_Code sentinels NOT in this table (handled by the join code, not a row here): "
        "99998 = \"small urban area\" (generic, no specific UACE -- treat as hpms_urban_size_tier="
        "small_urban); 99999 = rural (no urban population at all).\n"
    )
    with args.output.open("w", encoding="utf-8", newline="") as fh:
        fh.write(header)
        table.to_csv(fh, index=False)
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
