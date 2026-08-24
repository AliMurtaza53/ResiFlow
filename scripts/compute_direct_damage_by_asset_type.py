#!/usr/bin/env python3
"""Split one hazard event's direct damage cost into bridge vs. road totals.

Companion to scripts/compute_freight_industry_mix.py, same motivation: a
richer decomposition than a single summed direct_damage_total, following
Bor et al. 2026 (arXiv:2605.23053)'s Fig. 5 pattern of ranking hazards by
total damage alongside a companion panel decomposed by asset type.

Unlike the freight-mix script, this only needs Script 3's own output
(results/damage_analysis/<variant>/<scenario_param>/intersections_<event>_
with_damage_values.csv) -- no dependency on Script 4's disrupted-candidate
resolution, since direct damage is priced per-row in Script 3 regardless of
hazard type (both the HAZUS branch for earthquake/landslide and
calculate_damage()'s flood-curve branch write the same
direct_damage_mean_musd/road_label columns via
damage_aggregation.add_consolidated_damage_columns -- confirmed by reading
3_damage_analysis.py directly, not assumed).

Usage::

    python scripts/compute_direct_damage_by_asset_type.py 301 1 \
        --hazard-label flood --output direct_damage_by_asset_type_301_1.json
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import pandas as pd

from resiflow.utils import get_results_variant, load_config


def compute_by_asset_type(csv_path: Path) -> dict:
    df = pd.read_csv(csv_path)
    if df.empty or "direct_damage_mean_musd" not in df.columns:
        return {"by_asset_type_musd": {}, "total_musd": 0.0, "n_rows": 0}

    road_label = df.get("road_label")
    if road_label is None:
        road_label = pd.Series(["road"] * len(df), index=df.index)
    is_bridge = road_label.astype(str).str.lower().eq("bridge")
    musd = pd.to_numeric(df["direct_damage_mean_musd"], errors="coerce").fillna(0.0)

    bridge_total = float(musd[is_bridge].sum())
    road_total = float(musd[~is_bridge].sum())
    return {
        "by_asset_type_musd": {"bridge": bridge_total, "road": road_total},
        "total_musd": bridge_total + road_total,
        "n_rows": int(len(df)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("scenario_param", type=int)
    parser.add_argument("event_id")
    parser.add_argument("--results-variant", default=None)
    parser.add_argument("--hazard-label", default=None)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    logging.basicConfig(format="%(asctime)s %(process)d %(filename)s %(message)s", level=logging.INFO)

    if args.results_variant:
        import os

        os.environ["RESIFLOW_RESULTS_VARIANT"] = args.results_variant
        os.environ["NIRD_RESULTS_VARIANT"] = args.results_variant

    base_path = Path(load_config()["paths"]["soge_clusters"])
    results_variant = get_results_variant()
    csv_path = (
        base_path.parent
        / "results"
        / "damage_analysis"
        / results_variant
        / str(args.scenario_param)
        / f"intersections_{args.event_id}_with_damage_values.csv"
    )
    if not csv_path.exists():
        raise FileNotFoundError(f"Script 3 output not found: {csv_path}")

    result = compute_by_asset_type(csv_path)
    result["hazard_label"] = args.hazard_label or str(args.scenario_param)
    result["scenario_param"] = args.scenario_param
    result["event_id"] = args.event_id
    result["results_variant"] = results_variant

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2))
    logging.info("Wrote %s: %s", args.output, result["by_asset_type_musd"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
