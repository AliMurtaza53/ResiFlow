# Pass B Parallel Optimization Log

Systematic timing study for Patch 5 Pass B (`event_candidates` mode, `MaxFlowIterations=1` unless noted).

**Machine:** 28 logical CPUs, Windows, `nird` conda env  
**Benchmark script:** `scripts/benchmark_passb_timing.ps1`  
**Parser:** `scripts/parse_passb_timing.py`  
**Outputs:** `experiments/passb_timing/<run_label>/`

## Production recommendation (locked 2026-06-21)

| Setting | Value |
|---------|-------|
| `NIRD_OD_ID_AT_INSERT` | `1` (Patch 6) |
| `NIRD_POOL_MAX_TASKS_PER_CHILD` | `50` |
| `OMP_NUM_THREADS` / `MKL_NUM_THREADS` / `OPENBLAS_NUM_THREADS` | `1` |
| `NumCpu` | **`1`** |
| `NIRD_LCP_COLLECT_POOL_RESULTS` | **off** (profiling only; OOM at CONUS scale) |
| `MaxFlowIterations` (production) | `2` |

**Next algorithm work:** TAPAS / bush-based TAP on a new branch (Boyles Ch 6.4).

Launcher: `scripts/run_patch5_recovery_conus.ps1` (defaults updated).

## Feature flags

| Flag | Purpose |
|------|---------|
| `NIRD_OD_ID_AT_INSERT=1` | Patch 6: assign `od_id` during batch insert (skip `ROW_NUMBER()` rewrite) |
| `NIRD_LCP_COLLECT_POOL_RESULTS=1` | Finish LCP pool before DuckDB inserts — **profiling only; OOM at CONUS scale** |
| `NIRD_POOL_MAX_TASKS_PER_CHILD=50` | Recycle worker processes (Windows memory stability) |
| `OMP_NUM_THREADS=1` | Avoid nested BLAS/OpenMP oversubscription with Pool |

## Execution status

| Step | Run label | Status | Wall (s) | Notes |
|------|-----------|--------|----------|-------|
| 0 | `step0_baseline` | complete | 4859 | Legacy; od_id ~1188 s |
| 1 | `step1_patch6_od_id` | complete | 2608 | ~46% faster vs step 0 |
| 2 | `step2_lcp_collect` | **failed** | — | MemoryError |
| 3 | `step3_pool_recycle` | complete | 3153 | Patch6 + pool recycle |
| 4 | `step4_numcpu_1` | complete | 2537 | Production flags |
| 4 | `step4_numcpu_2` | complete | 2572 | LCP faster, wall flat |
| 4 | `step4_numcpu_4` | **aborted** | — | 42% LCP after ~96 min |
| 4 | `step4_numcpu_8` | **skipped** | — | Not run |

## Step 2 failure (LCP collect)

**Outcome:** `MemoryError` — materializing ~9.6M path rows in RAM before DuckDB insert.

**Decision:** Skip in production (`-SkipLcpCollect`).

## Step 4 NumCpu=4 abort

**Started:** 2026-06-21 01:11 Eastern  
**Aborted:** ~01:47+ Eastern at LCP 1330/3143 (42%)  
**Cause:** Severe negative scaling vs NumCpu=1 (LCP ~17 min vs >96 min incomplete).  
**Decision:** Skip NumCpu=8; use **NumCpu=1** for production Pass B.

## Results (1-iteration smoke)

| Step | NumCpu | Patch6 | Pool | Wall (s) | LCP (s) | od_id (s) | Stream p1 | Stream p2 |
|------|--------|--------|------|----------|---------|-----------|-----------|-----------|
| 0 baseline | 1 | off | off | 4859 | 1455 | 1188 | 549 | 1503 |
| 1 patch6 | 1 | on | off | 2608 | 1088 | 0 | 247 | 1225 |
| 3 pool | 1 | on | 50 | 3153 | 1130 | 0 | 251 | 1724 |
| 4 @1 | 1 | on | 50 | 2537 | 1048 | 0 | 245 | 1198 |
| 4 @2 | 2 | on | 50 | 2572 | 838 | 0 | 393 | 1280 |
| 4 @4 | 4 | on | 50 | — | — | — | — | aborted |

## NumCpu sweep conclusion

- **NumCpu=1** best wall time with production flags (~42 min / iter smoke).
- **NumCpu=2** modest LCP gain (~20%) but no wall-time win (streaming overhead).
- **NumCpu≥4** not viable on this Windows + igraph + Python Pool stack at CONUS scale.

## Production Pass B (2026-06-23)

**Command:** `run_patch5_recovery_conus.ps1 -SkipPassA -SkipScript2 -SkipScript3 -SkipScript4 -MaxFlowIterations 2 -NumCpu 1`

| Metric | Value |
|--------|-------|
| Wall (launcher) | ~77 min |
| Sim time (Script 1) | 4571 s (~76 min) |
| Iter 1 `progress_rel` | 78.34% |
| Iter 2 `progress_rel` | 5.11% |
| Event candidates | 30_1/2/3 — PASS (fresh parts) |
| Log | `logs/20260623_180937_passB_script1_event_candidates.log` |

**Next:** Script 4 + figure refresh; TAPAS on new branch for assignment speed/convergence.
