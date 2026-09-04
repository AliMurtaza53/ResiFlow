"""Build the finale multihazard comparison figures from real conus_nandu_v1
Hopper results (day0 snapshot, freight-only -- passenger rerouting was never
run for this batch, confirmed by directory listing on Hopper: no
edge_flows_passenger_*/cost_matrix_passenger_* files exist for any scenario).

6 of the 9 registered hazard scenarios have completed successfully as of
2026-08-28: flood(301), harvey(304), earthquake-Mineral(401),
earthquake-New-Madrid(403), landslide(501), winter_storm-Jonas(601).
winter_storm-Uri/Elliott/Snowmageddon(602/603/604) are still in flight
(48h+ elapsed against a now-96h budget after two earlier timeouts) --
excluded here, not silently zeroed. New Madrid's asset-type split and
freight commodity mix have not been derived yet (compute_direct_damage_by_
asset_type.py / compute_freight_industry_mix.py not yet run for scenario
403) -- it appears in panels 1/2 (direct cost source doesn't need them) but
shows "pending" in panel 2's asset-type breakdown and is absent from panel 3.

DIRECT DAMAGE SOURCE (2026-08-26 correction): direct_damage_usd below comes
from scripts/compute_direct_damage_by_asset_type.py's bridge+road sum (run
directly against each scenario's damage_analysis/<variant>/<depth>/
intersections_<event>_with_damage_values.csv), NOT from cost_matrix_by_
scenario.csv's direct_damage_total_usd column. Cross-checking the two
sources found flood/harvey/winter_storm agree exactly (ratio 1.00x), but
earthquake_401 and landslide_501 disagreed by 393x and 9.3x respectively --
traced to a real race condition: Script 3 rewrites the SAME shared per-
scenario damage CSV for every hazard it finds on disk, every time ANY hazard
job runs Script 3, with a plain (non-atomic) to_csv() call. earthquake_401
and landslide_501 both ran concurrently with other Script-3-running jobs on
Hopper on 2026-08-24; their Script 4 step evidently read a transiently
truncated version of their own damage CSV mid-overwrite by a sibling job.
The asset-type-script numbers are corroborated by an independent
damage_summary.csv snapshot captured earlier in the same investigation.
Fixed at the source in 3_damage_analysis.py (atomic tmp-file + os.replace).
rerouting_cost/isolation_cost are NOT affected (Script 4 computes those from
the routing/capacity state directly, not from this damage CSV's dollar
column) -- only combined_total_usd was recomputed here to reflect the
corrected direct damage.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "visualizations"))

import pandas as pd
from viz_data_loaders import (
    plot_freight_industry_breakdown,
    plot_multihazard_cost_panels,
    plot_ranked_cost_by_asset_type,
)

OUT_DIR = Path(__file__).resolve().parent

HAZARDS = [
    {
        "hazard_label": "Flood",
        "hazard_type": "flood",
        "hazard_subtype": "flood_surface",
        "variant": "conus_nandu_v1",
        "direct_damage_usd": 23426.73,
        "rerouting_cost_freight_usd": 0.0,
        "rerouting_cost_passenger_usd": 0.0,
        # No rerouting_analysis output at all for 301 -- 0 disrupted freight
        # candidates (1-edge closure never binds a capacity-critical path).
        "isolation_cost_usd": 0.0,
    },
    {
        "hazard_label": "Harvey",
        "hazard_type": "flood",
        "hazard_subtype": "flood_harvey_houston",
        "variant": "conus_nandu_v1",
        "direct_damage_usd": 10069329955.781158,
        "rerouting_cost_freight_usd": 74663.09767732024,
        "rerouting_cost_passenger_usd": 0.0,
        "isolation_cost_usd": 790808.355262991,
    },
    {
        "hazard_label": "Earthquake (Mineral)",
        "hazard_type": "earthquake",
        "hazard_subtype": "earthquake_shakemap_mineral",
        "variant": "conus_nandu_v1",
        "direct_damage_usd": 5077006220.174127,  # corrected -- see module docstring
        "rerouting_cost_freight_usd": 344189.58192921523,
        "rerouting_cost_passenger_usd": 0.0,
        "isolation_cost_usd": 92122.70490477204,
    },
    {
        "hazard_label": "Earthquake (New Madrid)",
        "hazard_type": "earthquake",
        "hazard_subtype": "earthquake_new_madrid_m75_scenario",
        "variant": "conus_nandu_v1",
        "direct_damage_usd": 1942465109.428291,  # from its own cost_matrix_by_scenario.csv, 2026-08-27
        "rerouting_cost_freight_usd": 8421765.552871466,
        "rerouting_cost_passenger_usd": 0.0,
        "isolation_cost_usd": 7391539.367033079,
    },
    {
        "hazard_label": "Landslide",
        "hazard_type": "landslide",
        "hazard_subtype": "landslide",
        "variant": "conus_nandu_v1",
        "direct_damage_usd": 37219159.63763988,  # corrected -- see module docstring
        "rerouting_cost_freight_usd": 289.21414234582335,
        "rerouting_cost_passenger_usd": 0.0,
        "isolation_cost_usd": 77.52609556229736,
    },
    {
        "hazard_label": "Winter storm (Jonas)",
        "hazard_type": "winter_storm",
        "hazard_subtype": "winter_storm",
        "variant": "conus_nandu_v1",
        "direct_damage_usd": 498713330538.9027,
        "rerouting_cost_freight_usd": 20650892.015225947,
        "rerouting_cost_passenger_usd": 0.0,
        "isolation_cost_usd": 39240543.79492121,
    },
]
# All isolation_cost_usd values are day-0 `isolation_cost` (the VOT-anchored SC
# term, not the separate $50/day isolation_cost_usd SA-seam column despite the
# name collision -- see docs/PROJECT_LOG.md's isolation-rate entry) read
# directly from each scenario's own cost_matrix_by_scenario.csv on Hopper,
# 2026-08-29. combined_total_usd is now an explicit sum of all three terms,
# matching Script 4's own combined_total_cost column exactly (cross-checked).
for row in HAZARDS:
    row["combined_total_usd"] = (
        row["direct_damage_usd"] + row["rerouting_cost_freight_usd"]
        + row["rerouting_cost_passenger_usd"] + row["isolation_cost_usd"]
    )
summary = pd.DataFrame(HAZARDS)
summary.to_csv(OUT_DIR / "finale_summary_day0_freight_only.csv", index=False)

# Real per-hazard direct-damage bridge/road split (MUSD), from
# scripts/compute_direct_damage_by_asset_type.py run on Hopper 2026-08-26
# against each scenario's own damage_analysis CSV.
asset_type_split = {
    "Flood": {"bridge": 0.0, "road": 0.023426734233994502},
    "Harvey": {"bridge": 10010.255525256945, "road": 59.074430524213184},
    "Earthquake (Mineral)": {"bridge": 5076.501255738951, "road": 0.5049644354617034},
    "Landslide": {"bridge": 37.21560078568696, "road": 0.0035588519529237105},
    "Winter storm (Jonas)": {"bridge": 498653.8745943354, "road": 59.45594456740155},
}

# Real per-hazard freight commodity mix, from
# scripts/compute_freight_industry_mix.py run on Hopper 2026-08-26. Flood/301
# has no disrupted freight candidates (0 candidates, 1-edge closure) so its
# shares are genuinely empty, not missing data.
industry_shares = {
    "Harvey": {
        "sctg3499": 0.12546977335556803, "sctg1519": 0.13182748296353303,
        "sctg1014": 0.22456057396082807, "sctg2033": 0.2595231693386357,
        "sctg0109": 0.25861900038143526,
    },
    "Earthquake (Mineral)": {
        "sctg1519": 0.14191512943943244, "sctg0109": 0.25449481863637996,
        "sctg3499": 0.11302087631041834, "sctg1014": 0.22842886820987274,
        "sctg2033": 0.2621403074038964,
    },
    "Landslide": {
        "sctg1014": 0.20261598517126492, "sctg2033": 0.2685475233539762,
        "sctg1519": 0.15195125391324227, "sctg3499": 0.11697638823421283,
        "sctg0109": 0.2599088493273037,
    },
    "Winter storm (Jonas)": {
        "sctg0109": 0.2532394210274836, "sctg3499": 0.1336464273670967,
        "sctg1014": 0.19598504964350702, "sctg2033": 0.2723648758684349,
        "sctg1519": 0.1447642260934778,
    },
}

# Winter storm's direct cost is excluded from the quantitative comparison,
# not scaled around -- it's the flood-shim (snow depth repackaged as fake
# flood depth, priced with flood repair-cost tables) applied at full-CONUS
# extent, and it is not a credible number: independent grey-literature
# estimates for the real 2016 Winter Storm Jonas put total damage/economic
# impact in the $500M-$3B range, while this placeholder reports $498.7B --
# roughly 166x to 1,000x too high. No axis choice (log or otherwise) makes a
# wrong number honest to show; excluding it and stating why is the correct
# call per the Urban Institute style guide's own reasoning against log axes.
WINTER_STORM_EXCLUSION = {
    "Winter storm (Jonas)": (
        "flood-shim direct cost is $498.7B vs. $500M-$3B in independent estimates "
        "for the real 2016 event -- pending a real clearance-cost model"
    ),
}

fig1, _ = plot_multihazard_cost_panels(summary, exclude_hazards=WINTER_STORM_EXCLUSION)
fig1.savefig(OUT_DIR / "01_multihazard_cost_comparison.png", dpi=150, bbox_inches="tight")

fig2, _ = plot_ranked_cost_by_asset_type(
    summary, asset_type_split=asset_type_split, exclude_hazards=WINTER_STORM_EXCLUSION
)
fig2.savefig(OUT_DIR / "02_ranked_cost_by_asset_type.png", dpi=150, bbox_inches="tight")

fig3, _ = plot_freight_industry_breakdown(summary, industry_shares=industry_shares)
fig3.savefig(OUT_DIR / "03_freight_industry_breakdown.png", dpi=150, bbox_inches="tight")

print("Wrote 3 figures + summary CSV to", OUT_DIR)
