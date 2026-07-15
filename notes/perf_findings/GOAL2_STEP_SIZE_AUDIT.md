# Goal 2 — Script 1 step-size audit

**Date:** 2026-07-12  
**Branch:** `perf/pass-a-convergence-diagnosis`  
**Code:** `src/resiflow/road_revised.py` (`network_flow_model`)

## Action

Audited the production Pass A assignment loop: how demand is loaded each iteration, how capacity feedback scales flows, and whether MSA / Frank–Wolfe link-flow blending exists outside the TNTP benchmark path.

## Results — baseline algorithm (pre–Goal 3)

Each iteration:

1. **Route 100% of current `remain_od`** — LCP args are built from full remaining Car21 per OD (`remain_od` grouped by origin).
2. **Capacity adjustment per path** — `adjust_r = min(acc_capacity / total_flow, 1)` along each path; assigned flow = `remain_flow × adjust_r`.
3. **Permanent accumulation** — edge flows merge into `road_links.acc_flow`; `acc_capacity` decreases; speeds update via piecewise cap-constrained profiles.
4. **Shrink `remain_od`** — subtract assigned flows; isolated / unreachable demand moves to `isolated_od`.

There is **no** link-flow averaging (MSA α = 1/k) or Frank–Wolfe direction search on **accumulated** link flows in baseline mode. Each iteration is **incremental all-or-nothing on the remainder**, not UE Frank–Wolfe.

## Stop conditions

| Condition | Threshold | Clone log at iter 58 |
|-----------|-----------|----------------------|
| `percentage_sumod >= 0.99` | 99% of **initial** demand assigned (cumulative) | ~64% — **not met** |
| `max_iterations` | env `RESIFLOW_MAX_FLOW_ITERATIONS` / `NIRD_*` | unbounded |
| Stagnation | 3 consecutive iters with `progress_rel < 1e-6` | never triggered |
| No remaining routable flow | empty `temp_flow_matrix_input` | not reached |

`percentage_sumod` tracks **cumulative assigned volume** (`assigned_sumod / initial_sumod`), not UE gap.

## MSA / FW elsewhere

| Module | Role |
|--------|------|
| `resiflow/assignment/ue_bpr.py` | BPR + MSA/FW for **TNTP benchmarks only** |
| `road_revised.network_flow_model` | **Production CONUS path** — incremental remain loading |

## Diagnosis

The clone stall pattern (Goal 1) is consistent with **fixed full-remainder steps** on a **piecewise cap-constrained** network:

- Early iterations move large mass (iter 1 assigns ~54% of initial supply).
- Later iterations face tighter capacities → smaller `adjust_r` → tiny reductions in `remain_od` despite many LCP passes.
- No under-relaxation → no guarantee of fast approach to a 99% assigned threshold.

This is an **algorithm / step-size** issue, not a multiprocessing or DuckDB bug.

## Goal 3 hook

Optional env flag (added on this branch):

- `RESIFLOW_REMAIN_ASSIGN_FRACTION=msa` (alias `NIRD_REMAIN_ASSIGN_FRACTION`)
- Scales routed demand by `α = 1 / iteration` before LCP while still subtracting full assigned flows from `remain_od` (experimental fractional remain loading).

See `GOAL3_FIX_AND_VALIDATION.md`.
