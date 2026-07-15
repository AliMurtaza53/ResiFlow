# Goal 4 — Escalation note (conditional)

**Date:** 2026-07-12  
**Branch:** `perf/pass-a-convergence-diagnosis`  
**Trigger:** Goal 3 fix insufficient at CONUS full-OD scale

## Status: deferred — bush / iTAPAS / PAS **not implemented**

Per investigation scope, Goal 4 documents escalation paths only if cheap fixes fail. Current evidence:

| Finding | Implication |
|---------|-------------|
| Clone log truncated at iter 59 with **35% remain** | Primary issue is **slow incremental loading**, not a hidden iteration cap |
| Stagnation guard never fired | Raising `min_progress_rel` or lowering `stagnant_limit` would **not** have stopped this run earlier |
| MSA remain flag added but not CONUS-validated | May help; **unproven** at clone scale |
| Piecewise cap-constrained speeds | Late-iter `adjust_r → 0` tail is **structural** to the current OR formulation |

## If MSA remain loading is insufficient after CONUS A/B

Escalation options (OR / product — **no code on this branch**):

1. **Accept isolation tail** — Stop at 99% *assigned* with explicit `isolated_od` accounting (already supported); document reroute metrics when ~35% demand is structurally unreachable under caps.
2. **Hybrid step rules** — Frank–Wolfe / conjugate Frank–Wolfe on a BPR surrogate for warm-start, then cap-constrained polish — requires OR validation vs current piecewise profiles.
3. **TAPAS / bush / PAS** — Advanced assignment from literature; high implementation cost; explicitly **out of scope** for this diagnosis branch.
4. **Demand / scope reduction** — Smoke-style OD sampling for sensitivity; not a production equilibrium fix.

## Recommendation

1. Run overnight **full-OD CONUS**: baseline vs `RESIFLOW_REMAIN_ASSIGN_FRACTION=msa`, same seed and iteration logging.
2. If remain fraction at iter 100+ still >10%, schedule OR review of **stop policy** (is 99% assigned the right criterion for cap-constrained freight?) before any bush/PAS investment.

## Explicit non-goals (this branch)

- No bush construction
- No iTAPAS / TAPAS step-size engine
- No PAS partial assignment swap

See `REPORT_PASS_A_CONVERGENCE.md` for consolidated recommendations.
