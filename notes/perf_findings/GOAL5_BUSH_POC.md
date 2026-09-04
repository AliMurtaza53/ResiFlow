# Goal 5 — Bush / local reroute PoC

**Date:** 2026-07-10  
**Script:** `experiments/perf_numcpu/spike_bush_poc.py`

## Setup

- One origin (`sf_1`), 23 destinations on Sioux Falls graph.
- Remove one igraph edge used by baseline paths; compare full vs local re-solve.

## Results

| Metric | Value |
|--------|-------|
| Destinations affected by closure | 6 / 23 (26%) |
| Full re-solve time | 21 µs |
| Local re-solve (affected only) | 11 µs |
| Local paths match full | **Yes** |
| PoC pass | **Yes** |

## Finding

Origin-partitioned **local reroute after single-link damage** is logically sound on toy network: only destinations whose baseline path touched the removed edge need recomputation.

At CONUS scale, potential savings depend on damage footprint vs OD tree size — this PoC validates the **algorithm pattern only**, not wall-clock benefit (times are sub-millisecond on Sioux Falls).

**Recommendation for Monday:** Option **(c)** remains a **months** effort (integration with Pass B iteration loop, incremental trees, validation). Not a near-term substitute for NumCpu=1 policy.
