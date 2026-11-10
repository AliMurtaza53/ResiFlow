# Correctness & performance lessons — one place, so they stop recurring

This file exists because the same two bug classes have each independently cost
real compute and real debugging time **four separate times**, in four unrelated
parts of the codebase, discovered months apart by different sessions. Each time
it was fixed well locally but the lesson stayed local to that fix's commit
message or a buried `docs/PROJECT_LOG.md` entry. This doc is the standing,
searchable answer to "haven't we hit this before?" Read it before trusting a
"speedup" or writing a new node-id join, and add to it — don't bury the next
one in a commit message.

---

## Lesson 1: node/vertex identity must be resolved through an explicit map, never a bare value

**The pattern that keeps recurring:** some id (a node id, an OD endpoint) is
passed as a bare `int`/`str` into code that silently reinterprets it — as an
*array position* instead of an *identity* — with no error, just wrong answers
or pathological slowness.

Four confirmed occurrences:

1. **`classify_unassigned_demand` / connected-components lookup**
   (`scripts/analyze_assignment_diagnostics.py`, fixed 2026-10-25, commit
   `a0b9348`). `road_links` node ids are int64 in the real parquets; OD tables
   (`trip_isolations.pq`) carry them as strings. Every lookup silently
   returned `NaN`, so the function classified **100% of a 9.78M-row isolated-OD
   table** as "structurally unreachable" — implausible on a largely-connected
   national network, but nothing raised an error to say so. Fix: coerce both
   sides to `str` before building/querying the graph.
2. **igraph lookup-tax regression** (`src/resiflow/road_revised.py`, fixed
   2026-11, merged to `main` in `perf/igraph-lookup-tax-fix`). `get_shortest_paths`
   treats a bare `int` as a vertex *index* (0..vcount-1), not a vertex *name*.
   The FAF5-based network's node ids happened to coincide with igraph's
   internal indices, so this was invisible. The HPMS-challenger network's ids
   (500k/600k+) didn't coincide, so every lookup fell through to a linear
   `vs.find()` scan — a measured **~190,000x** slowdown per lookup, a **~40x**
   regression end to end, and a real 12-hour SLURM job that timed out before
   finishing. Fix: a module-level `_name_to_idx` dict, rebuilt once per network
   load instead of scanned per call.
3. **`network_od_path_estimations()`** (`src/resiflow/utils.py`) — found
   during this audit, **dead code with zero live callers**, but it called
   `graph.get_shortest_paths(source, target, ...)` directly with no resolution
   at all — the identical landmine as #2, just not yet triggered because
   nothing calls it. Fixed defensively (resolves through a `name_to_idx` map
   first) so it can't become incident #5 the day someone wires it up.
4. **`components()`** (`src/resiflow/utils.py`) — also dead code, found in
   the same audit. Built a `networkx` graph from two id columns with no dtype
   coercion between them, the same mismatch class as #1. Fixed by coercing
   both to `str` before building the graph, matching the pattern already used
   correctly elsewhere (`build_full_crosswalk()` in
   `src/preprocess/redistribute_county_od_to_subareas.py`).

**Standing rule:** any function that takes a node/vertex/edge id and either
(a) hands it to a graph library's own id-indexing call, or (b) joins/merges it
against another table's id column, must resolve it through an explicit,
tested map/coercion step first. Never assume two id columns share a dtype
just because they're "the same kind of id" — this project's real data proves
that assumption wrong on a roughly quarterly cadence. If you're adding a new
function like this, grep this file first and crib the fix pattern instead of
re-deriving it.

---

## Lesson 2: a timing win is not a correctness proof — cross-check an output metric

**The incident:** `realize_paths_streaming()` was "fixed" for a 10x speedup on
2026-08-30 (`docs/PROJECT_LOG.md`). The real cause was a DuckDB cursor-sharing
bug: `to_arrow_reader()` returns a `RecordBatchReader` tied to its originating
cursor; any other `conn.execute()` on the *same connection* while that reader
is still being iterated silently truncates it to its first batch — no
exception, no warning. The "fix" was actually introducing *more* truncation,
not less — it was caught only because someone cross-checked `assigned_fraction`
(0.047 instead of the correct 0.731) on an otherwise-identical run, not by
wall-clock timing and not by the 188-test suite (every test was toy-scale,
small enough to fit in one batch, so none exercised multi-chunk behavior).
This broken version was live on Hopper's production branch and had started
running against real winter-storm jobs before it was caught.

The igraph lookup-tax fix in this same document was validated the same
correct way: not just "job finished faster" but `Non_allocated_flow: 0.0`
confirmed after the run, i.e. demand conservation checked, not just a clock.

**Standing rule:** before calling any performance change "confirmed" at
scale, name the output metric you checked (demand-conservation total,
`assigned_fraction`, a cost total — whatever this pipeline stage's invariant
is) and show it matched the known-good baseline. "It ran in 1/10th the time"
is not evidence of correctness; it is equally consistent with "it did 1/10th
the work." This is exactly why 2-iteration comparison runs in this project
are explicitly treated as a cheap diagnostic probe, never a verdict — see
`scratch_tests/hpms_la_challenger/STATUS.md` for an example of doing this
right.

---

## Lesson 3: compute `--time`, don't guess it

Hopper SLURM jobs in the mature hazard pipeline
(`experiments/conus_multihazard/hopper/`) already do this well — every
`#SBATCH --time` carries an inline comment citing a measured prior-run
timing (e.g. "22.4% faster, 12h24m→9h37m, confirmed"). The HPMS-challenger
scratch scripts (`scratch_tests/hpms_la_challenger/submit_hpms_la_AFTER_*.slurm`)
didn't have this discipline when first written, and job `2968425` paid for it:
it hit its wall-time limit (`TIMEOUT 12:00:01`) because the time budget was a
round number, not `remaining_work × measured_rate_per_unit`. The arithmetic
to avoid this is one line: measure a short run's per-unit rate, multiply by
the full job's unit count, add a margin, and write the margin's justification
in a comment next to `--time` — the same way the mature scripts already do.

**Standing rule:** every new `#SBATCH --time` gets an inline comment with the
rate or prior-run timing it was computed from. If you can't cite one yet, run
a short probe job first rather than guessing a round number.

---

## Why this keeps happening (the actual root cause)

Lessons 1 and 2 are not independent coincidences — they're the same meta-bug
wearing two costumes: **this project has no enforced contract on what "the
same id" or "a validated speedup" means**, so each new workstream re-derives
correctness ad hoc instead of inheriting a checked invariant. Concretely:

- No shared, tested id-normalization utility — every merge/join/graph-build
  site rolls its own dtype assumption, and about a quarter of them get it
  wrong on real (as opposed to toy-test) data.
- No standing test or CI rule that a "this is now N% faster" claim must be
  paired with an output-metric diff, not just a timing number.
- Toy-scale tests (188 of them, all fitting in a single DuckDB batch) gave a
  false sense of coverage for exactly the multi-chunk behavior that broke.

None of the four incidents above were caused by a hard problem — each is a
one-line fix once found. The cost was in finding them late, at full compute
scale, instead of in a unit test or a cheap probe. If a fifth incident like
this shows up, the fix belongs here first and in the code second.
