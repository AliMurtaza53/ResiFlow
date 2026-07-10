# Goal 1 — Sioux Falls Pass A numcpu sweep (initial)

**Date:** 2026-07-10  
**Config:** 1 assignment iteration, `NIRD_OD_ID_AT_INSERT=1`, streaming_arrays, 24 origins, 528 path rows.

## Results

| num_cpu | wall (s) | LCP logged (s) | total sim (s) | stream p1+p2 (s) |
|---------|----------|----------------|---------------|------------------|
| 1 | **5.60** | 0.0* | 0.93 | 0.14 |
| 2 | 2.58 | 1.13 | 1.43 | 0.06 |
| 4 | 2.51 | 1.08 | 1.35 | 0.05 |
| 8 | 2.86 | 1.32 | 1.66 | 0.08 |
| 16 | 2.94 | 1.46 | 1.76 | 0.07 |

\* `num_cpu=1` uses the in-process LCP loop; `lcp_pool_sec` log is **0.0** (timer not applied on that code path). Wall time is the reliable metric for cpu=1.

## Finding

On **Sioux Falls**, `num_cpu>1` reduces **wall-clock** ~2× vs `num_cpu=1` (5.6s → ~2.5s), then **plateaus** — more workers do not help further on 24 origins.

This is the **opposite direction** from CONUS Pass B (clone data: NumCpu=2 flat wall, NumCpu=4 catastrophic). **Sioux Falls is not a valid proxy for CONUS numcpu regression** — it has too few origins to expose pool/pickle/IPC overhead.

**Saturation:** At num_cpu≥2, wall tracks pool spawn + pickle init more than LCP; CPU sampling pending (`pip install psutil` in perf venv).

**Next:** Goal 1 on CONUS smoke (50k OD, 1 iter) if time permits; otherwise cite clone `PRIOR_PASSB_EVIDENCE.md` for CONUS.

Full table: `experiments/perf_numcpu/GOAL1_SWEEP_SUMMARY.md`
