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

Keep this table current. Update it the moment you start or finish a unit of
work — this is the single source of truth for "who's touching what," checked
*before* branching, not discovered after a conflict.

| Worktree / branch | Owner (agent + session) | Scope (files/subsystem) | Status | Last synced |
|---|---|---|---|---|
| `feature/hpms-la-challenger` (main repo dir, and now Hopper's clone too) | Claude (this session) | HPMS-vs-FAF5 LA challenger experiment, `road_revised.py` LCP path | Active — this is now the single canonical branch for this work on both local and Hopper | 2026-11-10 |
| ~~`feature/county-connector-disaggregation`~~ | Resolved 2026-11-10 | Was a duplicate of the row above, committed independently on Hopper under its old pre-rename branch name | **Retired** — branch deleted (local, remote, and Hopper's checkout switched to `feature/hpms-la-challenger`). The orphaned local worktree `ResiFlow.worktrees/connector-work` still needs `git worktree remove` (blocked for an agent, run it yourself) | 2026-11-10 |
| `ResiFlow.worktrees/ponytail-code-restraint-guidance` → `viz/paper-figures` | Unclear | Registry-driven paper figure pipeline (`results/viz/figlib/`) | Underdeveloped, expected to change — leave branch open, don't merge yet | 2026-10-22 |
| `feature/anaheim-assignment-diagnostics` (worktree `.worktrees/anaheim-diagnostics`) | Claude (2026-11-10 session) | Anaheim TNTP testbed with real GeoJSON link geometry (`tests/data/anaheim_tntp/`, `parameters/testbeds/anaheim.json`, `networks/tntp.py`), then assignment-iteration logging/invariants/visual debugging for `network_flow_model` before scaling to CONUS | Active; branched from `feature/hpms-la-challenger` @ 1bf602c. Logging changes to `road_revised.py` will be additive only | 2026-11-10 |
| `feature/hpms-faf-lrs-transfer` (no worktree currently) | Claude + Cursor (co-authored) | `scripts/hpms_to_faf_lrs_transfer.py`, LRS attribute transfer | Exploratory pilot, **not** validated for production use (see `docs/HPMS_FAF_LRS_TRANSFER.md` — ~22% national match rate, 4 states at 0% match) | 2026-09-22, not touched since |
| `perf/hopper-realize-paths-streaming-fix` (no worktree currently) | Claude (earlier session) | Cascadia M9 + co-seismic landslide, Hurricane Sandy, one winter-storm event (Uri or Elliott — confirm which), Hopper PROJ/GDAL env fixes | Deliberately deferred — merge only after core model issues are resolved | 2026-09-11 |
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
