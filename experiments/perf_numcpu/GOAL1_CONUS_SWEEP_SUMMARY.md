# Goal 1 — CONUS Pass B numcpu sweep (VA toy raster / 50k OD)

Track A stand-in: `inputs/test_141node_50m/va_hazard_*_{base,low,high}.tif` on full FAF5 network.

| num_cpu | wall (s) | LCP (s) | stream p1 | stream p2 | path rows | origins | run |
|---------|----------|---------|-----------|-----------|-----------|---------|-----|
| 1 | 32.505 | 2.740791082382202 | 2.53 | 7.31 | 46624 | 16 | `goal1_conus_passb_cpu1_20260710_182605` |
| 2 | 28.786 | 4.725719451904297 | 2.46 | 7.09 | 46624 | 16 | `goal1_conus_passb_cpu2_20260710_182645` |
| 4 | 30.974 | 6.488435506820679 | 2.51 | 7.27 | 46624 | 16 | `goal1_conus_passb_cpu4_20260710_182727` |

Generate: `python experiments/perf_numcpu/summarize_conus_sweep.py`
