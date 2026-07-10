#!/usr/bin/env python3
"""Goal 4: compare igraph vs scipy csgraph shortest-path batch on Sioux Falls."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

PERF_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PERF_DIR))
sys.path.insert(0, str(PERF_DIR.parents[1] / "src"))

from sioux_context import build_sioux_lcp_context
from resiflow import road_revised as rr


def _build_csgraph(network) -> tuple[csr_matrix, list[str], dict[str, int]]:
    vertices = [network.vs[i]["name"] for i in range(network.vcount())]
    index = {name: i for i, name in enumerate(vertices)}
    rows, cols, weights = [], [], []
    for edge in network.es:
        src = network.vs[edge.source]["name"]
        tgt = network.vs[edge.target]["name"]
        w = float(edge["weight"])
        rows.append(index[src])
        cols.append(index[tgt])
        weights.append(w)
        rows.append(index[tgt])
        cols.append(index[src])
        weights.append(w)
    graph = csr_matrix((weights, (rows, cols)), shape=(len(vertices), len(vertices)))
    return graph, vertices, index


def main() -> int:
    network, args, stats = build_sioux_lcp_context(origin_replicas=1)
    graph, vertices, index = _build_csgraph(network)

    # igraph serial
    rr.shared_network = network  # type: ignore[attr-defined]
    t0 = time.perf_counter()
    for arg in args:
        rr.find_least_cost_path(arg)
    igraph_sec = time.perf_counter() - t0

    # scipy one-origin-all-dests
    t1 = time.perf_counter()
    for origin, destinations, _flows in args:
        o_idx = index[str(origin)]
        dist, predecessors = dijkstra(
            csgraph=graph, directed=False, indices=o_idx, return_predecessors=True
        )
        _ = dist[[index[str(d)] for d in destinations]]
    scipy_sec = time.perf_counter() - t1

    out = {
        "stats": stats,
        "igraph_serial_lcp_sec": round(igraph_sec, 4),
        "scipy_dijkstra_serial_sec": round(scipy_sec, 4),
        "speedup_scipy_vs_igraph": round(igraph_sec / scipy_sec, 3) if scipy_sec > 0 else None,
        "caveat": "Sioux Falls only; scipy uses dense predecessor lookup per batch.",
    }
    out_path = PERF_DIR / "runs" / f"goal4_sp_backends_{int(time.time())}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
