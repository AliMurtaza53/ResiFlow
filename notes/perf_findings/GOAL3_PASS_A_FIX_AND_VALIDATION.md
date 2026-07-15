# Goal 3 — Fractional remain assignment fix and validation

**Date:** 2026-07-12  
**Branch:** `perf/pass-a-convergence-diagnosis`  
**Code change:** `src/resiflow/road_revised.py`

## Action

Implemented optional **MSA-style fractional remain loading** behind an env flag, added per-iteration convergence logging, and validated on Sioux Falls + CONUS smoke sample harnesses.

## Fix (opt-in)

| Env | Value | Effect |
|-----|-------|--------|
| `RESIFLOW_REMAIN_ASSIGN_FRACTION` | `msa` | Route `α × remain_flow` with `α = 1/iter` before LCP |
| `NIRD_REMAIN_ASSIGN_FRACTION` | `msa` | Alias for clone compatibility |
| (default / empty) | — | Baseline: route 100% of `remain_od` |

Additional logs each iteration:

- `Pass A convergence: remain_fraction=… assigned_fraction=…`
- `remain_assign_mode` in iteration control banner

**Not shipped as default** — behavior change for production Pass A requires CONUS validation against clone baseline paths and reroute metrics.

## Validation runs

| Run | Config | Result |
|-----|--------|--------|
| Sioux Falls baseline | 1+ iter, default | **1 iter**, 100% assigned, normal stop |
| Sioux Falls fractional | `msa` | **1 iter**, 100% assigned |
| CONUS smoke 50k OD | 10 iter cap, default | **1 iter**, 100% assigned (203k initial supply, 16 origins) |

Sioux Falls and 50k smoke **cannot reproduce** the clone stall — networks are too small / too few iterations to stress cap-constrained tail behavior.

## Expected effect at CONUS full-OD scale

Hypothesis: fractional remain loading reduces per-iteration capacity shock, improving late-iteration `progress_rel` and reaching the 99% stop in fewer iterations **or** with less `remain_od` tail.

**Not yet validated:** full-OD CONUS baseline vs `msa` comparison (multi-hour run). Recommend overnight A/B on clone hardware with `RESIFLOW_MAX_FLOW_ITERATIONS=0` and parsed log comparison.

## Operational note (unchanged from numcpu branch)

Pass B / wall-clock policy remains **NumCpu=1** + Patch 6 (`NIRD_OD_ID_AT_INSERT=1`). This Goal 3 change addresses **convergence rate**, not multiprocessing regression.

## Harness

```powershell
python experiments/pass_a_convergence/run_sioux_convergence.py --mode baseline
python experiments/pass_a_convergence/run_sioux_convergence.py --mode fractional
python experiments/pass_a_convergence/run_conus_convergence_sample.py
```

Artifacts: `experiments/pass_a_convergence/runs/sioux_*`, `conus_baseline_10iter/`.
