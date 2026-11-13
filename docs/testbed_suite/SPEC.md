# Testbed suite: spec and handoff (2026-11-12)

Written for the agent that will write the tests and the visualizer adapter, and for the project owner. Status of every claim is marked **verified** (read or run in this session) or **not verified**.

## 1. Purpose
Run all four hazard types (flood, earthquake, landslide, winter storm) on small networks (Sioux Falls, Anaheim) through the **same code path as the production run** (Script 2 raster intersection, Script 3 damage, Script 3 post-process, Script 4 rerouting and recovery), write the results in one fixed format, and feed that format to the figure set in place of the synthetic placeholder data. Two payoffs:
1. A sanity check on costs and flows (invariants in section 6) that real runs will also have to pass.
2. A ready pipeline: when real results exist they drop into the same bundle and the same figures.

Non-goals: no mocking of intersection or damage code; no changes to the figure layouts (frozen 2026-10-22); no real-data runs.

## 1a. Owner decisions (2026-11-12)
1. **Two testbeds: Sioux Falls and Anaheim.** Anaheim is the larger one (416 nodes, 914 links, 118 centroid connectors) and is still small enough for maps. Anaheim's GeoJSON (`tests/data/anaheim_tntp/anaheim.geojson`, `anaheim_nodes.geojson`) is already in this repo; the public repo `github.com/AliMurtaza53/network-analysis` (verified to exist; top level has `network.py`, `link.py`, `node.py`, `od.py`, `path.py`, `run_netanalysis_on.py`, `data/`, `tests/`) holds the UE network implementation that can be borrowed.
2. **State-level figures use labelled pseudo-regions** on the testbeds.
3. **Synthetic bridges and tunnels are assigned to some links, with whatever attributes make the testbed look like a FAF run** (table in section 3a).
4. **Sourced costing is the only costing path** (T24 CP25 roads, T30 bridges, Rostami tunnels). The legacy workbook path is retired. If the sourced path does not work on a testbed, that is a bug to fix, not a reason to fall back. This is itself one of the suite's checks.
5. **Every CONUS or semi-CONUS Hopper run is profiled** (per-stage wall time, peak memory, CPU efficiency). See `experiments/common/profile_stage.sh` and section 7.

## 2. What exists (verified)
| Piece | Where |
|---|---|
| Testbed registry and specs | `src/resiflow/testbeds`, `parameters/testbeds/sioux_falls.json`, `parameters/testbeds/anaheim.json` |
| Synthetic hazard generators | `src/resiflow/hazards/synthetic.py`, `scripts/testbed/generate_synthetic_hazards.py` (Sioux Falls only) |
| Sioux Falls hazard fields | `flood_surface`, `flood_river`, `flood_coastal` (m depth), `earthquake` (PGA g), `landslide` (mm), `winter_storm` (mm); events `0` miss, `1` bridge bottleneck, `3` disconnect stress, `4` low, `5` high, `6` extreme (intensity ladder, 2026-11-12); EPSG:9311; see `scripts/testbed/README.md` |
| Pipeline tests | `tests/test_multihazard_pipeline_sioux_falls.py`, `tests/test_sioux_falls_pipeline_disruptions.py`, `tests/test_toy_pipeline_disruptions.py`, runner `scripts/testbed/run_multihazard_sioux_falls.py` |
| Benchmarks | `scripts/testbed/compare_mock_hazus_benchmark.py`, `tests/test_ue_vs_capconstrained_sioux_falls.py` |
| Anaheim | `tests/test_anaheim_testbed.py` (416 nodes, 914 links, 38 zones, 118 zone connectors, 104,694.4 trips). Origin: user-run UE setup, GitHub `alimurtaza53/network-analysis` (**not read by me**) |
| Aggregation fix | `src/resiflow/damage_aggregation.py` (bridges and tunnels counted once per link) and `tests/test_damage_aggregation.py` |
| Figure set (another worktree, branch `viz/paper-figures`, owner unclear, do not edit) | `C:\Users\akothaw\Desktop\ResiFlow.worktrees\ponytail-code-restraint-guidance\results\viz`: `visual_registry.csv` (44 rows, 7 in the paper set), `figlib/synthetic_model.py`, `build_advisor_review_figures.synthetic_data()` |

Paper-set rows and their current blocker (from the registry): RQ1a `s3_major_cost_panel_a_facility` (blocked_code), RQ1b `s3_major_cost_panel_b_state` (blocked_run), RQ1c `x_ranked_states_4metric` (blocked_data), RQ2a `s4_rerouting_isolation_by_mode_merged` (blocked_run), RQ2c `x_sankey_cost_flow_state` (blocked_run), RQ3a `x_rq3a_event_industry_tonnage_value` (blocked_data), RQ3b `x_top5_states_industry` (blocked_data).

## 3. Gaps
1. **No synthetic hazards for Anaheim.** The generator is Sioux Falls specific. Needs hazard fields placed on Anaheim's geometry, in its CRS, with the same four units.
2. **Asset attributes on testbed links.** The sourced cost path needs the attributes in section 3a. TNTP networks do not carry them, so they are assigned synthetically and labelled as such. First check run on 2026-11-12: with the sourced override on, Script 3 exits with an error on Sioux Falls (details in section 8).
3. **No "state" on testbeds.** RQ1b, RQ1c, RQ2c, RQ3b are state-level. A fixed node-to-pseudo-region map is needed, clearly labelled synthetic.
4. **Pipeline tests failed on Hopper.** The failures I saw were caused by my own test job exporting `RESIFLOW_CONFIG_PATH`, which overrode the tests' toy config and loaded real CONUS demand. Do **not** export `RESIFLOW_CONFIG_PATH` or `NIRD_CONFIG_PATH` when running tests. A clean rerun at both the old and new commit was running when this was written; its result goes in section 8.
5. **Environments.** Hopper `nird` env: no `pytest` (installed separately in `/scratch/akothaw/multimodal_hazard_data/pytest_pkgs`, add to `PYTHONPATH`), no `SALib` (Morris tests error), PROJ mismatch (set `PROJ_DATA=/scratch/akothaw/conda_envs/nird/lib/python3.10/site-packages/rasterio/proj_data`). Local Windows Python: no `igraph`, so pipeline tests cannot run locally.

### 3a. Link attributes the sourced path reads (verified by reading `scripts/3_damage_analysis.py` and the cost modules)
| Asset (`road_label`) | Required columns | Notes |
|---|---|---|
| all | `e_id`, `length` (m), `lanes`, `road_classification`, `trunk_road`, `form_of_way`, `urban`, flood depth columns from Script 2 | `urban_code` (Census urban area) is turned into `hpms_urban_size_tier` before costing |
| road | `hpms_fclass`, `urban`, `hpms_urban_size_tier` | T24 CP25 $/lane-mile join; roads are priced per raster-cell piece |
| bridge | `bridge_state` (FIPS) or `STATE`, `nhs_designation` (non-null means on the NHS), `averageWidth` (m), `structure_length_m`, `main_unit_spans` | T30 $/ft2 by state and NHS class, times deck area, times a HAZUS damage-state ratio; the whole-structure value is repeated on every piece (counted once per link) |
| tunnel | `tunnel_bores`, `tunnel_length_m`, `tunnel_length_m_min`, `tunnel_lanes_total`, `tunnel_roadway_width_m` | Rostami construction value times a HAZUS tunnel ratio |
State must be a real US state because T30 is keyed by state: Sioux Falls = South Dakota (FIPS 46), Anaheim = California (FIPS 06). `hpms_fclass` has to be derived from the TNTP link attributes by a stated rule, and `urban_code` set to the Census urban area for the testbed's city (look up in `parameters/tables/T39_census_urban_area_population_2010.csv`).

## 4. Design
- **Extend, do not replace (corrected 2026-11-13; an earlier draft said to build a new runner, which would have duplicated existing tooling).** The Sioux Falls pieces already exist: `scripts/testbed/generate_synthetic_hazards.py`, `tests/multihazard_sioux_falls_fixtures.py`, and `scripts/diagnostics/inspect_multihazard_sioux_falls.py` (runs Scripts 1, 2, 3, 4 per hazard, event and variant; Hopper job `scripts/testbed/mh_suite_all.slurm`). The Anaheim work is to generalise these to take a testbed id, not to write a parallel runner. The results bundle writer and self-check (section 5, 6) are the genuinely new parts.
- Only inputs are synthetic; intersection, damage, aggregation and rerouting are the production functions.
- Hazard set: flood surface, earthquake PGA, landslide displacement, winter storm snow depth. Events per hazard: miss (expects zero damage), bridge bottleneck, disconnect stress.
- Costing: sourced path only. During the transition run with `RESIFLOW_PARAM_OVERRIDES` = `experiments/conus_multihazard/hopper/overrides/sourced_asset_costs.json`; the end state is that `vulnerability.use_sourced_asset_costs` defaults to true and the legacy branch is removed.
- Anaheim hazards: generalise `generate_synthetic_hazards.py` to take a testbed, place hazard fields on Anaheim's geometry in EPSG:9311, and assign synthetic bridges and tunnels to chosen links (for example the corridor links crossing the hazard) so each hazard hits at least one bridge.
- For the figure set, map each testbed hazard to one display event (flood to "Hurricane Harvey", earthquake to "New Madrid Earthquake", landslide to "New Madrid Landslide", winter storm to "Winter Storm Jonas") and stamp every figure "testbed, not a result".

### 4a. Coverage target (owner request 2026-11-12: the whole spectrum, so the typical result tables populate)
What has been checked so far is **one cell**: Sioux Falls, flood, event 1, where both flooded links happen to be bridges. Direct damage on roads, tunnels and every other hazard is **not verified** on the sourced path.

| Dimension | Target | Status (2026-11-12) |
|---|---|---|
| Hazards | flood surface, flood river, flood coastal, earthquake, landslide, winter storm | Sioux Falls generator and a pytest per hazard exist (`tests/test_multihazard_pipeline_sioux_falls.py`); costs and result tables per hazard **not inspected** |
| Direct cost path per hazard | flood: sourced (T24/T30/Rostami); earthquake and landslide: HAZUS bridges (earthquake road damage is zero by design); winter storm: T32 cost function | flood verified on bridges only |
| Assets hit | road, bridge, tunnel in every hazard that prices them | bridges only so far; no tunnels on any testbed yet |
| Events | miss (zero everything), bridge bottleneck, disconnect stress (isolation) | event 1 only run on the sourced path; event 3 not run |
| Indirect | rerouting by mode (operating, time, toll) for passenger and freight; isolation; 90-day recovery | rerouting verified on event 1 (freight $995.56, passenger $11,061.78); isolation zero there; horizon and components not checked |
| Interactions | see below | only the earthquake-to-landslide chain exists |
| Freight detail | commodity mix, tonnage and value by industry (RQ3 figures) | testbeds have no commodity breakdown; needs a synthetic mix |
| Regions | pseudo-regions for state-level figures | not built |

**Hazard interactions.** The only interaction the code has today is landslide displacement computed from earthquake shaking (`compute_landslide_pgd.py`, Newmark). Nothing evaluates simultaneous or sequential hazards on one network, and flood surface, river and coastal run as separate scenarios. Proposed interaction cases for the testbeds (owner to confirm): (1) earthquake followed by co-seismic landslide on the same links; (2) compound flood: surface plus river plus coastal fields on one event; (3) earthquake then flood on the already damaged network (sequential, damage state carried over), which needs new code. Cases 1 and 2 use existing pieces; case 3 does not.

### 4b. Requirements for sharing the module
Someone without Hopper access must be able to run it:
1. One command (`python scripts/testbed/run_testbed_suite.py --testbed all --out <dir>`), no CONUS data and no cluster paths.
2. A pinned environment (`environment.yml` exists at the repo root; **not verified that it builds**) including `igraph` and `snail`, which the local Windows Python lacked.
3. Everything the run needs lives in the repo (`tests/data`, `parameters/testbeds`), and the run writes only under `--out`.
4. A README with expected runtime, the expected results (pinned baselines with tolerances) and how to read the manifest.
5. A self-check at the end that runs the invariants in section 6 and prints PASS or the failing invariant by name.
6. Do not export `RESIFLOW_CONFIG_PATH` or `NIRD_CONFIG_PATH` in the user's shell (they override the testbed config and load real data).

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
10. The sourced path runs without error on both testbeds for all four hazards; a missing attribute fails loudly with its name (no silent zeros).

## 7. Ownership and workflow
- **Tests and adapter:** the other agent. Put tests in `tests/testbed_suite/`; runner in `scripts/testbed/`; outputs in `results/testbed_suite/` (gitignored).
- **This branch (`feature/anaheim-assignment-diagnostics`) carries the aggregation fix, hazard summary, and the Harvey prep.** Branch the suite from it, or from main once the diagnostics branch merges. Per AGENTS.md add a ledger row before starting. Proposed row: `testbed suite` | agent + session | `tests/testbed_suite/`, `scripts/testbed/run_testbed_suite.py`, `results/testbed_suite/` | Active | date.
- Do not edit the figure worktree except the one adapter file, and only with its owner's agreement.
- Profiling: any run at CONUS or semi-CONUS scale on Hopper or Anvil sources `experiments/common/profile_stage.sh` (`profile_init`, `profile_stage <label> <cmd>`, `profile_finish`) and is read with `scripts/diagnostics/summarize_hopper_profiles.py`. The testbeds are small, so a plain `sacct` line is enough for them.

## 8. Status log
- 2026-11-12 to 13 (Claude): fixed Script 3 per-directory pricing and the consolidated-cost zeroing; coastal flood now priced; earthquake gets an Sa(1.0 s) companion; testbed links get a synthetic `faf5_class` (winter T33/T34); legacy `snow` removed; embankment unit bug fixed; geodesic length check added. Test run at `1fd3b71`: 39 passed.
- 2026-11-13: intensity ladder (events 4, 5, 6 per hazard) and time-dependent variants (T26 fast/average/slow, winter region high/low) added to the generator and inspector; Hopper suite job 3708666 submitted. Observed on Sioux Falls before the ladder: closures and rerouting only for flood; earthquake, landslide and winter storm slowed links but never closed one (winter peak 120 mm is below the 254 mm closure point).
- 2026-11-12: spec written. Aggregation fix and 15 aggregation tests merged to the branch (`0c646da`). Clean rerun of the pipeline tests: see the next entry.

## 9. Decisions
Resolved 2026-11-12: pseudo-regions allowed; synthetic bridges and tunnels assigned; sourced costing only (see section 1a).
Still open: how `hpms_fclass` is derived from TNTP free-flow speed and capacity (the rule must be written down and tested); whether the legacy cost code is deleted in the same change that flips the default, or one change later.
