# NumCpu regression report (for Tom)

**Branch:** `perf/numcpu-regression-diagnosis`  
**Date:** 2026-07-10  
**Status:** Goals 0–6 complete; CONUS Pass B local sweep in progress (full OD)

---

## Executive summary

**NumCpu>1 does not improve end-to-end Pass B time on CONUS** and can regress badly (NumCpu=4 aborted after 96+ minutes on prior clone runs). The effective fix is already in production policy: **NumCpu=1 with Patch 6 flags** (`NIRD_OD_ID_AT_INSERT=1`, worker recycle, streaming_arrays). DuckDB write contention during LCP is **not** the cause — workers never touch DuckDB.

Sioux Falls benchmarks confirm pool overhead dominates when per-origin work is tiny; they are **not** a reliable CONUS proxy for numcpu scaling direction.

**Local CONUS Pass B (VA toy raster, Track A stand-in):** 50k row cap → 16 origins, wall flat 29–33 s; full-OD run underway on `Desktop/data/soge_clusters`. See `GOAL1_CONUS_NUMCPU_SWEEP.md`.

**Monday recommendation:** Option **(a)** — document and enforce NumCpu=1; optional affinity spike only if CONUS hardware re-run is scheduled.

---

## 1. Confirmed causes (Goals 1–2)

| Cause | Confidence | Notes |
|-------|------------|-------|
| Multiprocessing fixed costs (spawn, pickle, IPC, result shipping) | **High** | LCP microbench: 3144 tasks, num_cpu=1 → 36 ms vs num_cpu=4 → 1.8 s on same graph. |
| Serial post-LCP phases (stream p1/p2) | **High** | Clone: ~245+1198 s stream phases at NumCpu=1; not parallelized by LCP pool. |
| DuckDB lock contention in workers | **Ruled out** | Inserts in main process only. |
| LCP_COLLECT RAM mode | **High risk** | MemoryError at ~9.6M paths on clone. |
| P-core / E-core scheduling | **Low (untested)** | Affinity spike ready; needs `psutil` + CONUS run. |

**Clone Pass B (1 iter, ~9.7M paths):**

| NumCpu | Wall (s) | LCP (s) |
|--------|----------|---------|
| 1 | 2537 | 1048 |
| 2 | 2572 | 838 |
| 4 | aborted | — |

Full detail: `GOAL2_ISOLATION.md`, `PRIOR_PASSB_EVIDENCE.md`.

---

## 2. Fix applied and benefit (Goal 3)

**No additional code change proposed on this branch.**

Operational lock (already validated on clone):

```
Script 1 args: num_chunks=…, num_cpu=1
NIRD_OD_ID_AT_INSERT=1
NIRD_POOL_MAX_TASKS_PER_CHILD=50
NIRD_PATH_REALIZATION_STRATEGY=streaming_arrays
NIRD_LCP_COLLECT_POOL_RESULTS=0
```

**Benefit:** Patch 6 + NumCpu=1 reduced clone wall **4859 s → 2537 s** (~48%) vs pre-patch baseline.

Detail: `GOAL3_FIX_AND_BENCHMARK.md`.

---

## 3. Faster shortest-path backend (Goal 4)

Sioux Falls spike: **igraph 0.0003 s** vs **scipy csgraph 0.0013 s** (serial, 24 origins).

**Conclusion:** scipy is not faster at toy scale; igraph should remain unless a CONUS-sized benchmark shows otherwise.

Detail: `GOAL4_SP_BACKEND.md`.

---

## 4. Bush / origin-partitioned restructuring (Goal 5)

Minimal PoC: after single-edge removal, **local re-solve on 6/23 destinations** matches full re-solve; **26% work reduction** on one origin.

**Conclusion:** Algorithm is sound as a research direction; production integration is **months**, not a NumCpu workaround.

Detail: `GOAL5_BUSH_POC.md`.

---

## 5. Decision by Monday

| Option | Description | Rough effort | Recommendation |
|--------|-------------|--------------|----------------|
| **(a)** | Enforce NumCpu=1 + Patch6; document in runbooks | **days** | **Recommended** |
| **(b)** | Invest in faster SP primitive (igraph batching / csgraph) | 1–2 weeks | Defer — no SF evidence |
| **(c)** | Bush-based / TAPAS-class restructuring | months | Long-term R&D only |

---

## Appendix

| Doc | Path |
|-----|------|
| 48 h plan | `notes/PERF_INVESTIGATION_PLAN.md` |
| Resume checkpoint | `notes/perf_findings/CHECKPOINT.md` |
| Script 1 parallel inventory | `notes/perf_findings/GOAL0_SCRIPT1_PARALLEL_INVENTORY.md` |
| Goal 1 table | `experiments/perf_numcpu/GOAL1_SWEEP_SUMMARY.md` |
| Spike scripts | `experiments/perf_numcpu/spike_*.py` |

**Reviewer one-liner:** Checkout `perf/numcpu-regression-diagnosis`, read `CHECKPOINT.md`, run `benchmark_sioux_falls_passa.py` with `.venv` Python.
