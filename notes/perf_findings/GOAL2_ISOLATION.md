# Goal 2 — Isolate causes (Sioux Falls + clone cross-check)

**Date:** 2026-07-10  
**Artifacts:** `experiments/perf_numcpu/spike_pool_isolation.py`, runs under `experiments/perf_numcpu/runs/goal2_*`

## Hypotheses tested

| Hypothesis | Result | Evidence |
|------------|--------|----------|
| DuckDB write contention in LCP workers | **Ruled out** | Workers return path tuples only; DuckDB inserts run in main process (Goal 0 inventory). Spike confirms no worker-side DB. |
| Pickle / graph reload dominates | **Ruled out at SF scale** | `avg_pickle_load_sec_per_worker ≈ 2.7e-05` (27 µs) on 76-edge graph. Clone CONUS graph is larger but one pickle per worker, not per origin. |
| Pool IPC / spawn overhead dominates small tasks | **Confirmed** | 24 tasks: `num_cpu=1` LCP 0.3 ms vs `num_cpu=2` **867 ms** (pool cold start). |
| Pool helps at CONUS task count on tiny graph | **No** | 3144 tasks (131×24 replicas): `num_cpu=1` **36 ms** vs `num_cpu=2` **1061 ms**, `num_cpu=4` **1826 ms**. |
| `LCP_COLLECT` (all results in RAM) | **CONUS OOM** (clone) | `NIRD_LCP_COLLECT_POOL_RESULTS=1` → MemoryError ~9.6M paths. SF spike: collect mode slightly slower even in RAM. |
| P-core affinity | **Not run** | `psutil` not installed in `.venv`; affinity hook exists in spike (`PERF_WORKER_CPU_AFFINITY`). |

## Microbenchmark (LCP-only, no DuckDB)

### 24 origins (Sioux Falls native)

| num_cpu | stream | LCP wall (s) |
|---------|--------|--------------|
| 1 | yes | 0.0003 |
| 2 | yes | 0.87 |
| 4 | yes | 0.81 |

### 3144 tasks (131× origin replica — CONUS-like task count)

| num_cpu | stream | LCP wall (s) |
|---------|--------|--------------|
| 1 | yes | 0.036 |
| 2 | yes | 1.06 |
| 4 | yes | 1.83 |

## Interpretation

1. **Regression at NumCpu>1 on CONUS is not DuckDB lock contention during LCP.** Clone Pass B shows LCP ~1048 s at NumCpu=1 vs ~838 s at NumCpu=2 but **flat total wall** (~2537 s → ~2572 s) — savings in LCP are lost to pool overhead, result shipping, and serial post-LCP phases (stream p1/p2 ~1500 s combined).

2. **Sioux Falls Pass A sweep (Goal 1) and LCP microbench measure different things.** Full Script 1 at num_cpu=2 beats num_cpu=1 on wall (5.6 s → 2.5 s) because non-LCP phases also run; pure LCP microbench shows pool is toxic when each origin-task is microseconds.

3. **Root cause class:** multiprocessing fixed costs (spawn, pickle, IPC, result aggregation) + **E-core / scheduler noise** (affinity not yet measured) on a workload where post-LCP streaming and od_id phases remain largely serial.

## Recommended follow-ups (if CONUS re-run available)

- Install `psutil` in perf venv; re-run spike with `PERF_WORKER_CPU_AFFINITY` set to P-core IDs.
- CONUS smoke Pass B, 1 iter, NumCpu=1 vs 2 with phase parser on real logs.
