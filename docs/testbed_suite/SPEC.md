# Testbed suite: spec and handoff (2026-11-12)

Written for the agent that will write the tests and the visualizer adapter, and for the project owner. Status of every claim is marked **verified** (read or run in this session) or **not verified**.

## 1. Purpose
Run all four hazard types (flood, earthquake, landslide, winter storm) on small networks (Sioux Falls, Anaheim) through the **same code path as the production run** (Script 2 raster intersection, Script 3 damage, Script 3 post-process, Script 4 rerouting and recovery), write the results in one fixed format, and feed that format to the figure set in place of the synthetic placeholder data. Two payoffs:
1. A sanity check on costs and flows (invariants in section 6) that real runs will also have to pass.
2. A ready pipeline: when real results exist they drop into the same bundle and the same figures.

Non-goals: no mocking of intersection or damage code; no changes to the figure layouts (frozen 2026-10-22); no real-data runs.

## 2. What exists (verified)
| Piece | Where |
|---|---|
| Testbed registry and specs | `src/resiflow/testbeds`, `parameters/testbeds/sioux_falls.json`, `parameters/testbeds/anaheim.json` |
| Synthetic hazard generators | `src/resiflow/hazards/synthetic.py`, `scripts/testbed/generate_synthetic_hazards.py` (Sioux Falls only) |
| Sioux Falls hazard fields | `flood_surface`, `flood_river`, `flood_coastal` (m depth), `earthquake` (PGA g), `landslide` (mm), `winter_storm` (mm); events `0` miss, `1` bridge bottleneck, `3` disconnect stress; EPSG:9311; see `scripts/testbed/README.md` |
| Pipeline tests | `tests/test_multihazard_pipeline_sioux_falls.py`, `tests/test_sioux_falls_pipeline_disruptions.py`, `tests/test_snow_pipeline_sioux_falls.py`, `tests/test_toy_pipeline_disruptions.py`, runner `scripts/testbed/run_multihazard_sioux_falls.py` |
| Benchmarks | `scripts/testbed/compare_mock_hazus_benchmark.py`, `tests/test_ue_vs_capconstrained_sioux_falls.py` |
| Anaheim | `tests/test_anaheim_testbed.py` (416 nodes, 914 links, 38 zones, 118 zone connectors, 104,694.4 trips). Origin: user-run UE setup, GitHub `alimurtaza53/network-analysis` (**not read by me**) |
| Aggregation fix | `src/resiflow/damage_aggregation.py` (bridges and tunnels counted once per link) and `tests/test_damage_aggregation.py` |
| Figure set (another worktree, branch `viz/paper-figures`, owner unclear, do not edit) | `C:\Users\akothaw\Desktop\ResiFlow.worktrees\ponytail-code-restraint-guidance\results\viz`: `visual_registry.csv` (44 rows, 7 in the paper set), `figlib/synthetic_model.py`, `build_advisor_review_figures.synthetic_data()` |

Paper-set rows and their current blocker (from the registry): RQ1a `s3_major_cost_panel_a_facility` (blocked_code), RQ1b `s3_major_cost_panel_b_state` (blocked_run), RQ1c `x_ranked_states_4metric` (blocked_data), RQ2a `s4_rerouting_isolation_by_mode_merged` (blocked_run), RQ2c `x_sankey_cost_flow_state` (blocked_run), RQ3a `x_rq3a_event_industry_tonnage_value` (blocked_data), RQ3b `x_top5_states_industry` (blocked_data).

## 3. Gaps
1. **No synthetic hazards for Anaheim.** The generator is Sioux Falls specific. Needs hazard fields placed on Anaheim's geometry, in its CRS, with the same four units.
2. **Asset attributes on testbed links (not verified for Anaheim).** The cost paths need `road_label` (road, bridge, tunnel), structure lengths, lanes, classes and state. Anaheim is a TNTP network, so these likely have to be assigned synthetically and labelled as such.
3. **No "state" on testbeds.** RQ1b, RQ1c, RQ2c, RQ3b are state-level. A fixed node-to-pseudo-region map is needed, clearly labelled synthetic.
4. **Pipeline tests failed on Hopper.** The failures I saw were caused by my own test job exporting `RESIFLOW_CONFIG_PATH`, which overrode the tests' toy config and loaded real CONUS demand. Do **not** export `RESIFLOW_CONFIG_PATH` or `NIRD_CONFIG_PATH` when running tests. A clean rerun at both the old and new commit was running when this was written; its result goes in section 8.
5. **Environments.** Hopper `nird` env: no `pytest` (installed separately in `/scratch/akothaw/multimodal_hazard_data/pytest_pkgs`, add to `PYTHONPATH`), no `SALib` (Morris tests error), PROJ mismatch (set `PROJ_DATA=/scratch/akothaw/conda_envs/nird/lib/python3.10/site-packages/rasterio/proj_data`). Local Windows Python: no `igraph`, so pipeline tests cannot run locally.

## 4. Design
- One runner: `scripts/testbed/run_testbed_suite.py <testbed> [--hazards ...] [--events ...] --out <dir>`; for each hazard and event it (a) generates or loads the raster, (b) runs Scripts 2, 3, 3-postprocess, 4 by their normal entry points and environment variables, (c) writes the results bundle.
- Only inputs are synthetic; intersection, damage, aggregation and rerouting are the production functions.
- Hazard set: flood surface, earthquake PGA, landslide displacement, winter storm snow depth. Events per hazard: miss (expects zero damage), bridge bottleneck, disconnect stress.
- Run both costing paths for flood: legacy workbook and sourced (`RESIFLOW_PARAM_OVERRIDES` = `experiments/conus_multihazard/hopper/overrides/sourced_asset_costs.json`).
- For the figure set, map each testbed hazard to one display event (flood to "Hurricane Harvey", earthquake to "New Madrid Earthquake", landslide to "New Madrid Landslide", winter storm to "Winter Storm Jonas") and stamp every figure "testbed, not a result".

## 5. Results bundle
Folder: `results/testbed_suite/<testbed>/<run_id>/`.
- `manifest.json`: git commit, parameter file hash, override file, hazard and event list, raster units and stats, dollar year, costing path, run time.
- One table per synthetic-model function, **with the same columns and dtypes**: `event_totals`, `facility_severity`, `direct_by_state`, `cost_by_state`, `freight_tons_value`, `value_by_state_industry`, `ranked_metrics`, plus per-link `damage_by_link` and `rerouting_summary` for the Script 1/2/3/4 diagnostic rows.
- **Adapter contract test:** for every paper-set row id, the table built from the bundle must have exactly the columns and dtypes of `figlib/synthetic_model.table(row_id)`. The adapter lives in the figure worktree (`figlib/testbed_model.py`) and is the one change needed there; ask its owner.

## 6. Sanity invariants (the cost check)
These come from the reconciliation rules in `figlib/synthetic_model.py` plus the bug found in the Harvey run.
1. Total per event = direct + 90-day indirect (rerouting plus isolation, passenger plus freight).
2. Facility-class bars sum to direct; road classes exclude bridge structures.
3. State bars sum to the event direct damage; RQ1b(B) state sum equals RQ2(B) state sum.
4. Mode bars sum to indirect cost; toll is zero.
5. **Each bridge and tunnel is counted once per link** (production totals equal the edge-level sum).
6. **Damage on an asset cannot exceed its replacement value; total damage cannot exceed total exposed replacement value** (sourced costing path). This would have caught the $500B Harvey total.
7. Monotonic: higher hazard intensity never lowers damage; the miss event gives zero damage and zero disruption.
8. Flow conservation in rerouting: delivered plus isolated equals demand.
9. Units: raster statistics within the generator's design peaks (flood m, PGA g, landslide mm, snow mm).
10. Costing paths agree in order of magnitude on the same event (legacy vs sourced) or the difference is explained in the manifest.

## 7. Ownership and workflow
- **Tests and adapter:** the other agent. Put tests in `tests/testbed_suite/`; runner in `scripts/testbed/`; outputs in `results/testbed_suite/` (gitignored).
- **This branch (`feature/anaheim-assignment-diagnostics`) carries the aggregation fix, hazard summary, and the Harvey prep.** Branch the suite from it, or from main once the diagnostics branch merges. Per AGENTS.md add a ledger row before starting. Proposed row: `testbed suite` | agent + session | `tests/testbed_suite/`, `scripts/testbed/run_testbed_suite.py`, `results/testbed_suite/` | Active | date.
- Do not edit the figure worktree except the one adapter file, and only with its owner's agreement.

## 8. Status log
- 2026-11-12: spec written. Aggregation fix and 15 aggregation tests merged to the branch (`0c646da`). Clean rerun of the pipeline tests: see the next entry.

## 9. Open decisions (owner)
1. Pseudo-regions for state-level figures on testbeds: acceptable as labelled synthetic, or leave those four figures out of the testbed bundle?
2. Anaheim asset attributes: assign synthetic bridges and tunnels, or restrict Anaheim to road-only costing?
3. Which costing path is the reference in the bundle: sourced, legacy, or both?
