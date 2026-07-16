# Goal 8 — Full queue execution: bookkeeping, seeding, strategy fix, vectorization

**Date:** 2026-07-13
**Prerequisite reading:** [GOAL7_PROFILING_AND_STRATEGY_RESULTS.md](GOAL7_PROFILING_AND_STRATEGY_RESULTS.md)

Executed the full follow-up queue from Goal 7 in one session. Summary first, detail below.

| Item | Outcome |
|---|---|
| Assigned/remain/isolated bookkeeping anomaly | **Resolved — not a bug.** Naming/semantics issue only. |
| OD sampling seed | **Not needed.** Sampling is already deterministic. |
| `duckdb_chunked_compact` `od_id` bug | Fixed, but strategy is a **dead end** — abandoned after benchmarking. |
| Event-edge nested `dict.get` loop | **Vectorized.** Biggest win of the session. |

## 1. Bookkeeping anomaly — resolved

Traced precisely via the isolation-check run's log
(`goal6_isolation_logging_check/script1_passa.log`). The apparent
inconsistency (`assigned_delta (18.44M) + total_remain (13.12M) +
non_allocated (16.77M) > initial_supply (31.56M)`) is fully explained:

- `"Post-realization assigned_iter_sum for iteration 1: 1663835.21"` — the
  **true** delivered-flow figure for that iteration.
- The **99%-assigned stop condition** (`percentage_sumod`) is computed from
  this true figure — correct, uncontaminated by isolation.
- The **`"Iteration progress: assigned_delta=..."` log line** (feeding only
  the *stagnation* guard) is computed as `previous_total_remain -
  total_remain` — i.e., the **entire reduction in `remain_od`** that
  iteration, which includes both truly-delivered flow *and* newly-isolated
  no-path flow: `1,663,835.21 + 16,772,368.12 = 18,436,203.33` — matches
  exactly.

No computation bug. `assigned_delta`/`assigned_fraction` in log output and in
`parse_assignment_log.py` is a misnomer for "remain-pool reduction," not
"flow delivered" — worth remembering when reading these logs, but not worth
a risky rename of production log strings for this investigation.

## 2. OD sampling seed — not needed

`apply_sample_od_n` ([demand/load.py:163-176](../../src/resiflow/demand/load.py#L163-L176)) selects via `od.head(cap)`
(order-preserving, deterministic) before an inner `.sample(random_state=42)`
call that can never trigger (dead code — `head(cap)` already guarantees
`len(out) <= cap`). The large run-to-run wall-time variance observed in Goal 7
(330s vs 591s for nominally the same config) is attributable to machine
contention from this session's own sequential heavy benchmark/pytest runs,
not sampling non-determinism. No fix applied.

## 3. `duckdb_chunked_compact`: fixed the reported bug, then abandoned the strategy

**Bug fixed:** `INSERT INTO od_results_iter` was missing `od_id` (9-column
table, 8 values supplied). Propagated `od_id` through `temp_flow_indexed`,
`od_results_iter`, `od_adjustment_parts`, `od_adjustment`, and the final join
(all now keyed by `(od_id, origin, destination)`, matching the working
`legacy_compact_sql`/option1 strategy's pattern). Verified: full pytest suite
still 90 passed / 3 skipped after this change.

**Then abandoned as a production candidate**, based on direct measurement:

- A **second, separate pre-existing bug** surfaced once the first was fixed:
  this strategy never builds the `temp_iteration_costs` table that
  `create_full_temp_flow_matrix=False` (the production/lightweight mode)
  requires — `Catalog Error: Table with name temp_iteration_costs does not
  exist!`. This strategy was apparently never kept in sync with that later
  optimization.
- Even where it *does* run, it is **much slower** than `streaming_arrays` at
  500k-OD scale: "DuckDB compact pass 1" alone took **13m41s**, vs.
  `streaming_arrays`'s full run of ~10-11 minutes. It also got **slower**
  going from 1→4 CPUs (1052s→1909s before crashing), not faster — the
  `CROSS JOIN UNNEST WITH ORDINALITY` approach appears to explode
  memory/row-count badly at this scale, which is exactly the problem
  `streaming_arrays` was built to avoid.

**Conclusion:** the earlier hypothesis (Goal 7) that `duckdb_chunked_compact`
would be a better, `PRAGMA threads`-friendly alternative to `streaming_arrays`
is **refuted by direct measurement**. Not pursuing further; `od_id` fix is
kept (strictly more correct than before) but the strategy remains unused in
production.

## 4. Event-edge matching loop: vectorized (the big win)

Replaced the nested Python loop in `realize_paths_streaming`
([road_revised.py](../../src/resiflow/road_revised.py), around the
per-OD-row flood/event matching block) with precomputed per-event boolean
masks and value arrays, indexed by igraph edge index:

```python
# once per call, not per row:
for event_id, edge_lookup in event_edges.items():
    mask_arr = np.zeros(edge_count, dtype=bool)
    val_arr = np.empty(edge_count, dtype=object)
    idxs = np.fromiter(edge_lookup.keys(), dtype=np.int64, count=len(edge_lookup))
    vals = np.asarray(list(edge_lookup.values()), dtype=object)
    mask_arr[idxs] = True
    val_arr[idxs] = vals
    event_damaged_mask[event_id] = mask_arr
    event_flood_link_arr[event_id] = val_arr

# per row, per event (was: nested Python loop + dict.get per edge per path):
hit_mask = event_damaged_mask[event_id][path]      # vectorized numpy fancy-index
flood_links = event_flood_link_arr[event_id][path[hit_mask]].tolist()
```

Order-preserving (boolean masking preserves array order, matching the
original's path-traversal order), and behaviorally identical including the
`if idx in event_edge_lookup` filter (now structurally guaranteed by
construction of `mask_arr`).

**No existing test covered this code path** (`event_candidates_out_dir`,
`damaged_edges_path`, `flood_links` don't appear anywhere in `tests/*.py`) —
pytest passing is not sufficient evidence of correctness here. Verified
directly instead: ran the identical 200k-OD/1-event scenario before and after
the change and diffed the output candidate parquet
(`event_disrupted_candidates/30_1/parts/candidates_part_000001.pq`):
**1590 rows, all 11 columns byte-identical** (including the `path` and
`flood_links` list-typed columns, compared element-wise), same `od_id` set.
Also cross-checked scalar outputs (remain_fraction, isolated flow, total
travel/time/fuel/toll costs) — identical to 10+ significant figures across
runs.

**Performance, `pyinstrument`-profiled, same 200k-OD/1-iteration scenario:**

| Stage | Before (this session's start) | After all 3 fixes (cap_by_eid + event-edge + PRAGMA/threshold from Goal 7) |
|---|---|---|
| `realize_paths_streaming` total | 87.1s | **14.9s** |
| `dict.get` (was 2 sites; both now gone) | 21.3s → 28.8s (2nd site) | **0s — gone entirely** |
| `network_flow_model` total | 117.5s | **35.5s** |
| Full script wall time | ~156-190s | **~43-47s** |

Roughly a **3-4x** end-to-end speedup on this profiling scenario from the two
vectorization fixes, on top of the threshold/`PRAGMA threads` fixes from
Goal 7 — with byte-identical output confirmed.

## 5. OD sampling determinism re-confirmed empirically; convergence tracking tooling added

Re-ran the Goal 6 2M-OD probe (`goal8_reconv_2m`) after the Goal 8 fixes, killed
at iteration 77 (~12.5h). `initial_supply` matched the original `goal6_probe_2m`
run to all 12 significant figures (31,556,390.201871812, both runs, a day
apart, separate processes) — strong confirmation the same OD rows were
sampled both times, consistent with the code-level check that
`apply_sample_od_n` is deterministic (`od.head(cap)`, no random branch
triggered).

**Convergence result:** deeper progress in fewer iterations —
`remain_fraction` 0.1254 at iteration 77 vs. 0.1384 at iteration 117
previously. Consistent with the edge-utilization threshold fix improving
per-iteration effectiveness, not just wall-clock.

**Wall-clock result: did not show the expected speedup, and was investigated
rather than taken at face value.** Phase-by-phase log comparison showed LCP
time alone (untouched by any Goal 7/8 fix) also roughly doubled (190s→300-375s
per iteration), which points to environmental degradation, not a code
regression — most likely sustained heavy NVMe writes from this session's
accumulated experiment output (~105GB under `experiments/*/runs/`) causing
write-cache exhaustion/throttling. Not yet re-validated in a clean
environment; flagged for a follow-up controlled run.

**Added `plot_convergence_runs.py`**: reads any set of runs' `parsed.json`
files and plots `remain_fraction` / `progress_rel` by iteration side-by-side,
plus a summary table (final remain_fraction, iteration count, total isolated
fraction, wall time). Output: `notes/perf_findings/convergence_comparison_<label>.png/.csv`.
Intended as a standard step after every future convergence run, not a one-off.

## 6. Clean before/after re-validation (Goal 9): 50k-OD smoke test is sufficient

The Goal 8 §5 wall-clock result was confounded by ~105GB of accumulated
experiment output degrading disk I/O across the board (including LCP, which
no fix touched). Cleaned up: removed all disposable `*.duckdb`,
`*.duckdb.wal`, and `*.pq`/`*.gpq`/`*.parquet` artifacts under
`experiments/*/runs/` (kept logs/JSON/CSV/PNG backing the findings docs),
reclaiming ~83GB (695GB free afterward, up from 545GB).

Re-validated with a **clean, controlled before/after** using `git stash` to
get the exact pre-fix code, running the identical 50k-OD smoke test
(`experiments/pass_a_convergence/run_smoke_direct.py`, new tool) both before
and after, in a visible terminal window (`Start-Process ... -WindowStyle
Normal -Wait`, piped through `Tee-Object` so it's both visible live and
captured to a log). Confirms **the 50k-OD smoke test is sufficient to
validate these fixes** — it was only too small for multi-iteration
convergence-policy testing (Goal 6), not for wall-clock validation.

| Phase | Before | After | Speedup |
|---|---|---|---|
| LCP | 4.80s | 2.98s | 1.6x |
| Streaming pass 1 | 5.52s | 2.84s | 1.9x |
| Streaming pass 2 | 14.41s | 3.78s | **3.8x** |
| **Total simulation time** | **49.17s** | **25.05s** | **2.0x** |

Pass 2 (where both `dict.get` hotspots lived) shows the largest individual
gain, consistent with the profiling story. This properly isolates the code
speedup from the environmental noise seen in §5.

**Tooling note:** `run_smoke_direct.py` invoked with `python -u` under
`Start-Process`'s native `-RedirectStandardOutput` triggered a low-level
CPython crash (`Fatal Python error: PyEval_SaveThread`) — a Windows-specific
interaction between unbuffered mode and that redirection method, unrelated to
this codebase. Fixed by dropping `-u` and using `... | Tee-Object -FilePath`
inside the launched shell instead, which is also what makes the window show
live output rather than silently redirecting it.

## 7. Goal 10 — NumCpu (Pool-based LCP parallelism) re-tested post-vectorization

Motivated by the question "why isn't PRAGMA threads/parallelism yielding
results" — clarified that `PRAGMA threads` only parallelizes DuckDB SQL
(pass 1/2), while LCP (`find_least_cost_path`) uses a **separate** mechanism,
Python's `multiprocessing.Pool`, controlled by `num_of_cpu`. That mechanism
hadn't been re-tested since the pass-2 vectorization shrank the pipeline's
dominant serial bottleneck, changing the Amdahl's-law ceiling on what LCP
parallelism could plausibly buy.

Re-tested `num_of_cpu ∈ {1, 2, 4}` at 500k-OD/3-iterations (clean,
sequential, visible-terminal runs, same machine state):

| num_of_cpu | Avg LCP time/iter | Total wall time |
|---|---|---|
| 1 | 49.11s | 269.72s |
| 2 | 40.20s | 236.44s |
| 4 | 40.15s | 230.99s |

**Real but modest gain from 1→2 (LCP 1.22x faster, total wall 1.14x faster),
then a hard plateau from 2→4 (no further LCP improvement at all).** This
confirms multiprocessing does help now (unlike the pre-vectorization state
where it was masked/diluted by the pass-2 bottleneck), but something caps it
at 2 workers' worth of benefit. Leading candidates, not yet isolated:

1. **Per-iteration Pool respawn overhead** — the pool is still recreated
   fresh every iteration rather than persisted across iterations; more
   workers means more spawn/IPC cost paid repeatedly, eating into the
   marginal benefit of the 3rd/4th worker.
2. **P-core/E-core scheduling** on this 20-logical-core i7 14th-gen — flagged
   as an untested hypothesis on the earlier `perf/numcpu-regression-diagnosis`
   branch and still untested here; additional workers beyond the number of
   physical performance cores may land on slower efficiency cores with little
   to no benefit.

**Next step, not yet done:** implement a persistent worker pool (create once
outside the per-iteration loop) and/or test P-core affinity pinning, then
re-run this same 1/2/4 comparison to see whether the plateau moves.

## 8. Goal 11 — Both NumCpu-plateau suspects tested with instrumentation

Added fine-grained timing (`pickle.dumps` time, `Pool()` construction/spawn
time, `imap_unordered` dispatch time — all new `logging.info` lines in
`network_flow_model`) and an opt-in P-core affinity pin
(`NIRD_WORKER_CPU_AFFINITY`, space/comma-separated logical processor ids,
applied via `psutil.Process().cpu_affinity()` inside `worker_init_path`).
Verified no regressions (pytest full suite, twice).

**Suspect #1 (per-iteration Pool respawn) — confirmed, secondary effect.**
500k-OD/3-iter, same run:

| num_of_cpu | Pool construction (spawn+init) | Dispatch |
|---|---|---|
| 2 | ~3.0-3.2s | ~33.8-34.6s |
| 4 | ~6.0-6.2s | ~32.7-33.9s |

Construction time **scales linearly with worker count** while dispatch barely
improves — the extra spawn cost at 4 workers (+3s vs 2 workers) roughly
cancels out whatever marginal dispatch gain exists. This is exactly why
2→4 CPUs plateaued in Goal 10. Real, but a few seconds per iteration —
not the dominant effect.

**Suspect #2 (P-core/E-core scheduling) — confirmed, dominant effect.**
Machine is an i7-14700 (20 physical / 28 logical: 8 P-cores×2 threads=16,
12 E-cores×1 thread=12). Ran unpinned vs. pinned-to-logical-0-15 (presumed
P-core threads) back-to-back at `num_of_cpu=4`:

| Config | Dispatch time (avg of 3 iters) |
|---|---|
| Unpinned (fresh, run immediately before) | ~57.9s |
| Pinned to cores 0-15 | ~31.8s |

**Pinning nearly halved dispatch time.** Caveat: unpinned dispatch time
itself varied a lot across the session (32.7-33.9s in one run 30 min
earlier, 56.4-60.0s in the run immediately before this test) — there is
real session-level machine variance (consistent with earlier disk/thermal
findings) independent of affinity. But pinning consistently landed at the
*good* end of that range rather than the degraded end, which is itself the
useful result: **pinning removes a source of unpredictable performance**,
not just a raw speed win. Not fully isolated from the confound with a large
enough sample size to give a precise multiplier — treat "~2x" as directional,
not exact.

**Combined implication:** P-core pinning is the higher-leverage of the two
fixes; persistent pool is a smaller, additive win on top. Both are additive
sources of the still-unresolved "why doesn't NumCpu>1 scale linearly" question
from Goal 10 — LCP parallelism has real headroom once both are addressed,
more than either fix alone would suggest.

**Verified, not just assumed:** ran the Intel Processor Identification Utility
(user-supplied) confirming i7-14700 topology (8 P-cores/16 threads, 12
E-cores/12 threads, 20/28 total) — matches the assumed 20-physical/28-logical
split exactly. Then empirically classified each of the 28 logical processors
by pinning an identical single-threaded CPU-bound workload to each one in
turn and timing it (`probe_core_speed.py`, scratch): logical cores 0-15
clustered tightly at ~0.99-1.08s, cores 16-27 clustered tightly at
~1.57-1.80s — a clean ~1.7x per-core gap, splitting exactly 16 vs 12,
matching the P/E-thread counts. **`NIRD_WORKER_CPU_AFFINITY=0-15` targets the
verified P-core threads on this machine, not an assumed convention.**

**Still not done:** `NIRD_WORKER_CPU_AFFINITY` remains opt-in (not the
production default). The persistent-pool fix itself (avoiding respawn across
iterations) has not been implemented — Goal 11 only instrumented and
diagnosed it. A repeated-trial run controlling for the session-level
variance observed would tighten the affinity-pinning wall-clock multiplier
estimate beyond the "~2x, directional" figure above.

## 9. Goal 12 — Both fixes implemented, verified, and benchmarked together

Implemented both remaining pieces:

1. **Persistent LCP worker pool** (`NIRD_PERSISTENT_LCP_POOL=1`, opt-in,
   default off): pool created once before the `while` loop in
   `network_flow_model`; each iteration pushes the updated network to
   already-running workers via a lightweight `refresh_worker_network` call
   instead of respawning. Pool closed once after the loop exits. Existing
   per-iteration `Pool()` path kept intact as the default fallback.
2. **P-core affinity as the local default**: `_build_env` (shared by all the
   local benchmark/smoke harnesses) now sets `NIRD_WORKER_CPU_AFFINITY` to
   the verified P-core threads and `NIRD_PERSISTENT_LCP_POOL=1` by default,
   with `NIRD_POOL_MAX_TASKS_PER_CHILD` disabled (0) — a nonzero value would
   recycle individual workers constantly and defeat the persistent pool's
   purpose. Documented in `Performance_note.md` as the recommended config on
   this machine.

**Verified safe:** full pytest suite (90 passed, 3 skipped) after the code
change, before any benchmarking.

**Benchmarked together** (500k-OD/3-iter, `num_of_cpu=4`):

| Metric | Baseline (unpinned, per-iter respawn) | Persistent pool + P-core pinned |
|---|---|---|
| Per-iteration pool overhead | ~6.1s (respawn) | **~0.47s (refresh)** — ~13x less |
| Avg LCP time/iteration | 40.15s | **32.6s** |
| Total wall (3 iter) | 230.99s | **203.97s** |

**Correctness confirmed, not just speed:** `remain_fraction` after each of
the 3 iterations matched the pre-change baseline to 6 decimal places
(0.329127 / 0.306619 / 0.293357, identical both runs) — the refactor changes
performance only, not the assignment result.

Combined, this closes out the NumCpu investigation from Goal 10/11: P-core
pinning was the dominant lever (as measured), persistent pool the smaller
additive one, and both are now implemented, opt-in-safe, verified correct,
and set as the local default for future benchmark runs on this machine.

## 10. Goal 13 — Micro-optimizations: sort helps marginally, chunksize doesn't, cpu=4 remains the ceiling

Implemented and benchmarked (500k-OD/3-iter) in the 2-3h window before the
overnight convergence run:

1. **Sort LCP tasks by descending destination-count before Pool dispatch**
   (longest-job-first load balancing; `NIRD_LCP_SORT_BY_DEST_COUNT`, default
   on, zero correctness risk since `imap_unordered` is already unordered).
2. **Configurable Pool chunksize** (`NIRD_LCP_POOL_CHUNKSIZE`, default 1).

| Config | Avg LCP/iter | Wall (3 iter) |
|---|---|---|
| Baseline (persistent pool + P-core pin, no sort, chunksize=1) — Goal 12 | 32.6s | 203.97s |
| + sort, chunksize=1 | 32.0s | 201.43s |
| + sort, chunksize=4 | 35.6s | 212.22s |

Sort is a small, free win (no downside — keeping it on by default). Chunksize
4 made things slightly worse, not better — reverted to default (1).

**Pushed `num_of_cpu` further: 8 regressed.** LCP avg jumped to ~40.6s
(one iteration spiked to 53.9s), worse than `num_of_cpu=4`'s ~32s. Likely
hyperthread contention once dispatch exceeds ~4 concurrent workers on this
8-P-core chip — going from 4 to 8 workers doesn't guarantee 8 distinct
physical cores. **Stopped the NumCpu scaling search here: `num_of_cpu=4`
is the empirically-best config on this machine**, not 8 or 16 as might be
assumed from the 16 available P-threads.

**Final recommended local config:** `num_of_cpu=4`,
`NIRD_WORKER_CPU_AFFINITY="0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15"`,
`NIRD_PERSISTENT_LCP_POOL=1`, `NIRD_LCP_SORT_BY_DEST_COUNT=1` (default),
`NIRD_LCP_POOL_CHUNKSIZE=1` (default).

## 11. Goal 14 — Persistent pool degrades over iterations at larger scale; reverted for long runs

Before committing to the overnight full-convergence run, built a 5M-OD sample
guaranteed to include all 45,355 OD pairs known to intersect the VA-toy
hazard (matched 100% against a pre-existing full-OD baseline run's disrupted
candidates — `build_va_priority_5m_od.py`), and validated the overnight
driver with a 2-iteration test before letting it run unbounded.

**Iteration 2 was far slower than iteration 1 (2.4x), which shouldn't
happen** — the network only shrinks each iteration, so LCP should get
cheaper, not much more expensive. Ran a controlled comparison, same 5M-OD
scale, same 2 iterations, only difference being persistent pool on/off:

| Config | Iter 1 LCP dispatch | Iter 2 LCP dispatch | Growth |
|---|---|---|---|
| Persistent pool (`NIRD_PERSISTENT_LCP_POOL=1`) | 1746s | 4165s | **+139%** |
| Standard per-iteration respawn | 1611s | 1898s | +18% |

Both configs produced identical `remain_flow` results (33,587,368.92 /
32,860,993.28) — confirming this is a performance-only issue, not a
correctness one. **The persistent pool's short-run win (Goal 12, 3
iterations, 500k-OD) does not hold at longer run lengths / larger scale** —
very likely worker-process memory fragmentation or incomplete reclamation
from repeatedly unpickling a large network into the same long-lived process
across many iterations, a problem a fresh per-iteration respawn sidesteps
entirely by construction.

**Decision: disabled `NIRD_PERSISTENT_LCP_POOL` for the overnight run and
any future long/many-iteration run.** P-core affinity pinning and task
sorting by destination-count carry no equivalent risk (no long-lived shared
state across iterations) and remain enabled. The persistent pool itself is
not deleted — kept as an opt-in flag, but the recommendation is now:
**short bounded-iteration smoke tests only, not convergence-style runs**,
until the degradation is root-caused (e.g., forcing periodic worker
recycling via `maxtasksperchild` even within the persistent-pool path would
be the natural next experiment, not attempted here given time budget).

## Goal 15: overnight run near-OOM, root cause, and fix

The first real overnight convergence attempt (`goal14_va_priority_5m_overnight`,
5M-OD VA-priority sample, all Goal 6-14 fixes applied, standard
per-iteration respawn pool) ran 9 iterations cleanly (`remain_fraction`
0.4477 → 0.4067) but per-iteration wall time grew ~4.3x (35min → 150min,
iterations 1→9) with no code path that should cause that. Checking system
memory mid-iteration-10 found the main process at **~46.6GB RSS with only
625MB of 65GB system RAM free** — killed it before an OS-level OOM/crash.

**Hypothesis 1 (DuckDB's default memory ceiling, ~80% of RAM, never
bounded via `PRAGMA memory_limit`)** — plausible on paper (no
`memory_limit` pragma existed anywhere in the codebase), so added one
(`NIRD_DUCKDB_MEMORY_LIMIT`, default 24GB) to the long-lived connection.
Validation test on the same 5M-OD sample **disproved it as the primary
cause**: RSS hit 45GB at only 17% through *iteration 1* — before the
many-iterations-of-churn this hypothesis needed. The pragma is still a
reasonable belt-and-suspenders bound and was kept.

**Hypothesis 2 (worker-count / per-worker network copies)** — disproved by
direct A/B: `num_of_cpu=2` vs `num_of_cpu=4` on a safe 500k-OD repro gave
*identical* peak RSS (~5GB both), only `num_of_cpu=2` was slower. Ruled out.

**Hypothesis 3 (per-origin destination-list size scaling with OD volume)**
— origin count is ~fixed (~2975) regardless of OD sample size, while
destinations-per-origin scales with OD volume (168 avg at 500k → ~1680 avg
at 5M), and `find_least_cost_path` bundles one origin's *entire* destination
list into a single task/result. Implemented `NIRD_LCP_DEST_CHUNK_SIZE` to
split each origin's destinations into bounded sub-tasks at construction
time (no change needed to the worker function, which already supports
arbitrary-length destination lists via the existing
`NIRD_SHORTEST_PATH_DEST_BATCH` precedent). **Also disproved**: chunking to
300 destinations/task gave *higher* peak RSS (5.92-6.07GB vs the unchunked
baseline's 5.09-5.62GB at 500k OD) and ~30% slower wall time, for no
memory benefit. Correctness was unaffected (`remain_fraction` matched the
unchunked baseline exactly across 3 iterations), but the fix itself did
nothing useful, so `NIRD_LCP_DEST_CHUNK_SIZE` was left in the codebase
disabled by default (opt-in, harmless, not used).

**Actual root cause: `NIRD_FLOW_DB_BATCH_SIZE`.** Each LCP result is
unpacked into `flow_batch`/`isolated_batch` and flushed to DuckDB as a
pandas DataFrame (path column = nested Python int lists) once the batch
reaches this threshold (default 100,000 rows). Testing batch size directly
at 500k OD, single iteration:

| `NIRD_FLOW_DB_BATCH_SIZE` | Flush cycles (500k OD) | Peak RSS |
|---|---|---|
| 1,000,000 (one flush) | 1 | **17.06 GB** |
| 100,000 (default) | 5 | ~5 GB |
| 10,000 | 50 | **2.87 GB** |

Peak memory is governed by the size of a single in-flight, unflushed batch,
not by total OD volume directly. Confirmed decoupling from OD scale: at
`NIRD_FLOW_DB_BATCH_SIZE=10000`, peak RSS was 2.87GB at 500k OD, 5.11GB at
2M OD (4x the rows, not 4x the memory), and **6.78GB at the full 5M-OD
scale** (single iteration) — an 85% reduction from the killed run's
~45GB, with massive headroom on this 65GB machine. The cost: that
iteration took 6223s (~104min) vs. the original 35min at default batch
size — smaller batches mean more flush cycles, each with fixed
DataFrame-construction/`register`/`INSERT`/`unregister` overhead.

Tuned the trade-off: `NIRD_FLOW_DB_BATCH_SIZE=50000` (100 flush cycles for
5M OD) gave **7.23GB peak RSS — barely worse than the 10k setting's
6.78GB** — but at only **3047s (~51min)**, roughly half the wall time of
the 10k setting. The memory benefit saturates well before 10,000; 50,000 is
the adopted default for the overnight run via
`NIRD_FLOW_DB_BATCH_SIZE=50000` in
`experiments/pass_a_convergence/run_overnight_va_priority.py`, alongside
the `PRAGMA memory_limit` bound and lightweight `NIRD_LOG_RSS_CHECKPOINTS`
monitoring for the run itself.

**Diagnostic tooling added** (both opt-in, zero cost when unset):
`NIRD_LOG_RSS_CHECKPOINTS=1` logs main-process RSS at 5 points per
iteration (start, args-built, post-LCP-dispatch, pre-`itter_path`,
end); `NIRD_MEM_PROFILE_TOP_TYPES=1` additionally dumps the top 15 Python
object types by shallow size at each checkpoint (useful for narrowing down
*where* memory sits, though shallow `sys.getsizeof` under-counts nested
container contents — the real signal here came from the batch-size A/B,
not the object-type dump).

Branch note: the DuckDB `memory_limit` fix and diagnostics landed on
`perf/pass-a-convergence-diagnosis`; the (ultimately disproven)
`NIRD_LCP_DEST_CHUNK_SIZE` chunked-dispatch work and the batch-size
investigation/fix live on `perf/lcp-dest-chunked-dispatch`.

## Recommendation

All four Goal 8 items resolved or fixed; two (`cap_by_eid`, event-edge
matching) delivered large, verified wins. `duckdb_chunked_compact` should
not be revisited unless someone specifically wants to invest in fixing its
second bug *and* solving its apparent memory/row-count blowup at scale —
not recommended given `streaming_arrays` is now both correct and much
faster post-vectorization. The Goal 15 memory fix
(`NIRD_FLOW_DB_BATCH_SIZE=50000` + `PRAGMA memory_limit`) removes the OOM
risk that blocked the overnight convergence run; next step is to relaunch
it and let Pass A run to convergence (or stagnation) on the real 5M-OD
VA-priority sample, which directly bears on the still-open Pass A
convergence question.
