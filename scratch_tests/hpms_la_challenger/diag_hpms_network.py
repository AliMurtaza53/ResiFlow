"""Compare AFTER isolated vs BEFORE soge FAF5 network for LCP-killer issues."""
from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

ISO = Path(
    "/scratch/akothaw/multimodal_hazard_data/scratch_tests/hpms_la_challenger/isolated_base/networks/faf5"
)
SOGE = Path("/scratch/akothaw/multimodal_hazard_data/soge_clusters/networks/faf5")


def check(label: str, root: Path) -> None:
    links = gpd.read_parquet(root / "faf5_road_links.gpq")
    nodes = gpd.read_parquet(root / "faf5_road_nodes.gpq")
    print(f"=== {label} links={len(links)} nodes={len(nodes)} ===")
    for c in [
        "length",
        "Speed_Limit",
        "lanes",
        "from_id",
        "to_id",
        "e_id",
        "assignment_tier",
        "average_toll_cost",
    ]:
        if c not in links.columns:
            print(f"  MISSING {c}")
            continue
        s = links[c]
        nulls = int(s.isna().sum())
        msg = f"  {c}: dtype={s.dtype} nulls={nulls}"
        if pd.api.types.is_numeric_dtype(s):
            num = pd.to_numeric(s, errors="coerce")
            bad = int((~np.isfinite(num) & num.notna()).sum()) + nulls
            msg += f" min={num.min()} max={num.max()} nonfinite_or_null={bad}"
        else:
            msg += f" nunique={s.nunique()} sample={s.head(3).tolist()}"
        print(msg)

    nset = set(nodes["node_id"].astype(int))
    fr = links["from_id"].astype(int)
    to = links["to_id"].astype(int)
    print(f"  orphan from={(~fr.isin(nset)).sum()} to={(~to.isin(nset)).sum()}")
    print(
        f"  dup e_id={links['e_id'].astype(str).duplicated().sum()} "
        f"dup node={nodes['node_id'].duplicated().sum()}"
    )
    if "network_source" in links.columns:
        print(
            "  network_source:",
            links["network_source"].value_counts(dropna=False).head(12).to_dict(),
        )
    length = pd.to_numeric(links["length"], errors="coerce")
    print(f"  length<=0: {(length <= 0).sum()}  length null: {length.isna().sum()}")
    speed = pd.to_numeric(links["Speed_Limit"], errors="coerce")
    print(f"  Speed_Limit<=0: {(speed <= 0).sum()}  Speed null: {speed.isna().sum()}")

    # e_id type mix
    eid = links["e_id"]
    print(
        f"  e_id types: int={(eid.map(type) == int).sum()} "
        f"str={(eid.map(type) == str).sum()} other={eid.map(lambda x: type(x) not in (int, str)).sum()}"
    )


def main() -> int:
    check("AFTER", ISO)
    check("BEFORE", SOGE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
