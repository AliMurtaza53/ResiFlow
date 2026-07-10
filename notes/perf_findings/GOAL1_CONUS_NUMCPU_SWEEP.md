# Goal 1 — CONUS Pass B numcpu sweep (VA toy raster)

**Date:** 2026-07-10  
**Data bundle:** `C:/Users/akothaw/Desktop/data/soge_clusters`  
**Track A rasters:** `inputs/test_141node_50m/va_hazard_class50_141node_{base,low,high}.tif`

## Rationale

Sioux Falls (24 origins) is a poor proxy for CONUS NumCpu regression. This sweep runs **Pass B Script 1** on the full FAF5 network with VA toy hazard footprint as **Track A stand-in** for moving-window hazard intersection (production Track A will use state-sized rasters on the same network).

## Harness

```powershell
C:\Users\akothaw\AppData\Local\miniforge3\envs\nird\python.exe `
  experiments/perf_numcpu/benchmark_conus_passb_numcpu.py --num-cpus 1,2,4
python experiments/perf_numcpu/summarize_conus_sweep.py
```

## Results — 50k OD row cap (smoke)

**Caveat:** `RESIFLOW_SAMPLE_OD_N=50000` caps **rows**, not origins. This run yielded only **16 origins** — insufficient to reproduce CONUS pool saturation. Useful for end-to-end Pass B sanity only.

| num_cpu | wall (s) | LCP (s) | stream p1+p2 (s) | path rows | origins |
|---------|----------|---------|------------------|-----------|---------|
| 1 | 32.5 | 2.74 | 9.84 | 46624 | 16 |
| 2 | 28.8 | 4.73 | 9.55 | 46624 | 16 |
| 4 | 31.0 | (see run meta) | | 46624 | 16 |

**Finding:** At 16 origins, wall time is flat (~29–33 s). NumCpu=2 is marginally fastest on wall despite **higher** logged LCP time — same pattern as clone (LCP savings do not propagate when streaming phases dominate).

## Results — full OD (in progress)

```powershell
# Representative origin count (~3143); expect ~40+ min per run
benchmark_conus_passb_numcpu.py --num-cpus 1,2 --sample-od-n 0 --label goal1_conus_passb_fullod
```

See `GOAL1_CONUS_SWEEP_SUMMARY.md` after completion.

## Comparison to clone (full OD, Pass B)

| num_cpu | wall (s) | source |
|---------|----------|--------|
| 1 | 2537 | clone Pass B |
| 2 | 2572 | clone Pass B |
| 4 | aborted | clone Pass B |

Full-OD local sweep will validate whether flat scaling reproduces on this machine.
