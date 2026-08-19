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
    n_ramp = int(df["is_ramp"].sum())
    n_ramp_by_name = int(df["is_ramp_by_name"].sum())
    print(f"  service_level == 'Ramp, Wye, Connector, etc.' (SERVICE_LEVEL_005C=7, "
          f"authoritative per the NBI Coding Guide, p.14): {n_ramp:,} ({n_ramp / len(df):.1%})")
    print(f"  Cross-check, 'RAMP' in facility-carried name (text-match, independent "
          f"of the code above): {n_ramp_by_name:,} ({n_ramp_by_name / len(df):.1%})")
    agree = int((df["is_ramp"] & df["is_ramp_by_name"]).sum())
    print(f"  Both agree: {agree:,} of {n_ramp_by_name:,} name-matched structures "
          f"({agree / n_ramp_by_name:.1%}) -- the gap is expected (many ramps aren't "
          f"literally named 'ramp', e.g. 'I-95 CONNECTOR', but do carry code 7).")

    print("\n--- On the National Highway System? (HIGHWAY_SYSTEM_104) ---")
    counts = df["on_nhs"].value_counts(dropna=False)
    for code, n in counts.items():
        print(f"  code={code!r:8s} {n:>8,}  ({n / len(df):.1%})")

    print("\n--- Designated level of service (SERVICE_LEVEL_005C) ---")
    counts = df["service_level"].value_counts(dropna=False)
    for label, n in counts.items():
        print(f"  {label if pd.notna(label) else '(unrecorded)':40s} {n:>8,}  ({n / len(df):.1%})")

    print("\n--- Owner (OWNER_022, raw codes -- see NBI Coding Guide Item 22 for labels) ---")
    print(df["owner"].value_counts(dropna=False).head(15).to_string())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
