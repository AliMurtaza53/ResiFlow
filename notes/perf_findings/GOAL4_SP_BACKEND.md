# Goal 4 — Shortest-path backend spike

**Date:** 2026-07-10  
**Script:** `experiments/perf_numcpu/spike_sp_backends.py`

## Sioux Falls (24 origins, 76 edges)

| Backend | Serial LCP time (s) |
|---------|---------------------|
| igraph (`get_shortest_paths`, epath) | **0.0003** |
| scipy `csgraph.dijkstra` | 0.0013 |

**Speedup (scipy vs igraph):** 0.23× — scipy is **slower** on this toy graph.

## Finding

Replacing igraph with scipy sparse Dijkstra is **not** a quick win at Sioux Falls scale. igraph batching per origin is already near-zero cost on 76 edges; scipy overhead dominates.

At CONUS scale, igraph remains the production backend; any backend change would need profiling on full graph size (millions of edges) with batched multi-origin APIs — out of scope for this 48 h pass.

**Recommendation for Monday:** Option **(a)** — keep igraph; do not invest in scipy swap without CONUS-sized benchmark.
