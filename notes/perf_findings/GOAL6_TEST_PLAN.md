# Goal 6 — Test plan: reconciling with upstream stopping policy

**Prerequisite reading:** [GOAL6_UPSTREAM_DRIFT_AUDIT.md](GOAL6_UPSTREAM_DRIFT_AUDIT.md)

## Question to answer

Does the "iteration 58, 35% remaining" observation represent (a) a genuine
algorithmic stall that would persist even under the published methodology, or
(b) an artifact of ResiFlow running far past the point (5 iterations) where
the published method stops and books the remainder as isolation cost?

No solver/algorithm code changes in this phase — only exercising the existing
`RESIFLOW_MAX_FLOW_ITERATIONS` flag that's already wired up.

## Configurations under test

| Config | `RESIFLOW_MAX_FLOW_ITERATIONS` | Stagnation guard | Purpose |
|---|---|---|---|
| **A. current-default** | `0` (unbounded) | active (`stagnant_limit=3`) | ResiFlow's current fork behavior |
| **B. upstream-parity** | `5` | irrelevant (loop stops first) | Reproduces published stopping rule |
| **C. extended** | `15` (existing CONUS-sample harness default) | active | Middle ground, already-used harness default |

Threshold fix (Finding 2, `ratio < 0.001` → `0.01`) is **not** applied in this
phase — testing the stopping-policy question in isolation first, one variable
at a time.

## Metrics captured per run

All available today via `parse_assignment_log.py` output plus run metadata,
no new instrumentation required except where noted:

1. **Wall time** (total, from `run_meta.json` / subprocess timing) — already captured.
2. **Iteration count at stop** — `iteration_count` in parsed log.
3. **Stop reason** — `stop_messages` (which branch fired: 99% threshold / max-iterations / stagnation).
4. **Remain-fraction curve** — `remain_fraction` per iteration, to see the shape (still descending vs. genuinely flat).
5. **Assigned fraction at stop** — `1 - remain_fraction` at the final iteration.
6. **Isolated flow at stop** — *(new, see below)* — the `N_iso` dumped to `isolated_od`, parsed from the `Stop:` message text (`"... with {temp_isolation} extra isolated flows"`).
7. **Isolation-to-assigned cost ratio** *(sanity check against the paper, if time permits)* — not required for Phase 1; only relevant once cost outputs (rerouting/isolation $) are computed downstream, which Pass A alone does not produce.

## Harness

Reuse existing scripts, no new harness code beyond the parser extension:

```powershell
# CONUS 50k-OD Pass A smoke sample, three configs
python experiments/pass_a_convergence/run_conus_convergence_sample.py --mode baseline --max-flow-iterations 0  --label goal6_A_unbounded
python experiments/pass_a_convergence/run_conus_convergence_sample.py --mode baseline --max-flow-iterations 5  --label goal6_B_upstream_parity
python experiments/pass_a_convergence/run_conus_convergence_sample.py --mode baseline --max-flow-iterations 15 --label goal6_C_extended
```

Artifacts land in `experiments/pass_a_convergence/runs/goal6_*/` (gitignored):
`script1_passa.log`, `parsed.json`, `run_meta.json` (where applicable).

## Decision rule

- If config A (unbounded) shows `remain_fraction` still meaningfully
  descending at iteration 5 (i.e., config B would cut off mid-progress) **and**
  the isolation fraction booked at iteration 5 is implausibly large relative
  to what the paper's GB results show — that's evidence more iterations than 5
  are warranted for CONUS-scale demand, and the unbounded/stagnation approach
  may be a legitimate, deliberate adaptation (worth documenting as such, not
  reverting).
- If `remain_fraction` is already flattening out well before iteration 58 (little
  additional progress per iteration beyond ~5–15), that supports the
  interpretation that continuing past the published cap buys little and the
  divergence is accidental, not beneficial — recommend reverting the default
  to something close to upstream's 5, or explicitly re-deriving the "right"
  cap for CONUS scale from this data rather than leaving it unbounded.
- Either outcome is informative and requires no further code change to reach —
  only the run + parse.
