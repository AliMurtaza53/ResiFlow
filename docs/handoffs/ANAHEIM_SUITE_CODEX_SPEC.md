# Anaheim all-hazards testbed suite (handoff spec for Codex)

Written 2026-11-13. Bounded mandate: build the Anaheim version of the Sioux Falls suite, run it, report, stop.

## 1. Goal
Run the production Scripts 1 to 4 on the Anaheim TNTP testbed (416 nodes, 914 links incl. 118 zone connectors, 38 zones, 104,694.4 trips) for the same 6 hazards x events 0, 1, 3, 4, 5, 6 x variants that now run on Sioux Falls, with the same inspector and the same outputs, so the results can drive the figure set and be shared.

## 2. Prior knowledge (do not re-derive)
- Sioux Falls suite: job 3708666, findings in `docs/testbed_suite/SIOUX_FALLS_SUITE_FINDINGS.md`, data in `docs/testbed_suite/results_2026-11-13/`. Plan and decisions: `docs/testbed_suite/SPEC.md` (extend existing tooling, do not write a parallel runner), `docs/ASSUMPTIONS_REGISTER.md` (T1 to T5).
- Pieces to generalise, all Sioux-specific today: `tests/sioux_falls_fixtures.py` (`write_road_links`, `write_od_matrices`, `write_study_area`, `write_hazard_raster`, `build_sioux_falls_dataset`, node ids `sf_*`, `BRIDGE_PHYSICAL_PAIRS`, the flooded pair), `tests/multihazard_sioux_falls_fixtures.py`, `scripts/testbed/generate_synthetic_hazards.py` (`_load_sioux_links`, nodes 6, 8, 10, 1, 13, 20, `testbed_synthetic_hazards.intensity_ladder`), `scripts/diagnostics/inspect_multihazard_sioux_falls.py`.
- Reusable: `src/resiflow/testbeds/` (registry, `assets.py` with `apply_synthetic_asset_attributes`, `FAF5_CLASS_BY_ROAD_CLASS`), `src/resiflow/networks/tntp.py` (`links_to_geodataframe(nodes, links, link_geometries=...)` keeps Anaheim's real polylines), `parameters/testbeds/anaheim.json` (CA, FIPS 06, urban code 51445), `tests/test_anaheim_testbed.py`.
- The default Sioux Falls build must stay byte-identical (pinned tests: `tests/test_phase0_summary_parity.py`, `tests/test_sioux_falls_pipeline_disruptions.py`, `tests/test_multihazard_pipeline_sioux_falls.py`, `tests/test_toy_pipeline_disruptions.py`). Generalise by parametrising on a testbed spec, not by editing the Sioux Falls defaults.
- Environment: Hopper `nird` env, PROJ fix, pytest in `/scratch/akothaw/multimodal_hazard_data/pytest_pkgs`; never export `RESIFLOW_CONFIG_PATH` or `NIRD_CONFIG_PATH` for tests; `git pull --ff-only` from a login shell; compute nodes have no `git` on PATH. Test job template: `experiments/common/pytest_job.slurm`; suite job: `scripts/testbed/mh_suite_all.slurm` (own checkout, not the Harvey one).
- Sourced costing only (T24/T30/Rostami). A missing attribute must fail loudly with its name.

## 3. Work
1. **Link attributes.** Assign `hpms_fclass` from TNTP free-flow speed and capacity by a written, tested rule (add it to `assets.py` with a test; register it as T2's open item). Classify zone connectors as local access. Add synthetic bridges and at least one tunnel (no testbed has a tunnel yet) on chosen links, so every hazard hits at least one bridge and the tunnel path is exercised. Label everything synthetic; never overwrite real attributes.
2. **Fixture.** An Anaheim dataset builder equivalent to `build_sioux_falls_dataset` (links with real geometry in EPSG:9311, passenger and freight OD from the TNTP trips with the testbed freight share, study area, toy config, recovery table, damage workbooks).
3. **Hazards.** Generalise the generator to take a testbed id; place events on Anaheim geometry: 0 miss, 1 bridge bottleneck (chosen bridge links), 3 disconnect stress (a corridor between two chosen non-adjacent zones), 4 low, 5 high, 6 extreme with the same ladder parameters. Same six rasters per event and the earthquake Sa(1.0 s) companion.
4. **Inspector.** Generalise `inspect_multihazard_sioux_falls.py` (rename or add `--testbed`), keep the Sioux Falls CLI working.
5. **Pseudo-regions** (register T5): a fixed node-to-region map for state-level figures, labelled synthetic, in the bundle manifest only (no pipeline change).
6. **Run** all six hazards, events 0, 1, 3, 4, 5, 6, variants `default` and `recovery_average` first (full variant set only if time allows), on Hopper, profiled.

## 4. Acceptance
- Every cell `ok`; event 0 gives zero damage and zero disruption; flood events 5 and 6 close links and populate rerouting and isolation; monotonic damage with intensity.
- Sioux Falls tests unchanged and passing.
- The sourced path runs without error on every hazard; direct cost is nonzero where bridges, roads or tunnels are hit; invariant checks from `docs/testbed_suite/SPEC.md` section 6 that can be computed from the inspector output (each bridge or tunnel counted once per link, replacement-value cap, flow conservation) are written as code, not asserted by eye.
- Report `docs/testbed_suite/ANAHEIM_SUITE_FINDINGS.md` in the format of the Sioux Falls findings (goal, method, prior knowledge, tables, then findings), result CSVs under `docs/testbed_suite/results_<date>/`.

## 5. Out of scope
The three Sioux Falls findings that need owner decisions (winter storm and the T26 schedule, earthquake never closing a link, landslide rerouting without a closure) are not to be fixed or worked around; report whether Anaheim shows the same. No edits to production scripts or parameters beyond testbed keys. The results-bundle writer and figure adapter are separate work.

## 6. Ledger row (owner edits AGENTS.md)
| `testbed/anaheim-suite` | Codex (Anaheim suite) | `tests/anaheim_fixtures.py`, `scripts/testbed/`, `src/resiflow/testbeds/`, `docs/testbed_suite/` | Active | 2026-11-13 |
