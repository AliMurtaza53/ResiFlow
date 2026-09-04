# Goal 6 — Test results: 50k sample, 2M probe, isolation-logging verification

**Date:** 2026-07-13
**Prerequisite reading:** [GOAL6_UPSTREAM_DRIFT_AUDIT.md](GOAL6_UPSTREAM_DRIFT_AUDIT.md),
[GOAL6_TEST_PLAN.md](GOAL6_TEST_PLAN.md)

## 1. 50k-OD CONUS sample (configs A/B/C)

Ran `run_conus_convergence_sample.py` at the harness default 50k-OD sample
with `--max-flow-iterations 0` and `5`. **Both configs converge in a single
iteration** (`remain_fraction=0.0`, 100% assigned) — identical to the Goal 3
finding. This scale is too small to stress-test capacity pressure; **configs
A/B/C are indistinguishable at 50k-OD**. No further conclusions possible at
this scale.

One parser artifact noted: on a clean 1-iteration full-convergence run, the
loop exits via the `while total_remain > 0` condition becoming false rather
than an explicit `percentage_sumod >= 0.99` branch firing (remain hits exactly
0 before the check), so no `"Stop: ..."` line is logged. `parse_assignment_log.py`
reports `log_truncated_no_stop: true` in this case even though the run
completed normally — this flag conflates "genuinely truncated/killed" with
"exited the loop with nothing left to do." Worth a follow-up fix to the parser
if this scale of run is used again, but not blocking.

## 2. 2M-OD CONUS probe (unbounded, NumCpu=1)

Ran the same harness at `--sample-od-n 2000000 --max-flow-iterations 0`.
Killed after **117 iterations / ~16.5 hours** (process still actively
progressing — `baseline.duckdb` growing, not hung — killed because we already
had enough signal and didn't want to tie up the machine further).

Key numbers (`initial_supply = 31,556,390`):

| Iteration | remain_fraction | progress_rel (this iter) |
|---|---|---|
| 1 | 0.4158 | 58.42% (of initial supply) |
| 5 | 0.3793 | 0.57% |
| 10 | 0.3585 | 0.40% |
| 117 (killed) | 0.1384 | 0.15% |

**Per-iteration wall time:** ~4.5–5 min/iteration at this OD scale, NumCpu=1
(confirmed from log timestamps, iterations 1–3).

**Reads on the two open questions from the test plan:**

- **Is `remain_fraction` still descending well past iteration 5?** Yes,
  clearly — it drops from 0.42 → 0.14 between iterations 1 and 117, a
  real and steady (if slow) decline, not a flatline. This is the same
  qualitative shape as the clone's iteration-58 observation (`remain_fraction
  ≈ 0.357` there).
- **Would upstream's hardcoded 5-iteration cap have been reasonable here?**
  At iteration 5, `remain_fraction = 0.379` — i.e., **upstream's cap would
  book 37.9% of this sample's demand as "isolated"** while progress was still
  clearly ongoing (13.8% remained after 112 more iterations). This is an
  important caveat to the earlier recommendation: **naively adopting
  upstream's 5-iteration cap as-is is not obviously correct for CONUS-scale
  demand** — either (a) upstream's GB network/OD structure converges faster
  in absolute iteration count than ours does, (b) upstream's post-March-2026
  `itter_path`/threshold changes make each of *their* iterations more
  effective than ours (plausible — see Finding 3 in the drift audit), or (c)
  there is additional undiscovered drift in our fork's flow-adjustment math
  beyond the two fixes already identified. **Do not port the bare 5-iteration
  cap without also porting the efficiency fixes (Finding 2/3) and re-testing** —
  doing so first would risk misclassifying a large amount of genuinely
  routable demand as isolated.

## 3. Isolation-count logging: verified correct (with one gap found and fixed)

Neither the 50k runs (converge in 1 iter, isolation never triggered) nor the
2M probe (killed mid-run, no stop branch reached) exercised the isolation
stop-and-dump code path. Ran a **targeted 1-iteration test**
(`--sample-od-n 2000000 --max-flow-iterations 1`, label
`goal6_isolation_logging_check`) specifically to trigger it — completes in
~5 min given the measured per-iteration cost above.

**Result:** `"Stop: Maximum iterations reached (1) with 13,120,186.87 extra
isolated flows."` — correctly parsed by `parse_assignment_log.py` into
`isolated_flow_at_stop` / `isolated_fraction_at_stop`, and correctly matches
what remained in `remain_od` at that point.

**Gap found and fixed:** `isolated_od` in the run's `baseline.duckdb`
contained **29,892,555** total flow — not 13,120,187. The difference is two
*other* isolation channels the parser wasn't capturing, both logged and
inserted into `isolated_od` every iteration independent of the stop condition:

- `"Initial isolated flows: {X}"` ([road_revised.py:2707](../../src/resiflow/road_revised.py#L2707)) — OD pairs whose origin/destination node isn't in the current network. `0.0` in this run.
- `"Non_allocated_flow: {X}"` ([road_revised.py:2907](../../src/resiflow/road_revised.py#L2907)) — OD pairs for which no path was found during LCP. `16,772,368.12` in this run.

`13,120,186.87 + 16,772,368.12 + 0.0 = 29,892,554.99` — **matches the
`isolated_od` DB total exactly** (rounding aside). Added `INITIAL_ISOLATED_RE`
/ `NON_ALLOCATED_RE` to `parse_assignment_log.py`, tracked per-iteration, and
exposed `total_initial_isolated_flow`, `total_non_allocated_flow`,
`total_isolated_flow`, `total_isolated_fraction` in the parsed output —
**verified against the DB ground truth, not just the log text.**

## 4. Open question flagged (not yet resolved)

In the 1-iteration isolation check run: `assigned_delta (18.44M) + total_remain
(13.12M) + non_allocated (16.77M) = 48.33M`, which **exceeds** `initial_supply
(31.56M)`. If these three are meant to be a mutually-exclusive partition of
the initial demand, they shouldn't sum to more than the whole. This wasn't
chased further today — flagging it as a follow-up before leaning on
assigned/remain/isolated percentages for downstream decisions. Possible
explanations to check: whether `remain_od` truly excludes no-path OD pairs
before the "total remain flow (after adjustment)" figure is logged (code
suggests yes, at [road_revised.py:2925-2928](../../src/resiflow/road_revised.py#L2925-L2928)), or whether the 2M-OD sample generation produces duplicate
origin/destination rows that get double-counted across the assigned vs.
isolated queries.

**Important scope caveat:** this 2M-OD sample draws from a regional/toy data
bundle (per existing notes, VA-scale), not full CONUS. A ~94.7% total-isolated
figure in this specific run is very likely a **data-extent artifact** (many
sampled OD pairs' endpoints may fall outside the loaded regional network, so
"no path found" is expected, not a capacity or algorithm failure) — not
evidence about full-CONUS behavior. Do not extrapolate the isolation
*fraction* from this run; only the logging/parsing *mechanism* was the
validation target here, and that is now confirmed correct.

## Next steps

1. Resolve the Section 4 bookkeeping question with a quick targeted check
   (small OD sample, manual trace) before it affects any reported metric.
2. Port Finding 2 (edge-utilization threshold `0.001→0.01`) and Finding 3
   (SQL-first streaming + `PRAGMA threads`) from the drift audit.
3. Re-run the config A/B/C comparison (and the iteration-5 checkpoint
   analysis above) *after* porting those fixes, since the current results
   may not reflect the pipeline's efficiency once the streaming bottleneck is
   addressed.
4. Do not adopt the bare 5-iteration cap in isolation — re-derive the
   appropriate cap (or keep the stagnation-based approach, tuned) once
   per-iteration cost and effectiveness are back in line with upstream.
