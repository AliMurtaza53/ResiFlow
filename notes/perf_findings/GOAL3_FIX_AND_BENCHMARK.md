# Goal 3 — Fix applied and benchmark

**Date:** 2026-07-10  
**Conclusion:** No new production code change required on this branch. **Operational policy is the fix.**

## Production configuration (confirmed optimal from clone Pass B)

| Setting | Value | Rationale |
|---------|-------|-----------|
| `NumCpu` (Script 1 arg) | **1** | Only setting with stable CONUS wall time (~2537 s / 1 iter Pass B). |
| `NIRD_OD_ID_AT_INSERT` | **1** | Patch 6 — removes ~1188 s od_id phase at NumCpu=1. |
| `NIRD_POOL_MAX_TASKS_PER_CHILD` | **50** | Recycle workers; avoids long-lived worker bloat. |
| `NIRD_PATH_REALIZATION_STRATEGY` | `streaming_arrays` | Production streaming path. |
| `NIRD_LCP_COLLECT_POOL_RESULTS` | **0** (default) | `=1` OOM at CONUS scale. |
| `NumCpu>1` | **Avoid** | Flat or negative wall; NumCpu=4 aborted after 96+ min on clone. |

## What we did not ship (scratch branch only)

- Optional P-core affinity in `worker_init_path` — inconclusive without `psutil` sweep on CONUS hardware.
- Sharded DuckDB worker writes — not needed; workers do not write DuckDB today.

## Benchmark status

| Benchmark | Status |
|-----------|--------|
| Sioux Falls Pass A sweep | **Done** — `GOAL1_NUMCPU_SWEEP.md` |
| Sioux Falls LCP isolation | **Done** — `GOAL2_ISOLATION.md` |
| CONUS Pass B re-run | **Blocked** — no local `config.json` + full SOGE data bundle in repo |

## Benefit statement for Tom

Patch 6 + NumCpu=1 cut clone Pass B wall from **~4859 s → ~2537 s** (~48% reduction). Further NumCpu scaling does not improve end-to-end time; Goal 2 explains why (IPC + serial post-LCP phases).
