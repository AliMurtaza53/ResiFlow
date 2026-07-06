#!/usr/bin/env python3
"""Compare BPR user equilibrium vs ResiFlow cap-constrained assignment on a TNTP testbed."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from resiflow.assignment.compare import compare_ue_vs_resiflow
from resiflow.testbeds import list_testbeds


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--testbed",
        default="sioux_falls",
        choices=list_testbeds(),
        help="Registered TNTP testbed id",
    )
    parser.add_argument(
        "--target-gap",
        type=float,
        default=1e-3,
        help="UE Frank-Wolfe relative-gap tolerance",
    )
    parser.add_argument(
        "--use-testbed-prefix",
        action="store_true",
        help="Apply testbed node_id_prefix to ResiFlow network/OD (UE stays on raw TNTP ids)",
    )
    args = parser.parse_args()

    report = compare_ue_vs_resiflow(
        args.testbed,
        use_testbed_prefix=args.use_testbed_prefix,
        target_gap=args.target_gap,
    )

    print(f"Testbed: {report['testbed_id']}")
    print(f"Demand scale: {report['demand_scale']}")
    print(f"Total demand: {report['total_demand']:.1f}")
    print(f"UE converged: {report['ue_converged']} ({report['ue_iterations']} iterations)")
    print(f"UE relative gap: {report['ue_relative_gap']:.2e}")
    print(f"Paired links: {report['paired_links']} / {report['link_count']}")
    print(f"Directed flow correlation: {report['flow_correlation']:.4f}")
    print(f"Undirected flow correlation: {report['flow_correlation_undirected']:.4f}")
    print(
        f"Total flow ratio (ResiFlow/UE): {report['total_flow_ratio']:.4f} "
        f"({report['resiflow_total_flow']:.0f} / {report['ue_total_flow']:.0f})"
    )
    print(f"Flow MAE (directed): {report['flow_mae']:.2f}")
    print(f"Flow MAPE (directed): {report['flow_mape']:.4f}")

    paired = report["paired_flows"]
    if len(paired):
        print("\nTop 10 links by UE flow:")
        top = paired.sort_values("ue_flow", ascending=False).head(10)
        for row in top.itertuples(index=False):
            print(
                f"  {row.from_id}->{row.to_id}: "
                f"UE={row.ue_flow:.1f} ResiFlow={row.resiflow_flow:.1f}"
            )

    return 0 if report["ue_converged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
