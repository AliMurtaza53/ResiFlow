"""Build the finale multihazard comparison figures FROM REAL PIPELINE OUTPUT
on disk. Previously this hand-transcribed dollar figures from Hopper logs
into a HAZARDS list (see git history before 2026-09-08 for that version) --
that meant every number here had to be re-typed by hand after each run, with
no way to tell a stale transcription from a real change. Everything below is
read live from the results tree instead, using the same loaders
scripts/visualizations/viz_data_loaders.py already provides (and Script 4
itself uses for its own cost-CSV output), so this now needs real network
access -- run on Hopper (or wherever conus_nandu_v1's `results/` tree is
reachable, i.e. wherever RESIFLOW_CONFIG_PATH/NIRD_CONFIG_PATH point), same
as build_finale_damage_maps.py. It can no longer run standalone on a laptop
with only the small summary CSV.

Which hazards are included and what they're called lives in
finale_hazards.py (shared with build_finale_damage_maps.py) -- that's a
run-selection config, not the hardcoded data this rewrite removes.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "visualizations"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pandas as pd
from resiflow.utils import load_config
from viz_data_loaders import (
    load_direct_damage_by_asset_type,
    load_freight_industry_mix,
    plot_freight_industry_breakdown,
    plot_multihazard_cost_panels,
    plot_ranked_cost_by_asset_type,
    summarize_single_scenario,
)

from finale_hazards import VARIANT, finale_hazards

OUT_DIR = Path(__file__).resolve().parent

base_path = Path(load_config()["paths"]["soge_clusters"])
results_root = base_path.parent / "results"

rows = []
for hz in finale_hazards():
    row = summarize_single_scenario(
        results_root,
        variant=VARIANT,
        depth_key=hz.scenario_param,
        flood_key=hz.event_key,
    )
    row["hazard_label"] = hz.hazard_label
    row["hazard_type"] = hz.hazard_type
    row["hazard_subtype"] = hz.hazard_subtype
    row["depth_key"] = hz.scenario_param
    row["flood_key"] = hz.event_key
    rows.append(row)

summary = pd.DataFrame(rows)

# direct_damage_usd correction: cost_matrix_by_scenario.csv's own
# direct_damage_total_usd column can be stale/wrong for a scenario whose
# Script-3 damage CSV was concurrently overwritten by a sibling hazard job on
# the same machine -- a real race condition (Script 3 rewrote the same
# shared per-scenario damage CSV for every hazard it found on disk, non-
# atomically), fixed at the source 2026-08-26 in 3_damage_analysis.py, but
# not retroactive for CSVs already written before the fix. Confirmed on this
# variant: earthquake_401 and landslide_501 were off by 393x and 9.3x via
# this path. The dedicated per-asset-type JSON
# (scripts/compute_direct_damage_by_asset_type.py) was independently cross-
# checked against an early damage_summary.csv snapshot and found correct, so
# prefer its bridge+road sum wherever it exists; fall back to
# summarize_single_scenario's own value only for a hazard that hasn't had
# that script run yet (shows as "asset-type split pending" in figure 2).
asset_type_split = load_direct_damage_by_asset_type(results_root, VARIANT, summary)


def _resolved_direct_damage_usd(row: pd.Series) -> float:
    split = asset_type_split.get(str(row["hazard_label"]))
    if split:
        return (float(split.get("bridge", 0.0)) + float(split.get("road", 0.0))) * 1_000_000.0
    return float(row.get("direct_damage_usd", 0.0))


summary["direct_damage_usd"] = summary.apply(_resolved_direct_damage_usd, axis=1)
summary["combined_total_usd"] = (
    summary["direct_damage_usd"]
    + summary["rerouting_cost_freight_usd"]
    + summary["rerouting_cost_passenger_usd"]
    + summary["isolation_cost_usd"]
)
summary.to_csv(OUT_DIR / "finale_summary_day0_freight_only.csv", index=False)

# Real per-hazard freight commodity mix -- reads rerouting_analysis/<variant>/
# <depth_key>/<flood_key>/freight_industry_mix.json, written by
# scripts/compute_freight_industry_mix.py. A hazard missing that file (script
# not yet run, or zero disrupted freight OD pairs) falls back to the national
# baseline share inside plot_freight_industry_breakdown -- shown there as
# "(real share pending)", not silently faked.
industry_shares = load_freight_industry_mix(results_root, VARIANT, summary)

# Winter storm's direct cost is excluded from the quantitative comparison,
# not scaled around -- it's the flood-shim (snow depth repackaged as fake
# flood depth, priced with flood repair-cost tables) applied at full-CONUS
# extent, and it is not a credible number: independent grey-literature
# estimates for the real 2016 Winter Storm Jonas put total damage/economic
# impact in the $500M-$3B range, while this placeholder reports ~$498.7B --
# roughly 166x to 1,000x too high. No axis choice (log or otherwise) makes a
# wrong number honest to show; excluding it and stating why is the correct
# call per the Urban Institute style guide's own reasoning against log axes.
WINTER_STORM_EXCLUSION = {
    "Winter storm (Jonas)": (
        "flood-shim direct cost is ~166-1,000x independent estimates "
        "for the real 2016 event -- pending a real clearance-cost model"
    ),
}

# Excluded 2026-09-04 at user request: a single-edge closure with ~$23K
# direct damage and zero disrupted freight candidates isn't a meaningful
# comparison point against hazards costing $M-$B -- it reads as a rounding
# error on any shared axis. Kept in finale_summary_day0_freight_only.csv
# (not deleted from the underlying data), just dropped from the visual
# comparisons, same pattern as WINTER_STORM_EXCLUSION.
FLOOD_EXCLUSION = {
    "Flood": (
        "single-edge closure, negligible direct damage, zero disrupted "
        "freight candidates -- not a meaningful comparison point against "
        "hazards costing $M-$B"
    ),
}
EXCLUDED_HAZARDS = {**WINTER_STORM_EXCLUSION, **FLOOD_EXCLUSION}

fig1, _ = plot_multihazard_cost_panels(summary, exclude_hazards=EXCLUDED_HAZARDS)
fig1.savefig(OUT_DIR / "01_multihazard_cost_comparison.png", dpi=150, bbox_inches="tight")

fig2, _ = plot_ranked_cost_by_asset_type(
    summary, asset_type_split=asset_type_split, exclude_hazards=EXCLUDED_HAZARDS
)
fig2.savefig(OUT_DIR / "02_ranked_cost_by_asset_type.png", dpi=150, bbox_inches="tight")

# plot_freight_industry_breakdown has no exclude_hazards param -- it plots
# whatever hazards are in `summary` directly, so filter Flood (only --
# winter storm has a real industry_shares entry and was never excluded from
# this figure) out of the frame passed to this one call instead (summary
# itself, and the CSV already written above, are untouched).
fig3, _ = plot_freight_industry_breakdown(
    summary[~summary["hazard_label"].isin(FLOOD_EXCLUSION)].reset_index(drop=True),
    industry_shares=industry_shares,
)
fig3.savefig(OUT_DIR / "03_freight_industry_breakdown.png", dpi=150, bbox_inches="tight")

print("Wrote 3 figures + summary CSV to", OUT_DIR)
