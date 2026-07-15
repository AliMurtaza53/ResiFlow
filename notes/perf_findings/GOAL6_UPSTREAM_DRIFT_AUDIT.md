# Goal 6 — Upstream (DAFNI-NIRD) drift audit

**Date:** 2026-07-12
**Branch:** `perf/pass-a-convergence-diagnosis`
**Trigger:** Before testing any convergence fix, check whether the "iteration 58
stall" is actually a divergence from the published/upstream methodology rather
than a defect requiring a new algorithm.

## Summary

ResiFlow is a fork of [nismod/DAFNI-NIRD](https://github.com/nismod/DAFNI-NIRD)
(confirmed: [README.md:3](../../README.md#L3), `NIRD_*` env var lineage
throughout the codebase). DAFNI-NIRD is the reference implementation behind
Li et al. (2026), *"Stress-testing road network resilience using counterfactual
flood events (1953–2024) in Great Britain,"* Transportation Research Part D.

Diffing `src/resiflow/road_revised.py` against the upstream commit history pins
the ResiFlow fork point to roughly **Nov 2025 – Jan 2026** (contains the Nov 15
2025 edge-utilization logic, predates the Feb 2026 revision to it). Upstream has
had **~45 commits to `road_revised.py` since**, several bearing directly on the
exact convergence question under investigation on this branch.

## Finding 1 (primary): the stopping-policy divergence

Upstream `HEAD` hard-stops the assignment loop after **5 iterations**, no
exceptions, and dumps whatever remains in `remain_od` into `isolated_od`:

```python
if percentage_sumod >= 0.99: ... break
if iter_flag > 4:  # 5 iterations
    temp_isolation = ...remain_od...
    conn.execute("INSERT INTO isolated_od SELECT ... FROM remain_od")
    logging.info(f"Stop: Maximum iterations reached (5) with {temp_isolation} extra isolated flows.")
    break
```

This is not a placeholder — it has been stable across the upstream history we
reviewed. It matches the paper's own framework: isolation loss
(`SC = N_iso × ω`) is one of the two headline output metrics (direct damage,
rerouting, isolation), and Fig. 4 of the paper shows isolation costs
**exceeding direct damage by an order of magnitude** for the most severe
events. Undelivered demand becoming "isolated" is intended model output, not a
failure state to be minimized away by running more iterations.

ResiFlow's fork ([road_revised.py:2496](../../src/resiflow/road_revised.py#L2496))
replaced the hardcoded cap with a configurable one that **defaults to
unbounded**:

```python
max_iterations = int(get_env("RESIFLOW_MAX_FLOW_ITERATIONS", "NIRD_MAX_FLOW_ITERATIONS", "0") or "0")
```

and added a stagnation detector (`stagnant_limit=3`, `min_progress_rel=1e-6`)
as the intended replacement stopping condition. Per [GOAL1_STALL_CHARACTERIZATION](GOAL1_STALL_CHARACTERIZATION.md),
that stagnation guard **never fired** through iteration 58+.

**Implication:** the "35% remaining at iteration 58" observation may not be a
stall to fix at all — it may be ResiFlow chasing a convergence target (drain
`remain_od` to near-zero) that the published, validated method never attempts
past iteration 5, instead accounting for the remainder as isolation cost. This
needs to be tested before any algorithmic change is considered (see Test Plan
below).

## Finding 2: missed edge-utilization threshold fix

Upstream commit `df56a1d` (2026-02-25) changed the "fully utilized edge"
threshold from `ratio < 0.001` (0.1% of capacity) to `ratio < 0.01` (1% of
capacity) in `update_network_structure`. ResiFlow is still on the stricter
0.1% threshold (matches the pre-fix upstream state as of Nov 15 2025,
commit `e04c224`). This threshold governs how aggressively near-saturated
edges are pruned from the graph each iteration — a stricter threshold means
edges linger in the graph holding negligible residual capacity, plausibly
contributing to repeated low-yield routing attempts in late iterations.

This is a published, low-risk fix to adopt (single-line threshold change),
not a new algorithm.

## Finding 3: unreviewed streaming/path-realization rework

Upstream commits `0379a9d`, `c501fb5` (Mar 2 2026) and `a215385`, `2a21951`
(Mar 9 2026) reworked `itter_path` to be SQL-first in DuckDB with streamed OD
args (no full arg-list materialization) and chunked/configurable-thread
aggregation. This directly targets the same cost center flagged independently
on the `perf/numcpu-regression-diagnosis` branch: the serial post-LCP
streaming/DB-write phase, measured at ~60% of Pass B wall time on clone data
(see [GOAL2_ISOLATION.md](GOAL2_ISOLATION.md)). Upstream may have already
solved a problem we were about to profile from scratch. Needs a direct diff
against the current `itter_path`/streaming implementation before any new
profiling work is scoped.

## Finding 4: unreviewed multimodal support

Upstream commit `d7db09a` (2026-01-15), "adapting functions to support
multimodal analysis," postdates the ResiFlow fork and is directly relevant to
this project's goal of adding freight flows alongside passenger flows. Should
be reviewed before building freight/passenger multimodal support
independently, to avoid diverging from or duplicating an existing solution.

## Non-findings / lower priority

- Upstream's `225559c` (Sep 2025) stopping-condition change predates the
  DuckDB rewrite series (Nov 2025) and describes an older architecture no
  longer structurally comparable to ResiFlow's current `network_flow_model`.
  Historical context only.
- Upstream briefly added then removed a "low-saturation edge" isolation check
  (`1528648` add, `c1b5d21` remove, Sep–Oct 2025) — tried and abandoned before
  the ResiFlow fork point; not applicable.
- Most recent upstream commits (`e8c69b9`, `663ee1f`, 2026-07-07, 5 days
  before this audit) change OD loading to batch processing — not yet
  reviewed for relevance, flagged for a future pass.

## Recommendation

Adopting Findings 1–2 is **not** an algorithmic change in the sense the
supervisor conversation was worried about — it is reconciling with the same
published, peer-reviewed method this project is trying to replicate, which
kept evolving upstream for ~8 months while this fork stood still. This is
lower-risk and more defensible than any TAPAS/FW-style change.

See [GOAL6_TEST_PLAN.md](GOAL6_TEST_PLAN.md) for the benchmark plan and
[GOAL6_TEST_RESULTS.md](GOAL6_TEST_RESULTS.md) for results as they land.
