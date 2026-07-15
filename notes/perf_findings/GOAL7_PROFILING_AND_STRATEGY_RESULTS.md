# Goal 7 — PRAGMA threads validation, strategy comparison, and profiling

**Date:** 2026-07-13
**Prerequisite reading:** [GOAL6_UPSTREAM_DRIFT_AUDIT.md](GOAL6_UPSTREAM_DRIFT_AUDIT.md), [GOAL6_TEST_RESULTS.md](GOAL6_TEST_RESULTS.md)

## Code changes applied this session

1. **Edge-utilization threshold** ([road_revised.py](../../src/resiflow/road_revised.py), `update_network_structure`): `ratio < 0.001` → `ratio < 0.01`, matching upstream `df56a1d`.
2. **`PRAGMA threads={num_of_cpu}`** on the main DuckDB connections in `network_flow_model` (`road_revised.py`) and Script 4's per-scenario-day connection, matching upstream `2a21951`.
3. **Vectorized `cap_by_eid` lookup** in `realize_paths_streaming` (see profiling below) — replaced a per-edge Python `dict.get()` list comprehension with `pandas.Series.reindex`.

All three verified against the full pytest testbed suite (90 passed, 3 skipped) both before and after — no regressions.

## 1. PRAGMA threads: real but partial win

500k-OD/3-iteration comparison, `streaming_arrays` strategy (the production default):

| NumCpu | Wall (s) |
|---|---|
| 1 | 329.7 |
| 4 | 320.6 |

The catastrophic regression is gone (previously NumCpu=4 aborted after 96+
minutes on clone data) — that alone is a meaningful, confirmed win. But this
isn't the clean scaling win the upstream-parity hypothesis predicted (~3%
faster, not a multiple). Root-caused below: the production path-realization
strategy's dominant cost is a **Python loop**, which `PRAGMA threads` cannot
parallelize (it only affects DuckDB's own query execution).

## 2. `duckdb_chunked_compact` strategy: pre-existing bug, not usable as-is

Attempted a head-to-head between `streaming_arrays` (production default, Python
loop) and `duckdb_chunked_compact` (SQL/`UNNEST`-based, would benefit from
`PRAGMA threads`). The latter fails immediately:

```
_duckdb.BinderException: Binder Error: table od_results_iter has 9 columns but 8 values were supplied
```

`od_results_iter` is declared with 9 columns (`od_id, origin, destination,
e_id, flow, fuel, time, toll, length_mile`) but the `INSERT INTO od_results_iter
SELECT ...` in the `duckdb_chunked_compact` branch never selects `od_id` —
8 values into 9 columns. This is a **pre-existing bug**, not introduced this
session, and likely explains why this strategy isn't the production default
despite (in principle) being more thread-parallelizable. Not fixed today —
flagged as a separate, small, correctness-only fix if this strategy is wanted
later; out of scope for this session's goal.

**Methodology note:** the two `streaming_arrays` wall-time samples above
(329.7s/320.6s from the PRAGMA-only test, 591.1s/520.0s from the later
strategy-comparison test, same nominal config) disagree by ~80%. The OD
sample draw isn't seeded/fixed across runs, so different runs may sample
different, non-equally-hard OD subsets. Treat single-run wall-clock deltas at
this scale as noisy; use profiled *percentage* breakdowns (below) for
before/after comparisons instead, and consider fixing the sample seed for
future benchmarking.

## 3. Profiling `realize_paths_streaming` with `pyinstrument`

Installed `pyinstrument` (sampling profiler, pure-Python, no OS-level
privileges needed — chosen over `py-spy` for that reason) and profiled a
200k-OD/1-iteration Pass A run end-to-end (`pyinstrument -r text --show-all`).

**Before fix** — `realize_paths_streaming` totaled 87.1s, broken down by
self-time of each call:

| Category | Seconds | % |
|---|---|---|
| Python loop `[self]` | 48.7 | 55.9% |
| `dict.get` | 21.3 | 24.4% |
| `gc.collect` | 5.9 | 6.8% |
| numpy math (sum/at/amin/asarray/tolist) | 6.3 | 7.3% |
| other | 4.9 | 5.6% |

The `dict.get` cost traced to [road_revised.py:1148-1150](../../src/resiflow/road_revised.py#L1148-L1150) (pre-fix): a per-network-edge Python
dict lookup (`cap_by_eid.get(eid, 0.0) for eid in edge_eid`) run once per
`realize_paths_streaming` call, over the full network edge count.

**Fix applied:** replaced with `pandas.Series.reindex` (vectorized, C-backed
lookup), `keep="last"` on duplicate `e_id` to preserve the original dict's
overwrite semantics. Confirmed in the re-profile: that specific call now costs
0.046s (down from ~21s), a ~450x reduction *for that line*.

**Second `dict.get` source found, not yet fixed:** the re-profile still shows
a large `dict.get` bucket (28.8s / 22.9%), traced to a **different, larger**
site — a nested Python loop matching each path's edges against
flood-damaged-edge lookups for event-candidate generation
([road_revised.py:1378-1391](../../src/resiflow/road_revised.py#L1378-L1391)):

```python
for idx in path.tolist():
    for event_id in edge_events.get(int(idx), []):
        ...
```

This runs **per edge, per path, per OD row** — orders of magnitude more
dict lookups than the per-edge fix above (network edge count vs. total
path-edge traversals across all OD rows). This is the larger remaining target,
but touches event-candidate/damage-matching logic directly, which is
correctness-sensitive downstream (Script 3/4 inputs) — **not attempted this
session**. Recommend a dedicated pass: precompute a boolean/array-based
damaged-edge lookup (e.g. `np.isin`) and vectorize per-row instead of nested
Python loops, with its own before/after correctness check on event-candidate
output, not just wall time.

Chart: `notes/perf_findings/goal6_profile_summary.png` (breakdown %, plus the
wall-time table above). Reproduce via
`experiments/pass_a_convergence/plot_goal6_profile_summary.py`.

## Recommendation / next steps

1. Keep the three fixes applied today (threshold, `PRAGMA threads`, `cap_by_eid`
   vectorization) — all verified safe, all directly traceable to upstream
   parity or profiling data, zero test regressions.
2. Do **not** conclude `PRAGMA threads` "solved" NumCpu scaling — it removed
   the regression but the real per-iteration cost is Python-loop-bound, not
   DuckDB-query-bound. Bigger NumCpu wins require either fixing
   `duckdb_chunked_compact`'s bug and re-benchmarking it, or vectorizing the
   event-edge matching loop (both real work, both currently pending).
3. Fix the OD-sampling seed before drawing further wall-clock conclusions —
   today's numbers have too much run-to-run variance to trust in isolation.
4. Vectorizing the event-edge matching loop (Section 3, second `dict.get`) is
   now the best-evidenced next target — larger than everything fixed today
   combined, per the profile.
