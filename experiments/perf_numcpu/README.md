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

## Goal 2 — isolation tests (next)

- DuckDB shard writes (workers → separate files, merge after pool)
- P-core affinity pinning (`psutil.Process().cpu_affinity`)
- LCP vs pickle overhead micro-benchmark (WIP — needs normalized Sioux Falls links like Script 1)
