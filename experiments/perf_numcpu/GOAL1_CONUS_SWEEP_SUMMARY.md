# Goal 1 - CONUS Pass B numcpu sweep (VA toy raster)

Track A stand-in: `inputs/test_141node_50m/va_hazard_*_{base,low,high}.tif` on full FAF5 network.

## Full OD (3143 origins)

| num_cpu | wall (s) | LCP (s) | stream p1 | stream p2 | path rows | origins | run |
|---------|----------|---------|-----------|-----------|-----------|---------|-----|
| 1 | 2442.247 | 1042.8252730369568 | 213.98 | 1138.39 | 9684057 | 3143 | `goal1_conus_passb_fullod_cpu1_20260710_182820` |
| 2 | 3778.965 | 1116.8025178909302 | 528.45 | 2044.54 | 9684057 | 3143 | `goal1_conus_passb_fullod_cpu2_20260710_190925` |

## 50k OD row cap (16 origins — not representative)

| num_cpu | wall (s) | LCP (s) | stream p1 | stream p2 | path rows | origins | run |
|---------|----------|---------|-----------|-----------|-----------|---------|-----|
| 1 | 32.505 | 2.740791082382202 | 2.53 | 7.31 | 46624 | 16 | `goal1_conus_passb_cpu1_20260710_182605` |
| 2 | 28.786 | 4.725719451904297 | 2.46 | 7.09 | 46624 | 16 | `goal1_conus_passb_cpu2_20260710_182645` |
| 4 | 30.974 | 6.488435506820679 | 2.51 | 7.27 | 46624 | 16 | `goal1_conus_passb_cpu4_20260710_182727` |

Generate: `python experiments/perf_numcpu/summarize_conus_sweep.py`
