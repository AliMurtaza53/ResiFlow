# Assignment iteration dump: specification (draft, not implemented)

Status: draft for review. No code written. Scope: additive, env-gated output from `network_flow_model` (`src/resiflow/road_revised.py`) so that results can be inspected and plotted at CONUS scale without holding per-path data in memory. Companion to `docs/ASSIGNMENT_AUDIT_LOG.md` (the `ITER_AUDIT` lines) and `scripts/diagnostics/assignment_debug_report.py` (the Anaheim reference viewer).

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

- Node-to-zone-to-state map: source and keying for CONUS (see section 3).
- ~~Which path-realization strategy the CONUS runs use~~ Resolved, see section 8a.
- Whether `is_connector` can be derived from the network files or needs the connector-insertion module's output.
- ~~Hazard-stage dump~~ Specified in section 8b; cost not yet measured.
- Zone granularity retained per iteration at CONUS (state only, or county for selected states).

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
