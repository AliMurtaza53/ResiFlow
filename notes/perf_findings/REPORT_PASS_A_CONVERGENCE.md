# Pass A convergence diagnosis — report

**Date:** 2026-07-12  
**Branch:** `perf/pass-a-convergence-diagnosis` (from `perf/numcpu-regression-diagnosis`)  
**Scope:** Diagnose Jul 6 clone Pass A “stall” at iteration 58; rule out cheap fixes; separate Goal 5 hazard footprint work for Pass B. **No bush / iTAPAS / PAS implementation.**

## Executive summary

| Goal | Conclusion |
|------|------------|
| **1 — Stall characterization** | Clone run **did not converge**; log **truncated** at iter 59 with **~35% demand still in `remain_od`**. Not an iteration cap or stagnation stop. |
| **2 — Step-size audit** | Production Script 1 uses **full-remainder incremental loading** with **no MSA/FW** on link flows. Explains slow late-iteration progress. |
| **3 — Fix** | Opt-in **`RESIFLOW_REMAIN_ASSIGN_FRACTION=msa`** (+ logging). Validated on Sioux Falls / 50k smoke only; **full-OD CONUS A/B pending**. |
| **4 — Escalation** | Deferred. If MSA insufficient → OR review of stop policy before bush/PAS. |
| **5 — Hazard footprint** | 30 m vs 90 m max-resample: **~10,610 vs ~10,617** damaged links in VA window on CONUS — resolution negligible vs extent. |

**NumCpu policy (prior branch):** unchanged — **NumCpu=1** for CONUS Pass B wall time.

---

## Goal 1 — What happened on the clone?

- **Log:** `20260629_075855_passA_script1_baseline.log`
- **59 iterations parsed**, no `Stop:` line, `log_truncated_no_stop: true`
- **Controls:** unbounded iterations, `min_progress_rel=1e-6`, `stagnant_limit=3`
- **Iter 58:** `remain_fraction=0.357`, `progress_rel≈0.05%` of initial supply per iter
- User “~1.46% gap” **≠** remain fraction; likely a different metric or misread assigned fraction

Detail: [`GOAL1_STALL_CHARACTERIZATION.md`](GOAL1_STALL_CHARACTERIZATION.md)

---

## Goal 2 — Why is progress slow?

Baseline loop routes **100% of `remain_od`** each iteration, scales by path `adjust_r`, permanently accumulates to `acc_flow`. Cumulative stop at **99% assigned** was only **~64%** at truncation.

Detail: [`GOAL2_STEP_SIZE_AUDIT.md`](GOAL2_STEP_SIZE_AUDIT.md)

---

## Goal 3 — Cheapest algorithmic knob

```powershell
$env:RESIFLOW_REMAIN_ASSIGN_FRACTION = "msa"
```

Routes `remain × (1/k)` at iteration k. **Default unchanged.**

Sioux Falls + CONUS 50k smoke: both converge in **1 iteration** — insufficient to stress-test.

Detail: [`GOAL3_PASS_A_FIX_AND_VALIDATION.md`](GOAL3_PASS_A_FIX_AND_VALIDATION.md)

---

## Goal 4 — If cheap fix fails

Document-only escalation: accept isolation tail, OR hybrid FW warm-start, or product stop-policy review. **No bush/PAS code.**

Detail: [`GOAL4_ESCALATION_NOTE.md`](GOAL4_ESCALATION_NOTE.md)

---

## Goal 5 — Pass B hazard resolution

VA toy raster on CONUS links in extent:

| Treatment | Damaged links |
|-----------|---------------|
| ~50 m native | 10,610 |
| ~90 m max resample | 10,617 |

Smoke Script 2 artifact: **124** unique damaged edges (full pipeline, smoke scope).

Detail: [`GOAL5_HAZARD_RESOLUTION_FOOTPRINT.md`](GOAL5_HAZARD_RESOLUTION_FOOTPRINT.md)

---

## Artifacts

| Path | Purpose |
|------|---------|
| `experiments/pass_a_convergence/parse_assignment_log.py` | Clone log parser |
| `experiments/pass_a_convergence/plot_convergence.py` | Remain-fraction plot |
| `experiments/pass_a_convergence/run_sioux_convergence.py` | Baseline vs MSA |
| `experiments/pass_a_convergence/run_conus_convergence_sample.py` | 50k smoke sample |
| `experiments/pass_a_convergence/hazard_footprint_sweep.py` | Goal 5 table |
| `experiments/pass_a_convergence/runs/clone_parsed.json` | Parsed clone metrics |
| `experiments/pass_a_convergence/runs/clone_remain_fraction.png` | Convergence plot |

Runs directory is gitignored.

---

## Recommended next steps

1. **Overnight full-OD CONUS:** baseline vs `msa`, parse logs with `parse_assignment_log.py`, compare remain fraction at iter 50/100/200.
2. **Product / OR:** Confirm whether **99% assigned** is the correct production stop for cap-constrained freight; if not, adjust stop policy before investing in TAPAS-class solvers.
3. **Pass B:** Proceed with Track A state windows; do not block on 30 m vs 90 m resolution for VA-scale sensitivity.
4. **Keep NumCpu=1** for Pass B until a separate numcpu fix lands.

---

## Goal 6 — Upstream drift audit and test results

ResiFlow forks nismod/DAFNI-NIRD (the codebase behind Li et al. 2026, TRD),
~8 months stale. Upstream hard-stops at 5 iterations and books the remainder
as "isolated" (a first-class output metric in the paper, not a bug); ResiFlow's
fork made this unbounded, relying on a stagnation guard that never fires —
plausible root cause of the iteration-58 stall being a policy divergence, not
an algorithmic defect. Also missing: a Feb 2026 edge-utilization threshold fix
and a Mar 2026 rework (`PRAGMA threads=N` + SQL-first streaming) that explains
why upstream's multi-core runs scale and ours regress.

Live-tested at 2M-OD CONUS sample scale: `remain_fraction` is still clearly
descending at iteration 117 (0.42→0.14), confirming upstream's bare 5-iteration
cap should **not** be ported as-is without first porting the efficiency fixes.
Isolation-count logging verified correct against DuckDB ground truth after
fixing a parser gap (two previously-uncaptured isolation channels).

Detail: [GOAL6_UPSTREAM_DRIFT_AUDIT.md](GOAL6_UPSTREAM_DRIFT_AUDIT.md),
[GOAL6_TEST_PLAN.md](GOAL6_TEST_PLAN.md), [GOAL6_TEST_RESULTS.md](GOAL6_TEST_RESULTS.md)

## Goal 7 — Fixes applied, profiled, and validated

Ported the threshold fix and `PRAGMA threads=num_cpu` from Goal 6. Result:
NumCpu=4's catastrophic regression is gone (real win) but wall time is only
~3% better than NumCpu=1 (not a clean scaling win) — root cause is that the
production path-realization strategy's dominant cost is a **Python loop**,
which `PRAGMA threads` cannot touch. Profiled with `pyinstrument` and found
(and fixed) a per-edge Python `dict.get` costing ~21s/87s (~24%) of that
function, replaced with vectorized `pandas.reindex`. A **second, larger**
`dict.get` site was found (nested per-path-edge flood/event matching loop) —
not fixed yet, flagged as the best-evidenced next target. Also found a
pre-existing bug in the unused `duckdb_chunked_compact` strategy (missing
`od_id` column in an INSERT) that blocks testing it as a `PRAGMA threads`-
friendly alternative. All fixes verified against the full pytest suite
(90 passed, 3 skipped), no regressions.

Detail: [GOAL7_PROFILING_AND_STRATEGY_RESULTS.md](GOAL7_PROFILING_AND_STRATEGY_RESULTS.md), chart at `goal6_profile_summary.png`.

## Goal 8 — Full follow-up queue: vectorization delivers a 3-4x win

Resolved the bookkeeping "anomaly" (naming issue, not a bug) and confirmed OD
sampling needs no seed fix (already deterministic). Fixed `duckdb_chunked_compact`'s
reported `od_id` bug, then **abandoned it** after benchmarking exposed a second
bug and much worse scaling than `streaming_arrays` at 500k-OD scale (13m41s
for one sub-phase alone, and *slower* at 4 CPUs than 1). The real win:
vectorized the event-edge flood-matching loop (the second `dict.get` hotspot
from Goal 7) using precomputed boolean masks — verified byte-identical output
against the pre-change baseline (no existing test covered this path), and
`pyinstrument`-confirmed the `dict.get` cost is now completely gone.
`realize_paths_streaming` dropped from 87.1s → 14.9s; full script wall time
from ~156-190s → ~43-47s on the same profiling scenario.

Detail: [GOAL8_FULL_QUEUE_RESULTS.md](GOAL8_FULL_QUEUE_RESULTS.md)

---

## Related work

- NumCpu regression branch: `perf/numcpu-regression-diagnosis`, report in `notes/perf_findings/REPORT_FOR_TOM.md`
- Performance overview: `Performance_note.md`
