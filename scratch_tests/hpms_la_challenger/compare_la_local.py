"""LA-local BEFORE vs AFTER: demand on the 12 remapped catchment nodes.

BEFORE: OD still on old FAF node ids.
AFTER: same demand remapped to centroid ids 600000+.

Uses trip_isolations + (if present) edge_flows; fails closed if artifacts missing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path("/scratch/akothaw/multimodal_hazard_data/scratch_tests/hpms_la_challenger")
MAN = json.loads((ROOT / "splice_manifest.json").read_text())
import os

AFTER_RES = Path(
    os.environ.get(
        "HPMS_AFTER_RES",
        str(ROOT / "results/base_scenario/hpms_la_after_2iter_v2"),
    )
)
BEFORE_RES = Path(
    "/scratch/akothaw/multimodal_hazard_data/results/base_scenario/la_connector_before_2iter"
)
V3_OD = Path(
    "/scratch/akothaw/multimodal_hazard_data/scratch_tests/county_connector_remedy/"
    "v3_vehicle_trips/passenger_od_multinode_v3.pq"
)
AFTER_OD = ROOT / "passenger_od_hpms_la.pq"


def _load_isolations(path: Path) -> pd.DataFrame:
    for name in ("trip_isolations.pq", "trip_isolations.parquet"):
        p = path / name
        if p.exists():
            return pd.read_parquet(p)
    raise FileNotFoundError(f"no trip_isolations under {path}")


def _node_demand(od: pd.DataFrame, col: str, nodes: set[str]) -> float:
    s = od[col].astype(str)
    return float(od.loc[s.isin(nodes), "Car21"].sum())


def main() -> int:
    home_old = set(MAN["home_map"].keys())
    home_new = set(MAN["home_map"].values())
    work_old = set(MAN["work_map"].keys())
    work_new = set(MAN["work_map"].values())
    all_old = home_old | work_old
    all_new = home_new | work_new

    od_b = pd.read_parquet(V3_OD)
    od_a = pd.read_parquet(AFTER_OD)
    for df in (od_b, od_a):
        df["origin_node"] = df["origin_node"].astype(str)
        df["destination_node"] = df["destination_node"].astype(str)

    print("=== OD demand on LA remap nodes ===")
    print(
        f"BEFORE home-origin Car21={_node_demand(od_b, 'origin_node', home_old):.3f} "
        f"work-dest={_node_demand(od_b, 'destination_node', work_old):.3f}"
    )
    print(
        f"AFTER  home-origin Car21={_node_demand(od_a, 'origin_node', home_new):.3f} "
        f"work-dest={_node_demand(od_a, 'destination_node', work_new):.3f}"
    )
    # rows touching any remap endpoint
    b_touch = od_b[
        od_b["origin_node"].isin(all_old) | od_b["destination_node"].isin(all_old)
    ]
    a_touch = od_a[
        od_a["origin_node"].isin(all_new) | od_a["destination_node"].isin(all_new)
    ]
    print(f"BEFORE touch rows={len(b_touch)} Car21={b_touch['Car21'].sum():.3f}")
    print(f"AFTER  touch rows={len(a_touch)} Car21={a_touch['Car21'].sum():.3f}")

    iso_a = _load_isolations(AFTER_RES)
    print(f"\nAFTER isolations cols={list(iso_a.columns)} rows={len(iso_a)}")
    # normalize
    for c in ("origin_node", "destination_node", "origin", "destination"):
        if c in iso_a.columns:
            iso_a[c] = iso_a[c].astype(str)
    flow_col = "flow" if "flow" in iso_a.columns else "Car21" if "Car21" in iso_a.columns else None
    if flow_col is None:
        raise KeyError(f"no flow column in isolations: {iso_a.columns.tolist()}")

    ocol = "origin_node" if "origin_node" in iso_a.columns else "origin"
    dcol = "destination_node" if "destination_node" in iso_a.columns else "destination"
    a_iso_touch = iso_a[iso_a[ocol].isin(all_new) | iso_a[dcol].isin(all_new)]
    print(
        f"AFTER isolated touch rows={len(a_iso_touch)} "
        f"{flow_col}={float(a_iso_touch[flow_col].sum()):.3f}"
    )

    if BEFORE_RES.exists():
        try:
            iso_b = _load_isolations(BEFORE_RES)
            for c in ("origin_node", "destination_node", "origin", "destination"):
                if c in iso_b.columns:
                    iso_b[c] = iso_b[c].astype(str)
            b_flow = "flow" if "flow" in iso_b.columns else "Car21"
            bo = "origin_node" if "origin_node" in iso_b.columns else "origin"
            bd = "destination_node" if "destination_node" in iso_b.columns else "destination"
            b_iso_touch = iso_b[iso_b[bo].isin(all_old) | iso_b[bd].isin(all_old)]
            print(
                f"BEFORE isolated touch rows={len(b_iso_touch)} "
                f"{b_flow}={float(b_iso_touch[b_flow].sum()):.3f}"
            )
            dem = float(b_touch["Car21"].sum())
            if dem > 0:
                print(
                    f"BEFORE LA-touch isolated fraction="
                    f"{float(b_iso_touch[b_flow].sum()) / dem:.6f}"
                )
            dem_a = float(a_touch["Car21"].sum())
            if dem_a > 0:
                print(
                    f"AFTER  LA-touch isolated fraction="
                    f"{float(a_iso_touch[flow_col].sum()) / dem_a:.6f}"
                )
        except FileNotFoundError as e:
            print(f"BEFORE isolations missing: {e}")
    else:
        print(f"BEFORE results dir missing: {BEFORE_RES}")

    # Per-centroid AFTER isolation
    print("\n=== Per-centroid AFTER isolation (as origin or dest) ===")
    for label, mp in (("home", MAN["home_map"]), ("work", MAN["work_map"])):
        for old, new in mp.items():
            sub = a_iso_touch[(a_iso_touch[ocol] == new) | (a_iso_touch[dcol] == new)]
            dem = float(
                a_touch[
                    (a_touch["origin_node"] == new) | (a_touch["destination_node"] == new)
                ]["Car21"].sum()
            )
            iso = float(sub[flow_col].sum()) if len(sub) else 0.0
            print(f"  {label} {old}->{new}: demand={dem:.1f} isolated={iso:.1f}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
