# Goal 1 — CONUS Pass B numcpu sweep (VA toy raster)

**Date:** 2026-07-10  
**Data bundle:** `C:/Users/akothaw/Desktop/data/soge_clusters`  
**Track A rasters:** `inputs/test_141node_50m/va_hazard_class50_141node_{base,low,high}.tif`

## Rationale

Sioux Falls (24 origins) is a poor proxy for CONUS NumCpu regression. This sweep runs **Pass B Script 1** on the full FAF5 network with VA toy hazard footprint as **Track A stand-in** for moving-window hazard intersection (production Track A will use state-sized rasters on the same network).

## Results — full OD (3143 origins, 9.68M paths)

| num_cpu | wall (s) | LCP (s) | stream p1 | stream p2 | path rows | origins |
|---------|----------|---------|-----------|-----------|-----------|---------|
| 1 | **2442** | 1043 | 214 | 1138 | 9684057 | 3143 |
| 2 | **3779** | 1117 | 528 | 2045 | 9684057 | 3143 |

**Finding:** NumCpu=2 is **55% slower** on wall time locally (3779 s vs 2442 s). Clone showed flat scaling (2572 vs 2537 s); this machine regresses harder — streaming pass 2 nearly doubles (1138 → 2045 s) while LCP barely improves (1043 → 1117 s). **Confirms NumCpu=1 production lock.**

Local num_cpu=1 closely matches clone baseline (2442 vs 2537 s wall; 1043 vs 1048 s LCP).

## Results — 50k OD row cap (smoke, not representative)

**Caveat:** `RESIFLOW_SAMPLE_OD_N=50000` caps **rows**, not origins → only **16 origins**.

| num_cpu | wall (s) | LCP (s) | origins |
|---------|----------|---------|---------|
| 1 | 32.5 | 2.74 | 16 |
| 2 | 28.8 | 4.73 | 16 |
| 4 | 31.0 | 6.49 | 16 |

## Comparison to clone (full OD, Pass B)

| num_cpu | wall (s) | LCP (s) | source |
|---------|----------|---------|--------|
| 1 | 2537 | 1048 | clone |
| 2 | 2572 | 838 | clone |
| 1 | 2442 | 1043 | **local** |
| 2 | 3779 | 1117 | **local** |
| 4 | aborted | — | clone |

## Harness

```powershell
C:\Users\akothaw\AppData\Local\miniforge3\envs\nird\python.exe `
  experiments/perf_numcpu/benchmark_conus_passb_numcpu.py --num-cpus 1,2 --sample-od-n 0 --label goal1_conus_passb_fullod
python experiments/perf_numcpu/summarize_conus_sweep.py
```

Table: `experiments/perf_numcpu/GOAL1_CONUS_SWEEP_SUMMARY.md`
