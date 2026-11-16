"""Check a saved first pass before treating its link flows as unconstrained."""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audit", type=Path)
    parser.add_argument("flows", type=Path)
    parser.add_argument("intended", type=Path)
    args = parser.parse_args()
    audit = pd.read_parquet(args.audit)
    if len(audit) != 1:
        raise ValueError("Expected exactly one iteration")
    row = audit.iloc[0]
    for field in ("edges_binding", "remain", "isolated_structural_cum", "isolated_congestion_cum"):
        if row[field] != 0:
            raise ValueError(f"First pass is not unconstrained: {field}={row[field]}")
    np.testing.assert_allclose(row.delivered, 1510749.556669208, rtol=1e-9, atol=0)
    np.testing.assert_allclose(row.delivered, row.requested_flow, rtol=1e-9, atol=0)
    links = pd.read_parquet(args.flows, columns=["e_id", "faf5_class", "from_id", "acc_flow", "current_capacity"])
    if not links.e_id.is_unique or not np.isfinite(links.acc_flow).all():
        raise ValueError("Invalid physical link flows")
    if links.acc_flow.lt(0).any() or (links.acc_flow - links.current_capacity).gt(1e-6).any():
        raise ValueError("Physical capacity invariant failed")
    intended = set(pd.read_csv(args.intended).centroid_node)
    used = set(links.loc[links.faf5_class.eq(50) & links.acc_flow.gt(0), "from_id"].astype(int))
    if intended != used:
        raise ValueError(f"Centroid loading mismatch: missing={intended-used}, extra={used-intended}")
    print(json.dumps({"trips": float(row.delivered), "binding_links": 0,
                      "intended_and_used_centroids": len(used)}, indent=2))


if __name__ == "__main__":
    main()
