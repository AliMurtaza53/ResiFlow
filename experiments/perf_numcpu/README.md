# Perf numcpu experiments

Scratch benchmarks for the 48h numcpu regression investigation. **Not production code.**

## Setup

```powershell
pip install psutil   # optional; enables CPU/IO sampling in Goal 1
```

## Goal 1 — Sioux Falls Pass A sweep

```powershell
python experiments/perf_numcpu/benchmark_sioux_falls_passa.py --num-cpus 1,2,4,8,16
python experiments/perf_numcpu/summarize_sweep.py
```

Outputs: `experiments/perf_numcpu/runs/<label>_cpu<N>_<timestamp>/`

## Goal 2 — pool / IPC isolation (LCP-only, no DuckDB)

```powershell
python experiments/perf_numcpu/spike_pool_isolation.py --origin-replicas 1 --num-cpus 1,2,4
python experiments/perf_numcpu/spike_pool_isolation.py --origin-replicas 131 --num-cpus 1,2,4 --label goal2_conus_tasks
```

Optional P-core pinning: set `PERF_WORKER_CPU_AFFINITY=0,2,4,6` (requires `psutil`).

Findings: `notes/perf_findings/GOAL2_ISOLATION.md`

## Goal 4 — SP backend spike

```powershell
python experiments/perf_numcpu/spike_sp_backends.py
```

## Goal 5 — bush / local reroute PoC

```powershell
python experiments/perf_numcpu/spike_bush_poc.py
```

## Resume / report

- Checkpoint: `notes/perf_findings/CHECKPOINT.md`
- Tom report: `notes/perf_findings/REPORT_FOR_TOM.md`
