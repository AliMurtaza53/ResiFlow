#!/usr/bin/env python3
"""Goal 5: minimal bush/local-reroute PoC on Sioux Falls (standalone, not integrated)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

PERF_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PERF_DIR))
sys.path.insert(0, str(PERF_DIR.parents[1] / "src"))

from sioux_context import build_sioux_lcp_context
from resiflow import road_revised as rr


def _paths_for_origin(network, origin: str, destinations: list[str]) -> dict[str, list[int]]:
    rr.shared_network = network  # type: ignore[attr-defined]
    _origin, _dests, paths, _flows = rr.find_least_cost_path((origin, destinations, [1.0] * len(destinations)))
    return {d: p for d, p in zip(destinations, paths)}


def _edges_on_paths(path_map: dict[str, list[int]]) -> set[int]:
    edges: set[int] = set()
    for path in path_map.values():
        edges.update(path)
    return edges


def main() -> int:
    network, args, stats = build_sioux_lcp_context(origin_replicas=1)
    if not args:
        raise SystemExit("no LCP args")

    origin, destinations, flows = args[0]
    baseline_paths = _paths_for_origin(network, origin, destinations)
    baseline_edges = _edges_on_paths(baseline_paths)

    # Pick first edge used by any baseline path and simulate closure by removing it
    if not baseline_edges:
        raise SystemExit("no edges on baseline paths")
    damaged_edge_idx = sorted(baseline_edges)[0]

    network_local = network.copy()
    network_local.delete_edges(damaged_edge_idx)

    # Full re-solve for this origin only
    t_full0 = time.perf_counter()
    full_paths = _paths_for_origin(network_local, origin, destinations)
    full_sec = time.perf_counter() - t_full0

    # "Local" re-solve: only destinations whose baseline path used damaged edge
    affected_dests = [
        d for d, p in baseline_paths.items() if damaged_edge_idx in p
    ]
    t_local0 = time.perf_counter()
    local_paths = _paths_for_origin(network_local, origin, affected_dests) if affected_dests else {}
    local_sec = time.perf_counter() - t_local0

    # Check local+unchanged matches full for affected destinations
    match = all(local_paths.get(d, []) == full_paths.get(d, []) for d in affected_dests)

    out = {
        "stats": stats,
        "origin": origin,
        "destinations_total": len(destinations),
        "destinations_affected": len(affected_dests),
        "damaged_edge_igraph_idx": damaged_edge_idx,
        "baseline_edges_touched": len(baseline_edges),
        "full_reresolve_sec": round(full_sec, 6),
        "local_reresolve_sec": round(local_sec, 6),
        "local_matches_full_on_affected": match,
        "work_reduction_ratio": round(len(affected_dests) / max(len(destinations), 1), 3),
        "pass": match and len(affected_dests) < len(destinations),
    }
    out_path = PERF_DIR / "runs" / f"goal5_bush_poc_{int(time.time())}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
