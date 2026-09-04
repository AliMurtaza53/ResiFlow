# Goal 0 — Script 1 parallel path inventory

**Branch:** `perf/numcpu-regression-diagnosis`  
**Mode under test:** Pass A (default `NIRD_BASELINE_PATH_OUTPUT_MODE`); Pass B uses `event_candidates`.

## Entry points

| Layer | Location |
|-------|----------|
| CLI | `scripts/1_network_flow_model_revision.py` — args: `num_of_chunk`, `num_of_cpu` |
| Core loop | `resiflow.road_revised.network_flow_model()` |
| LCP worker | `find_least_cost_path()` → **igraph** `Graph.get_shortest_paths(..., output="epath")` |
| Pool init | `worker_init_path(shared_network_pkl)` — unpickles graph per worker |

## What is shared vs per-worker

| Artifact | Sharing |
|----------|---------|
| igraph `network` | Pickled once per iteration (`pickle.dumps(network)`), sent to each worker via `Pool` initializer |
| DuckDB connection | **Main process only** — workers return path tuples; inserts happen in parent via `flush_flow_batch()` |
| `temp_flow_matrix_input` table | Single DuckDB table in main process — **no concurrent worker writes** |
| Streaming realization (pass 1/2) | Main process after LCP phase completes |

**Implication:** DuckDB write contention during the parallel LCP phase is **unlikely** — the regression is more likely IPC/pickle overhead, E-core scheduling, or serial post-LCP phases (streaming, od_id).

## Key environment flags

| Flag | Default (production) | Effect |
|------|----------------------|--------|
| `NIRD_OD_ID_AT_INSERT` | `1` (Patch 6) | Assign `od_id` during batch insert; skips slow `ROW_NUMBER()` pass |
| `NIRD_LCP_COLLECT_POOL_RESULTS` | off | If `1`, materialize all pool results before insert — **OOM at CONUS** |
| `NIRD_POOL_MAX_TASKS_PER_CHILD` | `0` (off) or `50` (Pass B launcher) | Recycle workers on Windows |
| `NIRD_PATH_REALIZATION_STRATEGY` | `streaming_arrays` | Post-LCP path realization |
| `NIRD_FLOW_DB_BATCH_SIZE` | `100000` | DuckDB insert batch size |
| `NIRD_SHORTEST_PATH_DEST_BATCH` | `0` (= all dests per origin) | Split igraph SP calls |
| `OMP_NUM_THREADS` / `MKL_NUM_THREADS` | `1` in CONUS launcher | Avoid BLAS oversubscription with Pool |

## Prior evidence (DAFNI-NIRD clone, Pass B, 1 iter, ~9.7M paths)

From `DAFNI-NIRD-clone/docs/passb_parallel_optimization_log.md`:

| NumCpu | Wall (s) | LCP (s) | Verdict |
|--------|----------|---------|---------|
| 1 | 2537 (prod flags) | 1048 | **Production choice** |
| 2 | 2572 | 838 | LCP −20%, wall flat |
| 4 | aborted | — | 42% LCP after ~96 min |

Production locked **NumCpu=1** because parallelism did not reduce wall time and scaled negatively at 4+ workers.

## Log markers for phase timing

Parsed by `experiments/perf_numcpu/parse_assignment_timing.py`:

- `The least-cost path flow allocation time: <sec>`
- `LCP DuckDB insert phase: <sec> seconds`
- `od_id assignment phase: <sec> seconds`
- `Streaming realization pass 1/2 complete in <sec> seconds`
- `The total simulation time: <sec>`

## Sioux Falls vs CONUS

| | Sioux Falls | CONUS smoke | CONUS full |
|--|-------------|-------------|------------|
| Nodes | 24 | FAF5 | FAF5 |
| Origins | ~24 | ~3,143 | ~3,143+ |
| Iterations (sweep) | 1 | 1–2 | unbounded |
| Purpose | Fast regression repro | Confirm clone findings | Production |
