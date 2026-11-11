# Assignment iteration dump: specification

Status: phase 1 (levels `summary` and `binding`) implemented in `src/resiflow/audit_dump.py`; see section 3a for the schemas as written. Levels `zonepair`, `full`, `od_final` and the hazard-stage dump are not implemented. Scope: additive, env-gated output from `network_flow_model` (`src/resiflow/road_revised.py`) so that results can be inspected and plotted at CONUS scale without holding per-path data in memory. Companion to `docs/ASSIGNMENT_AUDIT_LOG.md` (the `ITER_AUDIT` lines) and `scripts/diagnostics/assignment_debug_report.py` (the Anaheim reference viewer).

## 1. Goals and constraints

- Answer, for any run, per iteration: where did demand go (delivered, structurally isolated, congestion isolated, remaining), which edges bound it, and which origin-destination (OD) groups were served or lost.
- Everything is aggregated inside DuckDB where the loop already holds the data. Nothing is pulled into pandas at path or OD-pair scale except the final OD table.
- Off by default. Default numerical results must be identical with the dump on or off. A failure while dumping logs a warning and never stops the assignment (same policy as `_log_capacity_blocked_edges`).
- The viewer reads only the dump plus a network geometry file. The same viewer must run on Anaheim and on CONUS.

## 2. What the loop already holds each iteration

Verified in the code (line numbers drift; names are stable). Streaming path (`NIRD_PATH_REALIZATION_STRATEGY=streaming_arrays`, `realize_paths_streaming`):

| Data | Table or variable | Columns | Lifetime |
|---|---|---|---|
| Edge load this iteration | `temp_edge_flow` | `e_id, flow, total_candidate_flow, acc_capacity, edge_ratio` | replaced each iteration |
| OD flow assigned | `temp_od_assignment` | `origin, destination, flow` | dropped at end of iteration |
| OD adjustment ratio | `od_adjustment` | `od_id, origin, destination, adjust_r` | dropped unless `persist_debug_tables` |
| Empty-path isolation | `temp_isolated_flow_matrix` | `origin, destination, flow` | dropped right after it is folded into `isolated_od` |
| Absent-node isolation | `isolated_tmp` | `origin_node, destination_node, flow` | dropped after insert |
| Remaining demand | `remain_od` | `origin_node, destination_node, Car21` | updated each iteration |
| Edges deleted | `update_network_structure` (`mask`) | per edge | in memory only |

Legacy strategy (`legacy_compact_sql`, the code default) has `total(e_id, acc_capacity, total_flow)` and `od_adjustment` instead of `temp_edge_flow`; the edge ratio is `LEAST(acc_capacity / total_flow, 1)`. Not verified: which strategy the CONUS runs use. The handoff notes point to streaming for the large runs; the dump must support both.

Every dump hook has to run before the table it reads is dropped or replaced (the isolated tables above are the tightest).

## 3. Output layout

Directory: `$RESIFLOW_AUDIT_DUMP_DIR` (or `<baseline_out_dir>/audit_dump/` when unset and a level is requested). Parquet, one file per iteration where stated, `iter` zero-padded to 4 digits.

```
audit_dump/
  manifest.json
  edge_attrs.parquet                 written once
  iteration_summary.parquet          one row per iteration, the ITER_AUDIT fields
  edge_iter/iter=0007.parquet        binding and deleted edges only (level >= binding)
  ratio_iter/iter=0007.parquet       adjust_r distribution (level >= binding)
  zonepair_iter/iter=0007.parquet    zone-pair aggregates (level >= zonepair)
  isolated_iter/iter=0007.parquet    isolated OD pairs with kind (level >= full)
  od_final.parquet                   per OD pair, written once at the end (level >= full)
```

### Schemas

- `manifest.json`: `schema_version`, run label, git commit, initial demand, number of edges and OD pairs, strategy, all `RESIFLOW_*` and `NIRD_*` knobs in effect (including `RESIFLOW_EDGE_PRUNE_RATIO`), demand class (freight, passenger, combined), dump level, UTC start time.
- `edge_attrs.parquet`: `e_id, from_id, to_id, current_capacity, lanes, road_class_or_tier, length_mile, is_connector, state_fips` (columns that do not exist in a given network are null). No geometry; the viewer joins geometry from the network file by `e_id`.
- `iteration_summary.parquet`: `iteration, delivered, delivered_cum, isolated_structural, isolated_congestion, isolated_structural_cum, isolated_congestion_cum, remain, edges_deleted, origins_no_out_edges, iter_wall_s, requested_flow (remain at start), reachable_flow (requested minus empty-path isolation), legacy_assigned_fraction, edges_loaded, edges_binding`.
- `edge_iter`: `iteration, e_id, flow, total_candidate_flow, edge_ratio, residual_before, residual_after, deleted`. Rows only where `edge_ratio < 1` (binding) or `deleted`. Edges loaded but not binding are counted in `iteration_summary.edges_loaded`, not listed.
- `ratio_iter`: `iteration, quantile, adjust_r` for flow-weighted quantiles 0, 0.01, 0.05, 0.25, 0.5, 0.75, 1, plus `share_flow_r_lt_0.1` and `share_flow_r_lt_0.5`. This is the "tiny ratio, little progress" diagnostic.
- `zonepair_iter`: `iteration, origin_zone, destination_zone, requested, delivered, isolated_structural, isolated_congestion, remain_end`. Zone is a county or TNTP zone; a `state` roll-up (`origin_state, destination_state`) is computed at read time from a zone map, not stored per iteration.
- `isolated_iter`: `iteration, origin, destination, flow, kind` with kind in `structural`, `node_absent`, `congestion`.
- `od_final`: `origin, destination, demand, delivered, isolated_structural, isolated_congestion, remain_at_stop`. Identity per row: demand = delivered + isolated_structural + isolated_congestion + remain_at_stop.

Zone map input (needed for `zonepair_iter`): `RESIFLOW_NODE_ZONE_MAP` points to a parquet with `node, zone_id, state_fips`. For TNTP testbeds zone equals node. Not verified: where the CONUS node-to-county mapping currently lives (candidates: `src/preprocess/map_bts_od_to_network_centroids.py` and the county OD files). IDs must be coerced to string on both sides before any join (Lesson 1 in `docs/CORRECTNESS_AND_PERFORMANCE_LESSONS.md`).

## 3a. Phase 1 as implemented (schema_version 1)

Enable with `RESIFLOW_AUDIT_DUMP_DIR=<dir>`; `RESIFLOW_AUDIT_DUMP_LEVEL=summary|binding` (default `binding`). `zonepair` and `full` warn and write `binding`; any other value warns and disables the dump. If the same directory is used twice in one process (for example Script 1 then Script 4), the later call writes to `<dir>/call_NN/`. Files are written to a `.tmp` name and renamed, so a killed job never leaves a half file. Hooks run before the per-iteration tables are dropped; the dump reads, never writes, assignment state.

```
<dir>/manifest.json
<dir>/iteration_summary.parquet          rewritten each iteration
<dir>/edge_iter/iter=0007.parquet        level binding
<dir>/ratio_iter/iter=0007.parquet       level binding
<dir>/binding_od_iter/iter=0007.parquet  level binding, streaming_arrays only
```

`manifest.json`: `schema_version`, `git_commit` (from `git rev-parse`, or env `RESIFLOW_GIT_COMMIT`, else null), `started_utc`, `finished_utc`, `level`, `level_requested`, `strategy`, `strategy_capabilities`, `initial_demand`, `n_edges`, `n_od_pairs`, `env` (every `RESIFLOW_*` and `NIRD_*` variable set, minus names containing TOKEN, KEY, SECRET or PASSWORD), `edge_attribute_source_columns`, `ratio_histogram_bins`, `files` (count and bytes per directory), `iterations_written`, `iterations_completed`, `stop_reason` (`delivered_99pct`, `max_iterations`, `stagnation`, `no_remaining_flows`, `loop_condition_no_remaining_demand`), `dump_wall_s_total`, `finished`. It is rewritten every iteration, so an interrupted job still has a valid one with `finished=false`.

`iteration_summary.parquet` (one row per iteration): `iteration, delivered, delivered_cum, isolated_structural, isolated_congestion, isolated_structural_cum, isolated_congestion_cum, remain, edges_deleted, prune_applied, origins_no_out_edges, iter_wall_s, requested_flow` (remain at the start of the iteration), `legacy_assigned_fraction` (1 minus remain over initial, i.e. what the old `assigned_fraction` line prints), `edges_loaded` (edges with flow > 0), `edges_binding`, `edges_meeting_prune_rule`, `dump_wall_s` (time spent in the dump hooks this iteration, excluding the summary and manifest rewrite). `reachable_flow` from section 3 is not written.

`edge_iter/iter=NNNN.parquet`: rows only for edges with `edge_ratio < 1` (binding) or meeting the prune rule. Columns: `iteration, e_id, flow` (adjusted flow loaded this iteration), `total_candidate_flow` (all-or-nothing demand wanting the edge, before the ratio cut), `edge_ratio` (`min(acc_capacity_before / total_candidate_flow, 1)`), `acc_capacity_before` (residual before this iteration), `acc_capacity_after` (residual after loading, the value `update_network_structure` sees), `current_capacity` (original), `remaining_ratio` (`acc_capacity_after / current_capacity`), `is_binding`, `is_deleted` (the prune rule from `_edge_prune_frame`, the same function `update_network_structure` calls; on a stop iteration, `prune_applied=0` means these edges were flagged but the loop ended before deleting them), `road_name, state, county, tier, lanes, road_class` (null when the edge table has no such column), `is_connector`. Sorted deleted first, then by `total_candidate_flow` descending. This is the answer to "which edges were deleted in which iteration": filter `is_deleted`.

`ratio_iter/iter=NNNN.parquet` (long format): `iteration, metric, value, resolution, source`. Metrics: `n_od`, `flow_candidate`, `flow_adjusted` (equals `delivered` for the iteration, a cross-check), quantiles `q0, q0.01, q0.05, q0.25, q0.5, q0.75, q1` of `adjust_r` weighted by candidate flow (`q0` and `q1` exact; the others are the upper edge of a 0.001-wide bin), and `share_flow_r_lt_0.1`, `share_flow_r_lt_0.5`, `share_flow_r_lt_1` (share of candidate flow with `adjust_r` below the threshold; the last is the share of requested flow that was throttled).

`binding_od_iter/iter=NNNN.parquet` (streaming only): per edge that was the minimum-ratio edge on at least one OD path: `iteration, e_id, n_od_bound, flow_candidate, flow_adjusted, flow_lost`, sorted by `flow_lost`. Ties pick the first edge on the path.

What each strategy can supply (also in the manifest as `strategy_capabilities`): `edge_iter` and `iteration_summary` are the same for all three. `ratio_iter` comes from an inline pass in the realization loop for `streaming_arrays` and from a SQL histogram over `od_results_iter` joined to `od_adjustment` for `duckdb_chunked_compact` and `legacy_compact_sql`; both weight by candidate flow and agree to 1e-9 on Anaheim (tested). `binding_od_iter` is unavailable under the two SQL strategies (it needs an argmin over exploded paths) and is not written.

Expected size and cost at CONUS scale (not measured; the first Hopper probe should check): `edge_iter` is at most the edges loaded per iteration (about 450k rows, so under roughly 50 MB per iteration at the very worst) and should be far smaller, since only binding and deleted edges are kept (on Anaheim at 40x, 175 of 522 loaded edges were binding in iteration 1; the CONUS probe saw about 4 deleted per iteration). `ratio_iter` is 13 rows. `binding_od_iter` is at most the number of binding edges. Expect well under 100 MB over a 59-iteration run. Time: the streaming sink adds roughly a microsecond per OD pair (on the order of 10 to 20 seconds per iteration at 9.7 million ODs), the SQL histogram is one join and group-by over `od_results_iter`, and `edge_iter` is a pandas merge of about 450k rows. Anaheim measured `dump_wall_s` of 0.01 to 0.02 s on iterations of 0.15 to 0.25 s (under 10%), which is parquet fixed cost on a tiny network and says nothing about CONUS. Target to confirm: under 5% of `iter_wall_s`.

## 4. Levels and knobs

| Env var | Values | Default | Meaning |
|---|---|---|---|
| `RESIFLOW_AUDIT_DUMP_DIR` | path | unset | enables the dump |
| `RESIFLOW_AUDIT_DUMP_LEVEL` | `summary`, `binding`, `zonepair`, `full` | `binding` | each level includes the ones before it |
| `RESIFLOW_NODE_ZONE_MAP` | parquet path | unset | required for `zonepair` and above |

`summary` is the `ITER_AUDIT` fields as parquet (negligible cost). `binding` adds edge and ratio files. `zonepair` adds the aggregates. `full` adds per-OD files and is meant for testbeds and short CONUS probes.

## 5. Cost and failure policy

- Expected size is not measured. Rough bounds to check on the first probe: `edge_iter` is at most the number of edges loaded per iteration (about 450k at CONUS per the handoff, far fewer when only binding edges are kept); `zonepair_iter` is at most zones squared (state level is 49 squared; county level is millions of rows and should be a late-run option); `od_final` is one row per OD pair (a couple of million per the handoff).
- Per-iteration overhead must be reported next to `iter_wall_s` (new `dump_wall_s` field) so the cost is visible. Budget to confirm: under 5% of iteration wall time at `binding`.
- All dump code is wrapped so that an exception logs `AUDIT_DUMP warning ...` once and disables further dumping for the run.
- No change to any existing log line, table or return value.

## 6. Viewer outputs fed by each file

| File | Output |
|---|---|
| `iteration_summary` | trajectory chart; old-versus-delivered fraction; iteration table |
| `edge_iter` + `edge_attrs` + geometry | map of deleted and binding edges by iteration; binding-edge ranking with connector flag |
| `ratio_iter` | adjustment-ratio quantiles over iterations |
| `zonepair_iter` + zone map | state-to-state delivered-share matrix per iteration and final; zone-level matrix for testbeds |
| `isolated_iter`, `od_final` | structural versus congestion isolation by zone; unserved demand lists for an expert |

At CONUS scale only deleted and binding edges are drawn (plus a thinned base network), the hazard footprint is drawn from a low-resolution raster, and the matrix is state level.

## 7. Validation (Lessons 1 and 2)

1. Results identical with the dump off versus on (delivered per iteration and total edge flow) on Sioux Falls and Anaheim at 1x, 6x, 20x and 40x, plus a unit test.
2. Conservation from the dump alone: per iteration, delivered + isolated + remain equals initial demand; per OD row, the `od_final` identity above; per iteration, the sum of `zonepair_iter.delivered` equals `iteration_summary.delivered`.
3. Anaheim cross-checks against the reference viewer: `od_final.delivered` equals the `odpfc` sums; the edge flows in `edge_iter` agree with `acc_flow` changes.
4. One CONUS probe of one to two iterations at `binding` and then `zonepair`, reporting `dump_wall_s`, file sizes and peak memory, before any longer job. Any SLURM time limit needs the measured rate in its comment (Lesson 3). Nothing is submitted without approval.

## 8. Open questions

- Node-to-zone-to-state map: still open (needed only for `zonepair`). For phase 1, `edge_iter` takes `state` and `county` from the edge table if present (first match of `STATE`, `state`, `State`, `state_fips`, `STATEFIPS`, `STFIPS`, `state_abbr`; county: `county_fips`, `COUNTY`, `county`, `County`, `COUNTYFIPS`, `CTFIPS`, `CNTYFIPS`, `county_name`) and writes null otherwise; the manifest records which column was used. Question for the user: which column on the CONUS `road_links` holds state and county (the earlier probe analysis found AR, MO, OH, IA, so some mapping exists)?
- ~~Which path-realization strategy the CONUS runs use~~ Resolved, see section 8a.
- ~~`is_connector`~~ Answered: `network_connector_insertion.py` sets `assignment_tier = "centroid_connector"` on connector edges, so `edge_iter.is_connector` is `tier == "centroid_connector"`.
- ~~Hazard-stage dump~~ Specified in section 8b; cost not yet measured.
- Zone granularity retained per iteration at CONUS (state only, or county for selected states). Open, needed for `zonepair`.

## 8a. Path-realization strategy in past CONUS runs (answer to open question 2)

Read from the SLURM scripts and `notes/perf_findings/`, not from a run log, so treat as the intended setting per script:

| Where | `NIRD_PATH_REALIZATION_STRATEGY` |
|---|---|
| `experiments/pass_a_convergence/hopper/*.slurm` (all 12, incl. `submit_cpu8_convergence.slurm`) | `duckdb_chunked_compact` |
| `experiments/conus_multihazard/hopper/` earthquake 401, flood 301, Harvey 304, landslide 501, winter bigmem | `duckdb_chunked_compact` |
| same folder: Cascadia 404/502, Sandy 305, winter storm 603 | `streaming_arrays` |
| `scripts/run_conus_multihazard.py` | `setdefault("duckdb_chunked_compact")` |
| Script 1 / `road_revised.py` code default | `legacy_compact_sql` |
| `notes/perf_findings/REPORT_FOR_TOM.md` "operational lock" | `streaming_arrays`, NumCpu=1 |

Notes: `GOAL8_FULL_QUEUE_RESULTS.md` calls `duckdb_chunked_compact` a dead end (slower than `streaming_arrays`) yet the convergence SLURMs still set it, chosen there to avoid an OOM in `legacy_compact_sql`. So the tail runs we are diagnosing used `duckdb_chunked_compact`, and Stage 2's strategy comparison must include it.

Hook consequence: in both strategies the edge totals reach the loop as a pandas frame `temp_edge_flow(e_id, flow)` (`road_revised.py`, "aggregate edge flows from realized paths"), so `edge_iter` and `summary` hook there and are strategy independent. `ITER_AUDIT` reads only `remain_od` and loop counters, also strategy independent. Per-OD data (`ratio_iter`, `zonepair_iter`, `od_final`) comes from `temp_od_assignment` (streaming) or `temp_flow_matrix` (others) and needs one reader per strategy.

## 8b. Hazard-stage (Script 4) dump

Same conventions (env-gated, off by default, parquet, warn-once-and-disable). Layout: `hazard_dump/event=<id>/day=<d>/`.

- `link_state.parquet`: `e_id, original_capacity, damaged_capacity, seed_current_flow, seed_acc_flow, is_deleted`. One row per edge; about the size of `edge_attrs`, so cheap at CONUS if limited to damaged edges plus deleted edges (`level=binding`).
- `od_class.parquet`: per OD, `baseline_flow, disrupted_flow (per-OD rule), rerouted_delivered, isolated, remain`. At roughly 9.7M OD rows per day this is not cheap, so default is zone-pair aggregation (`zonepair`), full OD only for chosen events.
- Reuses `ITER_AUDIT` / `INVARIANT` lines per recovery iteration.

Purpose: make the two hazard-stage findings in `HAZARD_STAGE_CHECKS.md` (background flow dropped; per-OD rule misses partial capacity loss) visible on real events. Cost is estimated from row counts only; not measured.

## 9. Implementation phases

1. `summary` and `binding` levels in the streaming and legacy paths, with the unit tests and the off-versus-on identity check.
2. `zonepair` level with a zone map; the Anaheim viewer rewritten to read the dump instead of wrapping the loop.
3. `full` level and `od_final`.
4. CONUS probe, then the state-level matrix and deleted-edge map against real output.
