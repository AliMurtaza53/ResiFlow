#!/usr/bin/env python3
"""Build a 5M-row OD sample for the overnight convergence run that
guarantees inclusion of every OD pair known to intersect the VA-toy hazard
(event 30_1), per the pre-existing full-OD baseline run's disrupted
candidates, then fills the remaining budget from the full combined OD in
original order.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import geopandas as gpd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

from resiflow.demand import load_assignment_demand, demand_spec_from_env  # noqa: E402
from resiflow.networks import normalize_network_links  # noqa: E402
from resiflow.utils import load_config  # noqa: E402

TARGET_N = 5_000_000
CANDIDATES_PATH = Path(
    "C:/Users/akothaw/Desktop/data/results/base_scenario/conus_snapshot_full/"
    "event_disrupted_candidates/30_1/parts/candidates_part_000001.pq"
)
OUT_PATH = Path(__file__).resolve().parent / "runs" / "goal14_va_priority_5m_od.pq"


def main() -> None:
    base_path = Path(load_config()["paths"]["soge_clusters"])

    print("Loading full combined assignment OD...", file=sys.stderr)
    demand_result = load_assignment_demand(base_path, demand_spec_from_env(base_path))
    od = demand_result.assignment_od.copy()
    print(f"Full combined OD rows: {len(od):,}", file=sys.stderr)

    print("Loading VA-toy hazard disrupted-candidate OD pairs...", file=sys.stderr)
    candidates = pd.read_parquet(CANDIDATES_PATH, columns=["origin_node", "destination_node"])
    candidates = candidates.drop_duplicates().reset_index(drop=True)
    print(f"Must-include (hazard-intersecting) OD pairs: {len(candidates):,}", file=sys.stderr)

    od["origin_node"] = od["origin_node"].astype(str)
    od["destination_node"] = od["destination_node"].astype(str)
    candidates["origin_node"] = candidates["origin_node"].astype(str)
    candidates["destination_node"] = candidates["destination_node"].astype(str)

    key = ["origin_node", "destination_node"]
    is_priority = od.set_index(key).index.isin(candidates.set_index(key).index)
    priority_rows = od[is_priority]
    rest_rows = od[~is_priority]
    print(
        f"Matched {len(priority_rows):,} of {len(candidates):,} candidate pairs "
        f"in the combined OD (some may not appear in this demand source mix).",
        file=sys.stderr,
    )

    fill_n = max(0, TARGET_N - len(priority_rows))
    sample = pd.concat([priority_rows, rest_rows.head(fill_n)], ignore_index=True)
    print(f"Final prioritized sample rows: {len(sample):,}", file=sys.stderr)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    sample.to_parquet(OUT_PATH, index=False)
    print(f"Saved: {OUT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
