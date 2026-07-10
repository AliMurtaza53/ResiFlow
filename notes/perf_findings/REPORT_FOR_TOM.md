# NumCpu regression report (draft for Tom)

**Branch:** `perf/numcpu-regression-diagnosis`  
**Status:** in progress — Goal 0–1 started

## 1. Confirmed causes (Goals 1–2)

_TBD — populate after Sioux Falls sweep and isolation tests._

Prior clone evidence (Pass B, CONUS): see `experiments/perf_numcpu/PRIOR_PASSB_EVIDENCE.md`.

## 2. Fix applied and benefit (Goal 3)

_TBD_

## 3. Faster shortest-path backend (Goal 4)

_TBD_

## 4. Bush / origin-partitioned restructuring (Goal 5)

_TBD — stretch goal._

## 5. Decision by Monday

| Option | Description | Rough effort |
|--------|-------------|--------------|
| **(a)** | Ship confirmed I/O/affinity fix; keep NumCpu=1 | days |
| **(b)** | Invest in faster SP primitive (igraph batching / csgraph spike) | 1–2 weeks |
| **(c)** | Commit to bush-based / TAPAS-class restructuring | months |

## Appendix

- Inventory: `notes/perf_findings/GOAL0_SCRIPT1_PARALLEL_INVENTORY.md`
- Goal 1 table: `experiments/perf_numcpu/GOAL1_SWEEP_SUMMARY.md`
