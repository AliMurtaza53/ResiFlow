#!/usr/bin/env python3
"""Compare Script 3 direct damage totals to a mock HAZUS benchmark CSV (RQ1 stub)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from resiflow.damage_aggregation import total_direct_damage_usd
from resiflow.utils import get_results_variant, load_config


def load_model_totals(results_root: Path, variant: str) -> pd.DataFrame:
    damage_dir = results_root / "damage_analysis" / variant
    rows = []
    for path in sorted(damage_dir.glob("intersections_*_with_damage_values.csv")):
        event_id = path.stem.replace("intersections_", "").replace("_with_damage_values", "")
        df = pd.read_csv(path)
        rows.append(
            {
                "event_id": event_id,
                "model_direct_damage_usd": total_direct_damage_usd(df),
                "source_file": str(path),
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark-csv", type=Path, required=True)
    parser.add_argument("--results-root", type=Path, help="Parent of damage_analysis/")
    parser.add_argument("--variant", help="Results variant (default: env or toy_sioux_falls_multihazard)")
    parser.add_argument("--out-csv", type=Path, help="Optional comparison report path")
    args = parser.parse_args()

    config = load_config()
    base = Path(config["paths"]["soge_clusters"])
    results_root = args.results_root or (base.parent / "results")
    variant = args.variant or get_results_variant() or "toy_sioux_falls_multihazard"

    model = load_model_totals(results_root, variant)
    bench = pd.read_csv(args.benchmark_csv)
    bench["event_id"] = bench["event_id"].astype(str)
    model["event_id"] = model["event_id"].astype(str)

    report = bench.merge(model, on="event_id", how="left")
    report["model_direct_damage_usd"] = report["model_direct_damage_usd"].fillna(0.0)
    report["abs_diff_usd"] = report["model_direct_damage_usd"] - report["direct_damage_usd_mock"]
    report["ratio_model_over_mock"] = report["model_direct_damage_usd"] / report["direct_damage_usd_mock"].replace(0, pd.NA)

    print(f"Mock HAZUS comparison | variant={variant}")
    print(report[["event_id", "hazard_type", "direct_damage_usd_mock", "model_direct_damage_usd", "abs_diff_usd", "ratio_model_over_mock"]].to_string(index=False))

    if args.out_csv:
        args.out_csv.parent.mkdir(parents=True, exist_ok=True)
        report.to_csv(args.out_csv, index=False)
        print(f"Wrote {args.out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
