# Multi-agent coordination rulebook

This file exists because of a real incident: two different agents (Cursor on
one branch, Claude on another, weeks apart, neither aware of the other)
independently built the same new module from scratch — `src/resiflow/sa/`
and `tests/test_sa_curves.py` — producing two incompatible versions that
conflict on merge. Separately, `feature/hpms-la-challenger` and
`feature/county-connector-disaggregation` turned out to be two different
agents (Cursor, then Claude) re-committing byte-identical fixes under two
different branch names, because neither checked what the other had already
done. Both incidents were 100% preventable by reading this file first.

**Read this before creating a branch, a worktree, or starting any
multi-session piece of work in this repo — whether you're Claude, Cursor, or
any other agent.**

## The one rule that would have prevented both incidents

**Before writing any new module, function, or branch: check the ledger below
and grep the repo for anything that might already be doing this.** If you
are about to create a file that doesn't exist yet, that is exactly the
moment two agents are most likely to collide — search first.

## Active worktree / branch ledger

**Canonical copy (rule set 2026-11-17):** this file on `feature/anaheim-assignment-diagnostics` is the single source of truth for the ledger. Other branches carry stale or partial copies and MUST NOT edit rows independently. To sync a branch: `git checkout origin/feature/anaheim-assignment-diagnostics -- AGENTS.md`. When you merge a branch, resolve any `AGENTS.md` conflict by taking this copy, then remove your own row. Add or update your row on this branch first, not on yours.

Keep this table current. Update it the moment you start or finish a unit of
work — this is the single source of truth for "who's touching what," checked
*before* branching, not discovered after a conflict.

| Worktree / branch | Owner (agent + session) | Scope (files/subsystem) | Status | Last synced |
|---|---|---|---|---|
| `.worktrees/connector-loading-test1` → `exp/connector-loading-test1` (A/B pilot; same Codex owner) | Codex (2026-11-18 rebase/pilot session) | Clark reconciliation onto 701062a; clean all-hazard virtual exemption; five-county fixed-OD additional-exit pilot. No Arm C, integration merge/push, branch deletion or freeze | STOP at registered coverage gate. Rebased; 55797 gets 100%, 55804 zero. Four recovery reruns passed all physical/damage checks and 48 zero-shortcut exports. All-hazard clean patch READY: 60 unique executed checks validated across broad/focused runs; 2 real-network checks skipped. Prep 3797277: 44 regressions passed, 41 exits at 15/26 units; Brazoria/Chambers have zero additions. No primary jobs submitted; neither arm frozen. Materiality remains 5%; GIS/node list and unexecuted V2 proposal committed. Three setup jobs cancelled before compute; scientific pilot used 0.188 allocated CPU-hours | 2026-11-18 |
| `.worktrees/viz-envelope-panels` → `viz/envelope-panels` (local, off `viz/results-bridge` `c2b5ccd`) | Claude (2026-11-23 session, forked with owner confirmation; Cursor's `viz/results-bridge` untouched) | `results/viz/` panel plots for the 8-event final envelope (2 events per hazard family: add 305 Sandy, 404 Cascadia, 502 Cascadia landslide, 603 Elliott), and the `results_long.csv` writer from `finalA_*` outputs. No model code | Active. Waits on the 24 envelope event jobs on Hopper (running 2026-11-23). No push or merge without owner | 2026-11-23 |
| `.worktrees/dense-net-passenger` → `exp/dense-net-passenger` | Cursor (dense-network pilot) | `scripts/experiments/dense_net/` and its report in `docs/handoffs/` only; no edits to `road_revised.py` or damage modules. Spec `DENSE_NET_PASSENGER_CURSOR_SPEC.md` plus 2026-11-16 addendum | Active. Anaheim TNTP and OSM tract comparison done (`58cc39f`, `DENSE_NET_PASSENGER_RESULT.md`); open question on identical VHT across networks. Orange County waits for the owner | 2026-11-16 |
| `.worktrees/connector-loading-test1` → `exp/connector-loading-test1` | Codex (connector loading tests 1–2; history, same owner) | FAF5 connector restore, endpoint-only access, Harvey-15 pilot, Test 2 S and G allocation, handoffs in `docs/handoffs/` | Superseded by the current A/B pilot row above. Test 1 zero-shortcut gate and full-CONUS C+S/G freight comparisons completed; G allocation and GIS review implemented. Mean weight used for missing parent records. Virtual-hazard qualification passed; the A/B pilot stopped at rural coverage; do not start a second G allocation workstream from the obsolete 2026-11-16 status | 2026-11-18 |
| `.worktrees/viz-results-bridge` → `viz/results-bridge` (local, unpushed, off `viz/paper-figures` `04b4746`) | Cursor | `results/viz/` diagnostics figures, `figlib/data.py` real/synthetic provider, `scripts/postprocess/write_results_long.py`; carries a cherry-pick of `feat/run-summary-bridge` | Parked 2026-11-17 after Steps 1–3 (`c2b5ccd`): S1 diagnostics real, RQ1–3 sheets still synthetic. Waits for a passenger-only Stage 4 mode and freight reruns on the merged code. No push or merge without owner | 2026-11-17 |
| `.worktrees/harvey-rerun-report` → `ops/harvey-rerun-report` | Owner (Alimurtaza Husain Kothawala) | Harvey rerun and county isolation report (`c1fd93e`, 2026-11-13) | Worktree clean, no ledger row existed. Owner to say whether to merge and delete or keep | 2026-11-17 |
| `.worktrees/run-summary-bridge` → `feat/run-summary-bridge` (local only, off `1206112`) | Claude (this session) | `scripts/postprocess/baseline_run_bridge.py` and its test: stage 1 run outputs to figure-ready CSVs. Read-only on run outputs, no model code | Parked. Cherry-picked into `viz/results-bridge` (Cursor, local). Delete after that branch merges | 2026-11-16 |
| `feature/hpms-la-challenger` (main repo dir, and now Hopper's clone too) | Claude (this session) | HPMS-vs-FAF5 LA challenger experiment, `road_revised.py` LCP path | Active — this is now the single canonical branch for this work on both local and Hopper | 2026-11-10 |
| ~~`feature/county-connector-disaggregation`~~ | Resolved 2026-11-10 | Was a duplicate of the row above, committed independently on Hopper under its old pre-rename branch name | **Retired** — branch deleted (local, remote, and Hopper's checkout switched to `feature/hpms-la-challenger`). The orphaned local worktree `ResiFlow.worktrees/connector-work` still needs `git worktree remove` (blocked for an agent, run it yourself) | 2026-11-10 |
| `ResiFlow.worktrees/ponytail-code-restraint-guidance` → `viz/paper-figures` | Unclear | Registry-driven paper figure pipeline (`results/viz/figlib/`) | Underdeveloped, expected to change — leave branch open, don't merge yet | 2026-10-22 |
| `feature/anaheim-assignment-diagnostics` (worktree `.worktrees/anaheim-diagnostics`) | Claude (2026-11-10 session) | Anaheim TNTP testbed with real GeoJSON link geometry (`tests/data/anaheim_tntp/`, `parameters/testbeds/anaheim.json`, `networks/tntp.py`), then assignment-iteration logging/invariants/visual debugging for `network_flow_model` before scaling to CONUS | Active, and now the INTEGRATION branch: vehicle class (ogv/car), truck PCE 2.0 capacity-only, sealed fuel, county commute occupancy merged 2026-11-16 (`badf15e`, ex-`fix/vehicle-classes`, deleted). Branched from `feature/hpms-la-challenger` @ 1bf602c. Owns the additive iteration-audit logging in `road_revised.py` (see `docs/ASSIGNMENT_AUDIT_LOG.md`) and the env-gated per-iteration dump `src/resiflow/audit_dump.py` (see `docs/ASSIGNMENT_DUMP_SPEC.md`); the freight/Hopper work reuses them instead of writing its own Update 2026-11-22: also carries the all-hazard virtual-link exemption (`6633589`), endpoint-only FAF5 connector routing plus the native-network switch and C+S+G builders cherry-picked from `exp/connector-loading-test1` (`ccf37e4`), and New Madrid M7.7 for envelope events 403/503 (`ef0a1cf`). `perf/hopper-realize-paths-streaming-fix` (tip `48fee86`) was content-diffed against this branch, found already contained, and deleted 2026-11-22 with owner confirmation. Update 2026-11-23: network A frozen (T29 freight OD, Clark-fixed passenger split OD; inputs in Hopper `/home/akothaw/frozen_inputs_networkA_20261123`); final-envelope baselines FR and PX done, PX+FR running; launch scripts in `experiments/final_envelope/`; see `docs/handoffs/FINAL_HAZARD_ENVELOPE.md` | 2026-11-23 |
| `feature/hpms-faf-lrs-transfer` (no worktree currently) | Claude + Cursor (co-authored) | `scripts/hpms_to_faf_lrs_transfer.py`, LRS attribute transfer | Exploratory pilot, **not** validated for production use (see `docs/HPMS_FAF_LRS_TRANSFER.md` — ~22% national match rate, 4 states at 0% match) | 2026-09-22, not touched since |
| `src/resiflow/sa/` (no dedicated branch — exists independently on `main` via a merged GitHub PR, and on the long `feature/hpms-la-challenger` lineage) | Cursor (main's PR #3); Claude (feature-branch version) | Sensitivity-analysis curves module | **Resolved 2026-11-10, not yet applied** — not actually a duplicate: main's version is dead code (zero callers anywhere); the feature-branch version is the real one, actively called from `scripts/3_damage_analysis.py` and covered by 9 passing tests. When `main` and the feature branch are eventually reconciled, take the feature-branch version outright (see `scripts/cleanup/diff_sa_curves_collision.sh`) | n/a |

When you finish a unit of work: merge, delete the branch (see
`docs/CORRECTNESS_AND_PERFORMANCE_LESSONS.md` and the project's standing
norm — merged branches get deleted immediately, not left around), and
remove its row from this table.

## Before starting new work

1. **Read this table.** If another row already covers the file(s) or
   subsystem you're about to touch, don't start a parallel branch — either
   continue that branch, or explicitly ask the user to confirm you should
   fork it.
2. **`git fetch` and check how far your base branch is behind `main`** (or
   the actual integration branch you were told to build on) before you
   start. If it's more than a few days stale, resync first — don't build on
   a week-old snapshot.
3. **Grep before you build.** If you're about to create a new file/module
   that doesn't exist yet, search the whole repo (all branches:
   `git log --all --oneline -- '**/<likely_name>*'`) for anything with a
   similar name or purpose first. This is exactly the step that was skipped
   before `src/resiflow/sa/curves.py` got built twice.

## While working

- **One agent/session per worktree, one active branch per worktree.** Don't
  have two sessions committing to the same branch at the same time without
  coordinating — that's how `feature/county-connector-disaggregation` and
  `feature/hpms-la-challenger` ended up duplicating each other's fixes.
- **Short-lived branches.** Rebase onto the integration branch at the start
  of each session; don't let a branch sit unmerged for weeks — every branch
  in the ledger above that went stale for more than a few days is exactly
  where this project's duplicate-work incidents came from.
- **Name every commit's authorship honestly.** If an AI agent made the
  change, say so (`Co-authored-by: Cursor <cursoragent@cursor.com>`,
  `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`, etc.) — this is
  already happening in some commits here and is the only reason it was
  possible to reconstruct, after the fact, which agent built which duplicate
  module. Keep doing it everywhere.
- **For any task spanning more than one session, write a bounded-mandate
  doc first** — scope, fixed budget, explicit decision gate, "stop and
  report" framing — the same shape as `hpms_la_challenger_instructions.md`.
  That document is the reason the HPMS-LA challenger work, unlike the `sa/`
  module collision, stayed scoped and legible across multiple sessions.

## Before merging / finishing a unit of work

1. Run the relevant existing tests. If you changed a hot path or a shared
   utility, name which tests you ran and what they covered — don't just
   report "it ran faster" (see
   `docs/CORRECTNESS_AND_PERFORMANCE_LESSONS.md`, Lesson 2: a timing win is
   not a correctness proof).
2. Merge to the integration branch promptly — same day if possible, not
   "whenever convenient." Every day a branch sits unmerged is another day
   it can silently collide with someone else's work.
3. Delete the branch immediately after merge (local and remote). The
   commits aren't lost — they live permanently in the integration branch's
   history — only the stale pointer goes away.
4. Update the ledger above.

## If you find a duplicate / collision anyway

Don't silently pick one side and discard the other. Diff them, understand
what each version actually does differently, and either reconcile
deliberately or flag it to the user with both versions named — exactly as
was done for `src/resiflow/sa/curves.py` (still unresolved — see the ledger
note above once that's picked up).
