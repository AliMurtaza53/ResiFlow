#!/usr/bin/env python3
"""Descriptive statistics for a downloaded NBI structures table.

Answers the questions that motivated adding the classification columns to
scripts/download_nbi_bridges.py: how many structures, what's their
characteristic size/age, how are they distributed geographically, and --
specifically -- are they limited to interstates/state highways, or does the
inventory include ramps and local roads too.

Usage::

    python scripts/nbi_descriptive_stats.py --nbi /path/to/nbi_bridges_2024.parquet
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nbi", type=Path, required=True)
    args = parser.parse_args()

    df = pd.read_parquet(args.nbi)

    print("=" * 70)
    print(f"NBI structures: {len(df):,} across {df['state'].nunique()} states/territories")
    print("=" * 70)

    print("\n--- Geographic spread: top 15 states by structure count ---")
    print(df["state"].value_counts().head(15).to_string())

    print("\n--- Size/age characteristics ---")
    print(df[["deck_width_m", "structure_length_m", "year_built"]].describe().to_string())

    print("\n--- Route ownership (ROUTE_PREFIX_005B) ---")
    counts = df["route_prefix"].value_counts(dropna=False)
    for label, n in counts.items():
        print(f"  {label if pd.notna(label) else '(unrecorded)':30s} {n:>8,}  ({n / len(df):.1%})")

    print("\n--- Functional class (FUNCTIONAL_CLASS_026) ---")
    counts = df["functional_class"].value_counts(dropna=False)
    for label, n in counts.items():
        print(f"  {label if pd.notna(label) else '(unrecorded)':38s} {n:>8,}  ({n / len(df):.1%})")

    print("\n--- Are ramps included? ---")
    n_ramp = int(df["is_ramp_by_name"].sum())
    print(f"  Structures with 'RAMP' in their facility-carried name: {n_ramp:,} ({n_ramp / len(df):.1%})")
    print("  (text-match, not a classification code -- see download_nbi_bridges.py's")
    print("   comment on why SERVICE_LEVEL_005C isn't used for this: an initial label")
    print("   mapping from memory of the NBI Coding Guide didn't match real data, so")
    print("   this uses direct text evidence instead, which needs no code lookup to trust.)")
    print(f"  Raw SERVICE_LEVEL_005C codes present in the data: "
          f"{sorted(df['service_level_raw_code'].dropna().unique())}")

    print("\n--- On the National Highway System? (HIGHWAY_SYSTEM_104) ---")
    counts = df["on_nhs"].value_counts(dropna=False)
    for code, n in counts.items():
        print(f"  code={code!r:8s} {n:>8,}  ({n / len(df):.1%})")

    print("\n--- Owner (OWNER_022, raw codes -- not labeled, same reason as service_level) ---")
    print(df["owner"].value_counts(dropna=False).head(15).to_string())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
