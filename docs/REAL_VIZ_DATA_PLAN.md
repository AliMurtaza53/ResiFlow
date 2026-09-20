# Plan: real data for the v3 candidate figures + additional hazard types

Written 2026-09-18. Companion to `results/viz/FIGURE_GUIDE.md` (style/format
rules) and `results/viz/v3/` (the synthetic mockup this plan replaces with
real numbers). Facts below were verified against the current codebase on
2026-09-18, not carried over from memory -- file/flag names are exact.

## Status snapshot (verified, not assumed)

- The winter-storm scenario-duplication bug is fixed in
  `src/resiflow/disruption/build.py`, but the fix comment shows it affected
  **all four** winter-storm scenarios (601/602/603/604), not just the three
  (601/602/603) confirmed earlier by direct value comparison. 604
  (Snowmageddon) needs re-verification.
- The same class of bug was found and pre-emptively fixed for landslide
  before the new Cascadia-paired landslide (502) could hit it.
- Sandy (flood, scenario 305) and Cascadia (earthquake 404 + co-seismic
  landslide 502) are fully wired into `scenario_registry.py` /
  `real_events.py` already -- not hypothetical, just not run yet.
- Passenger rerouting is a real, already-built capability that's switched
  off: `scripts/4_rerouting_and_recovery_scenario_loop.py` computes it behind
  `RESIFLOW_ENABLE_PASSENGER_REROUTING` (default `0`). That's why every real
  scenario is currently missing passenger costs.
- `scripts/compute_freight_industry_mix.py` needs
  `faf5_od_matrix_by_sctg.pq` -- which already exists locally
  (`...\soge_clusters\census_datasets\`, 2.1GB) but has never been copied to
  Hopper's scratch. A plain `scp` from the local machine, not a
  data-acquisition problem.
- Lane-miles by state and freight value by state are both derivable right
  now from data already on hand: `faf5_road_links.gpq` (length x lanes,
  grouped by `STATE`) and `faf5_county_od.pq` (has a real `value` column,
  keyed by county FIPS -> state). Only **population by state** needs a small
  external reference table.
- `compute_direct_damage_by_asset_type.py` only splits bridge vs. road
  (binary) -- needs extending to group by the real road-classification field
  for the 5-class breakdown v3's figure wants.

## Phase 1 -- Fix data integrity on Hopper (user executes; Claude has read-only access)

1. `git pull` the winter-storm/landslide fix on Hopper (already committed).
2. Re-run Script 2 -> Script 3 -> Script 4 for scenarios **601, 602, 603,
   604** (the winter-storm quartet). Confirm afterward that no two are
   byte-identical.
3. Same for **502** (Cascadia-paired landslide) once Phase 2's Cascadia PGA
   exists, to confirm the pre-emptive fix actually produced distinct output
   from 501.

## Phase 2 -- Bring the two new hazard case studies online

4. **Sandy (305, flood):** `scripts/prepare_sandy_depths.py` already has the
   PROJ/GDAL fix. Confirm the 4 state-clipped FEMA depth grids are on Hopper
   scratch, run the prep job, then Scripts 2-4 for 305.
5. **Cascadia (404, earthquake):** confirm `shake_result.hdf` and
   `n10_conus.tif` are on Hopper scratch, run `prepare_cascadia_pga.py`, then
   Scripts 2-4 for 404.
6. **Cascadia landslide (502):** depends on 404's PGA output; run once 404 is
   done.

## Phase 3 -- Turn on features that exist but are switched off

7. **Passenger costs:** re-run Script 4 for every scenario (existing + new)
   with `RESIFLOW_ENABLE_PASSENGER_REROUTING=1`. Confirm
   `lodes_passenger_od_matrix.pq` is present on Hopper scratch first (exists
   locally; `scp` over if not).
8. **Freight industry mix:** `scp` `faf5_od_matrix_by_sctg.pq` (2.1GB, run
   from the local machine, not through the Hopper wrapper) to Hopper's
   `census_datasets/`, then run `compute_freight_industry_mix.py <scenario>
   <event> --output ...` per scenario.
9. **Direct damage by road class:** extend
   `compute_direct_damage_by_asset_type.py` (or a small sibling script) to
   group by the real `road_classification`/`road_label` field instead of
   just bridge/road.

## Phase 4 -- Build the state-level denominators (Claude can do locally now)

10. **Lane-miles by state:** `groupby(STATE).sum(length * lanes)` on
    `faf5_road_links.gpq` -- no new data needed.
11. **Freight value by state:** aggregate `faf5_county_od.pq`'s `value`
    column by state FIPS (first 2 digits of county FIPS) -- no new data
    needed.
12. **Population by state:** one small public Census reference table --
    source and add as a static CSV.

## Phase 5 -- Exposure composition: real vs. genuine gap

Checked against `faf5_road_links.gpq`'s real columns:
- **Road classification, number of lanes, location (urban flag)** -- real,
  directly available.
- **Road structure (bridge/at-grade)** -- real (`road_bridge` flag); no
  tunnel flag exists, so "tunnel" either drops or folds into at-grade.
- **Carriageway type (divided/undivided)** -- not present in the FAF5
  attributes seen so far. Either drop this category for the real figure, or
  find/derive a proxy -- worth a full column-list check before deciding.
- **Damage level** -- real, from the disruption output's `damage_level_max`
  column.

## Phase 6 -- Build the real stats-extraction layer (Claude writes this)

13. New module (e.g. `results/viz/v4/real_data.py`), matching `v3/
    synth_data.py`'s table shapes (`direct_cost_by_road_class`,
    `direct_cost_by_state`, `indirect_isolation_cost`, `exposure_scale`,
    `exposure_composition`, `state_industry`,
    `ranked_states_metrics_by_type`, `damage_per_exposed_mile`), sourced from
    the real per-scenario artifacts pulled off Hopper.
14. **Open decision:** real data now has multiple events per hazard type (2
    floods, 3 earthquakes, 2 landslides, 4 winter storms) instead of v3's
    one-example-per-type mockup. Decide: one representative event per hazard
    family (mirrors v3's 4-panel structure) vs. all ~11 real scenarios side
    by side.

## Phase 7 -- Uncertainty / error bars (the honest options)

Every scenario is currently a single deterministic run -- no ensemble.
- **Near-term, defensible:** bootstrap over the contributing links/states
  behind each bar (real statistical spread, but link-level variability, not
  model/hazard uncertainty).
- **Longer-term, real:** rerun a hazard with multiple realizations (Cascadia's
  own source is a 30-realization ensemble; only the median grid is currently
  pulled through the pipeline -- the other 29 could in principle be run at
  real compute cost).
Recommendation: start with the bootstrap approach, label it accurately in
the caption.

## Phase 8 -- Wire into the notebook + QA

15. Swap `synth_data.generate_synthetic_dataset()` for the new
    `real_data.py` loader in a new `v4/` folder (v3 stays untouched, per the
    versioning rule established this session).
16. Run `FIGURE_GUIDE.md` SS5's pre-flight checklist against the real output.
17. Caption explicitly which panels are real, which carry bootstrap
    uncertainty, and which categories were dropped/proxied (carriageway
    type, tunnel) so nothing is silently overstated.

## Sequencing summary

- **Blocking on the user** (Hopper compute + 2 `scp` transfers, Claude's
  Hopper access is read-only): Phases 1-3.
- **Can proceed in parallel now:** Phase 4 (denominators), Phase 5's column
  audit, and drafting Phase 6's extraction layer against whatever real data
  already exists, ready the moment reruns land.

## Related, in progress alongside this plan

Input parameter tables T04 (fuel cost vs. speed), T05 (non-fuel operating
cost vs. speed), and T22 (flood damage-ratio curves) are being
sourced/verified for both this real-data effort and sensitivity testing. See
`docs/PARAMETER_AUDIT_CHECKLIST.md` for full status; as of 2026-09-18 all
three are wired in behind feature flags (`use_table_fuel_curve`,
`use_table_nonfuel_curve`, `use_table_damage_ratio_curves`, all default
`False`) and none currently affect model output -- the model runs on the
legacy hardcoded UK-TAG polynomial constants (T04/T05) and the real
`damage_ratio_road_flood.xlsx` workbook (T22) until each table is verified
and its flag flipped.
