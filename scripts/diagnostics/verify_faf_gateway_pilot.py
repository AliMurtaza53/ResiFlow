"""Verify the gateway pilot and show physical access-link utilization."""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("audit", "pilot", "control", "budgets", "output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    audit = pd.read_parquet(args.audit)
    if len(audit) != 1:
        raise ValueError("Gateway arm did not finish in one pass")
    row = audit.iloc[0]
    for field in ("edges_binding", "remain", "isolated_structural_cum", "isolated_congestion_cum"):
        if row[field] != 0:
            raise ValueError(f"Pilot missed the assignment gate: {field}={row[field]}")
    np.testing.assert_allclose(row.delivered, 754974.3022249371, rtol=1e-9, atol=0)
    cols = ["e_id", "faf5_class", "from_id", "to_id", "acc_flow", "current_capacity"]
    pilot = pd.read_parquet(args.pilot, columns=cols)
    control = pd.read_parquet(args.control, columns=cols)
    for frame in (pilot, control):
        if not frame.e_id.is_unique or not np.isfinite(frame.acc_flow).all():
            raise ValueError("Invalid physical flow table")
        frame[["from_id", "to_id"]] = frame[["from_id", "to_id"]].astype(str)
    ports = pd.read_csv(args.budgets)
    connectors = pilot[pilot.faf5_class.eq(50) & pilot.from_id.isin(ports.centroid_node.astype(str))]
    by_centroid = connectors.groupby("from_id").acc_flow.sum()
    expected = ports.groupby(ports.centroid_node.astype(str)).allocated_trips.sum()
    np.testing.assert_allclose(by_centroid.reindex(expected.index), expected, rtol=1e-9, atol=0)
    physical = pilot[pilot.faf5_class.ne(50)].merge(
        control[["e_id", "current_capacity", "acc_flow"]], on="e_id", validate="one_to_one",
        suffixes=("_pilot", "_control"))
    if len(physical) != pilot.faf5_class.ne(50).sum() or len(physical) != control.faf5_class.ne(50).sum():
        raise ValueError("Physical road support changed")
    np.testing.assert_allclose(physical.current_capacity_pilot, physical.current_capacity_control)
    if (physical.acc_flow_pilot - physical.current_capacity_pilot).gt(1e-6).any():
        raise ValueError("Physical road capacity exceeded")
    roads = []
    for node, group in connectors.groupby("from_id"):
        endpoints = set(group.to_id)
        local = physical[physical.from_id.isin(endpoints) | physical.to_id.isin(endpoints)].copy()
        local["gateway_node"] = node
        for arm in ("pilot", "control"):
            local[f"vc_{arm}"] = local[f"acc_flow_{arm}"] / local[f"current_capacity_{arm}"]
        roads.append(local)
    ranked = pd.concat(roads).sort_values("vc_pilot", ascending=False)
    ranked.to_csv(args.output, index=False)
    print(json.dumps({"delivered": float(row.delivered), "gateway_connector_trips": by_centroid.to_dict(),
                      "access_road_max_vc_pilot": float(ranked.vc_pilot.max()),
                      "access_road_max_vc_control": float(ranked.vc_control.max())}, indent=2))


if __name__ == "__main__":
    main()
