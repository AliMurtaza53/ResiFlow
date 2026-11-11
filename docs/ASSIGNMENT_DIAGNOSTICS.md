# Assignment diagnostics: where things live and how to read them

Entry point for debugging convergence of the ResiFlow traffic assignment (Script 1) and the hazard stage (Script 4).

## Layout

| What | Where |
|---|---|
| Per-iteration log lines (`ITER_AUDIT`, `INVARIANT`) | `docs/ASSIGNMENT_AUDIT_LOG.md` (spec), emitted by `network_flow_model` into the normal job log |
| Dump of per-iteration data for CONUS (draft, not implemented) | `docs/ASSIGNMENT_DUMP_SPEC.md` |
| Hazard-stage checks and findings | `docs/HAZARD_STAGE_CHECKS.md` |
| Anaheim visual report | `scripts/diagnostics/assignment_debug_report.py` |
| Hazard-stage rule check (Anaheim) | `scripts/diagnostics/hazard_stage_rule_check.py` |
| Sioux Falls Script 1 to 4 background-flow check | `scripts/diagnostics/sioux_falls_background_flow_check.py` |
| Testbed (Anaheim TNTP + GeoJSON) | `parameters/testbeds/anaheim.json`, `tests/data/anaheim_tntp/` |

Outputs always go to a directory you pass with `--out`; nothing is written into the repo.

## How you consume it

1. **Any run (Anaheim or CONUS):** grep the job log. `grep ITER_AUDIT job.err` gives one line per iteration; `grep "INVARIANT.*ok=False"` should return nothing. Parse with `experiments/pass_a_convergence/parse_assignment_log.py` (unchanged) or load the `key=value` pairs into pandas.
2. **Anaheim, to see the mechanics:** `python scripts/diagnostics/assignment_debug_report.py anaheim --demand-scale 40 --out <dir>` writes `iteration_table.csv`, `od_delivery.csv`, `trajectory.png`, `od_matrix.png`, `network_maps.png`, `deletions_by_iter.png`. Open the PNGs; use the CSVs for numbers. Raise `--demand-scale` until the network binds.
3. **CONUS:** log lines now; the dump plus a state-level viewer once `ASSIGNMENT_DUMP_SPEC.md` is implemented. Spatial maps at CONUS need the dump's binding/deleted edges, not the full per-path data.

## What to read first in a tail

`delivered_frac_cum` flat while `isolated_congestion_cum` rises means demand is being cut off, not assigned. `delivered` is flow loaded; the older `assigned_delta` counts isolation as progress. `edges_deleted` per iteration shows the pruning heuristic at work (`RESIFLOW_EDGE_PRUNE_RATIO`, default 0.01).

## Which strategy CONUS used

See section 8a of the dump spec: mixed; the convergence runs used `duckdb_chunked_compact`.
