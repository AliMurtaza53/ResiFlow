# Context checkpoint — NumCpu perf investigation

**Updated:** 2026-07-10  
**Branch:** `perf/numcpu-regression-diagnosis`  
**Repo:** https://github.com/AliMurtaza53/ResiFlow  
**Related branch (multihazard, separate):** `feature/sioux-falls-multihazard`

Use this file to resume work without prior chat context.

---

## Goals status

| Goal | Status | Key artifact |
|------|--------|--------------|
| 0 Inventory | ✅ Done | `GOAL0_SCRIPT1_PARALLEL_INVENTORY.md` |
| 1 Reproduce + instrument | ✅ Done (Sioux Falls) | `GOAL1_NUMCPU_SWEEP.md`, `GOAL1_SWEEP_SUMMARY.md` |
| 2 Isolate causes | ✅ Done | `GOAL2_ISOLATION.md`, `spike_pool_isolation.py` |
| 3 Fix + benchmark | ✅ Done (policy) | `GOAL3_FIX_AND_BENCHMARK.md` |
| 4 SP backend spike | ✅ Done | `GOAL4_SP_BACKEND.md`, `spike_sp_backends.py` |
| 5 Bush PoC | ✅ Done | `GOAL5_BUSH_POC.md`, `spike_bush_poc.py` |
| 6 Report for Tom | ✅ Draft complete | `REPORT_FOR_TOM.md` |

---

## Key numbers

### Sioux Falls Pass A (1 iter, full Script 1)

| num_cpu | wall (s) |
|---------|----------|
| 1 | 5.60 |
| 2 | 2.58 |
| 4 | 2.51 |
| 8+ | ~2.9 (plateau) |

### Clone CONUS Pass B (prior evidence, 1 iter, ~9.7M paths)

| num_cpu | wall (s) | notes |
|---------|----------|-------|
| 1 | 2537 | production lock |
| 2 | 2572 | flat |
| 4 | aborted | 96+ min, negative scaling |

### Goal 2 LCP microbench (3144 tasks, no DuckDB)

| num_cpu | LCP (s) |
|---------|---------|
| 1 | 0.036 |
| 4 | 1.83 |

---

## Decisions (no user input needed yet)

1. **Ship NumCpu=1 + Patch6 flags** — not a code change on this branch.
2. **Do not enable `NIRD_LCP_COLLECT_POOL_RESULTS=1`** at CONUS scale.
3. **Do not pursue scipy csgraph** based on Sioux Falls spike.
4. **Bush/local reroute** — valid PoC, months to productionize.

---

## File index (perf work)

```
notes/PERF_INVESTIGATION_PLAN.md
notes/perf_findings/
  CHECKPOINT.md          ← this file
  GOAL0_SCRIPT1_PARALLEL_INVENTORY.md
  GOAL1_NUMCPU_SWEEP.md
  GOAL2_ISOLATION.md
  GOAL3_FIX_AND_BENCHMARK.md
  GOAL4_SP_BACKEND.md
  GOAL5_BUSH_POC.md
  REPORT_FOR_TOM.md
experiments/perf_numcpu/
  benchmark_sioux_falls_passa.py
  spike_pool_isolation.py
  spike_sp_backends.py
  spike_bush_poc.py
  sioux_context.py
  parse_assignment_timing.py
  summarize_sweep.py
  PRIOR_PASSB_EVIDENCE.md
  GOAL1_SWEEP_SUMMARY.md
  runs/                  ← gitignored raw outputs
```

---

## Open blockers

| Blocker | Impact | Unblock |
|---------|--------|---------|
| No local CONUS `config.json` + SOGE bundle | Cannot re-run Pass B on this machine | User provides data path |
| `psutil` missing in `.venv` | CPU affinity + sampler skipped | `pip install psutil` in venv |
| Sioux Falls ≠ CONUS | Microbench can mislead on pool benefit sign | Cite clone logs for CONUS |

---

## Resume commands (PowerShell)

```powershell
cd C:\Users\akothaw\Desktop\ResiFlow
git checkout perf/numcpu-regression-diagnosis
.\.venv\Scripts\python.exe experiments/perf_numcpu/benchmark_sioux_falls_passa.py --num-cpus 1,2,4
.\.venv\Scripts\python.exe experiments/perf_numcpu/spike_pool_isolation.py --origin-replicas 131 --num-cpus 1,2,4
```

---

## Multihazard work (other branch)

Panel viz, unique scenario keys, `results/multihazard_panel/` — all on `feature/sioux-falls-multihazard`, **not merged to main**.
