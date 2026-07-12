# Goal 1 — Pass A stall characterization (clone log)

**Date:** 2026-07-12  
**Branch:** `perf/pass-a-convergence-diagnosis`  
**Source log:** `C:\Users\akothaw\Desktop\DAFNI-NIRD-clone\logs\20260629_075855_passA_script1_baseline.log`  
**Parsed:** `experiments/pass_a_convergence/runs/clone_parsed.json`  
**Plot:** `experiments/pass_a_convergence/runs/clone_remain_fraction.png`

## Action

Parsed the Jul 6 clone Pass A baseline log with `parse_assignment_log.py`, extracted iteration controls, remain fraction, per-iteration progress, and stop messages. Generated remain-fraction vs iteration plot.

## Results — stop reason

| Check | Finding |
|-------|---------|
| `max_iterations` | **unbounded** (not capped at 58) |
| `min_progress_rel` | **1e-6** |
| `stagnant_limit` | **3** |
| Parsed iterations | **59** (log ends mid–iter 60 streaming pass 2) |
| `Stop:` messages | **None** |
| `log_truncated_no_stop` | **true** → process kill / wall timeout / external interrupt, **not** algorithmic convergence |

The run did **not** stop because stagnation fired or because 99% of demand was allocated. It was **truncated externally** while still making slow progress.

## Results — remain fraction trajectory

Initial supply: **148,917,265.7**

| Iteration | Remain fraction | Assigned fraction | progress_rel (of initial) |
|-----------|-----------------|-------------------|---------------------------|
| 1 | 0.461 | 0.539 | 53.9% |
| 10 | ~0.414 | ~0.586 | ~0.15% |
| 50 | ~0.375 | ~0.625 | ~0.05% |
| 58 | **0.357** | **0.643** | **0.051%** |
| 59 | 0.354 | 0.646 | 0.257% |

Pattern: **monotonic slow descent**, not oscillation or cycling. At iter 58, **~35.7% of initial demand remains unassigned** in `remain_od` — far from the 99% allocated stop threshold.

## Clarifying “~1.46% relative gap”

The user-reported **~0.0146 relative gap at iter 58** does **not** match `total_remain / initial_supply` (~0.357). Likely interpretations:

1. **Per-iteration `progress_rel`** — logged as a fraction of *initial* supply; at iter 58 it is **0.05083188%** (~5×10⁻⁴), not 1.46%.
2. **UE-style relative gap** — production Script 1 does not log Frank–Wolfe / Beckmann relative gap; the BPR UE module (`assignment/ue_bpr.py`) is TNTP-only.
3. **Assigned-fraction metric** — `1 - remain_fraction ≈ 0.643` at iter 58; “1.46% unassigned” would imply ~98.5% assigned, which this log contradicts.

**Conclusion:** The visible “stall” is **slow incremental loading** with **~36% demand still in `remain_od`**, combined with **log truncation** before natural stop. Stagnation guard never triggered because every iteration’s `progress_rel` exceeded `1e-6` by orders of magnitude.

## Stagnation guard (ruled out as stop cause)

At iter 58: `stagnant_iterations=0/3`. Even late iterations assign **50k–750k** vehicles per iter (`assigned_delta`), so `progress_rel` stays well above `min_progress_rel`.

## Next

Goal 2 audits whether missing MSA/FW step size explains slow descent. Goal 3 tests optional fractional remain assignment (`RESIFLOW_REMAIN_ASSIGN_FRACTION=msa`).
