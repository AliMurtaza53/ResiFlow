# Runbook: integrating the new earthquake/landslide/winter-storm tables

**Progress update, 2026-09-23:** T31-T35 landed in `parameters/tables/`
(manifest updated). Landslide and earthquake-roads are now fully harmonized
-- see "Harmonization, done 2026-09-23" below. Earthquake-bridges and all of
winter storm remain open, see their sections. Branch:
`feature/paraminputs_update`.

## Harmonization, done 2026-09-23 (zero new data needed)

Found while starting Track A: `damage_level_max` (the field driving
operational closures/speed -> indirect/rerouting cost) was being set by a
"PLACEHOLDER -- confirm with advisor" categorical fragility
(`fragility/{earthquake,landslide}_categorical.py`) completely disconnected
from whatever priced direct cost -- for landslide, that placeholder's
thresholds (25-300mm) were below HAZUS's own real median for "slight"
damage (304.8mm), so closures were far more aggressive than the priced
event would ever justify.

Fixed for the two hazards that needed zero new data:
- `hazards/hazus_bridge.py` gained `road_pgd_damage_level()` and
  `bridge_pgd_damage_level_default()` -- damage-level-only wrappers around
  the exact same Table 7-5/7-7 fragility that already prices direct cost
  (verified identical to `road_direct_cost_usd`'s own level via a
  dedicated test, `test_road_pgd_damage_level_matches_road_direct_cost_usd`).
- `disruption/intensity_hazard.py`'s shared `categorical_fn` call site now
  passes `road_label` as a 3rd argument (all 3 hazards' categorical modules
  updated to accept it, `winter_storm_categorical.py` accepts-but-ignores
  for now) so bridges and roads can be classified differently.
- **Landslide**: roads -> real Table 7-5 curve, bridges -> real Table 7-7
  base-medians (no per-bridge geometry correction -- full NBI attributes
  aren't available at this call site; Script 3's actual bridge cost still
  applies the geometry-corrected version). Full fix, both asset types.
- **Earthquake roads**: placeholder removed entirely -- HAZUS publishes no
  ground-shaking fragility for roads, so "no" damage from PGA alone is the
  *correct* behavior until liquefaction PGD exists (Track A below), not a
  gap. **Earthquake bridges**: still the old placeholder -- the real Sa(1.0s)
  fragility needs a raster pass not available at this generic call site;
  using PGA as an Sa(1.0s) proxy would be a real methodological error
  (mixing intensity measures), not a documented simplification. Real
  follow-up, not done here.
- Tests: `tests/test_hazus_bridge.py` (+4), `tests/test_fragility_
  monotonicity.py` (+3, incl. explicit bridge-vs-road cases). Full existing
  suite reruns clean -- 0 regressions from this change (7 pre-existing
  failures unrelated to it, all in T04/T19 areas another session has in
  flight on this branch).

Scope: the two parameter sources the intern (Ali)
produced --
`hazus_roadway_pga_compound_lookup.csv` (earthquake, via liquefaction) and
`winter_storm_cost_and_recovery.xlsx` (winter storm) -- and what an
end-to-end "setup run" exercising each looks like. Written so this can run
as a parallel track (e.g. on Anvil, see `docs/ANVIL_SETUP.md`) alongside the
`docs/REAL_VIZ_DATA_PLAN.md` work, converging at the sensitivity-analysis
stage where both tracks meet: every new table here gets wired in the same
way T04/T05/T22 already are -- a named parameter table plus a `use_table_*`
flag, off by default until verified.

**Landslide:** no new file has been supplied yet. Current landslide
methodology (`src/resiflow/hazards/hazus_bridge.py` + `landslide_pgd.py`) is
already real HAZUS Newmark-PGD, not a shim -- so unlike earthquake and
winter storm, there's no documented $0/placeholder gap for landslide to
close right now. If a landslide-specific table is still coming, slot it into
this same pattern when it arrives; otherwise landslide's only outstanding
item is the Cascadia-paired rerun already covered in
`docs/REAL_VIZ_DATA_PLAN.md` Phase 1.

---

## Track A: Earthquake road liquefaction (`hazus_roadway_pga_compound_lookup.csv`)

### What this closes

`hazus_bridge.py`'s `compute_row_direct_damage_musd()` currently hardcodes
`if not is_bridge: return 0.0` for earthquake -- roads always report $0
direct damage for every earthquake scenario, documented as a real
methodology gap (no liquefaction PGD computed for earthquake). This table
supplies exactly that missing PGA -> liquefaction -> PGD -> damage-ratio ->
cost chain, in HAZUS's own `HRD1_major`/`HRD2_urban` tier vocabulary that
`road_direct_cost_usd()` already uses.

### Step 1 -- Formalize as a parameter table

- Add `hazus_roadway_pga_compound_lookup.csv` to `parameters/tables/` (a
  `T##` number not yet assigned -- pick the next free slot, e.g. `T30`).
- Add a `manifest.csv` row, status `SOURCED` (it's a full, gridded,
  internally-consistent HAZUS-methodology table, not a template) but flag
  the dependency below as a blocker before it's *usable*, not before it's
  *correct*.

### Step 2 -- Write the lookup module

A new small module, e.g. `src/resiflow/hazards/liquefaction.py`, mirroring
`resiflow.tables.load_table`/`interpolate`'s existing pattern:
- Input: `magnitude` (scenario-level constant -- Mineral 5.8, New Madrid
  7.5, Cascadia 9.0, all already known), `susceptibility_class` (per
  segment -- see Step 3's blocker), `pga_g` (per segment, already
  intersected for every earthquake scenario), `road_tier` (derive via the
  *same* `_MAJOR_ROAD_CLASSIFICATIONS` set `hazus_bridge.py` already uses,
  so "major"/"urban" stay one classification, not two divergent ones).
- Output: `direct_cost_usd_per_km` and a damage level (from
  `p_slight`/`p_moderate`/`p_extensive_complete`), interpolated/looked-up
  from the table.
- Nearest-grid-point lookup is probably fine given the table's fine PGA step
  (0.01g) and full magnitude/class grid -- confirm no gaps before assuming
  interpolation is even necessary.

### Step 3 -- The real blocker: liquefaction susceptibility per road segment

The table tells you the damage *given* a susceptibility class -- it doesn't
assign that class. **This project has no liquefaction susceptibility
layer today** (landslide's `n10` raster is a different, Newmark-slope-based
scheme, not interchangeable with liquefaction's VeryHigh/High/Moderate/Low/
VeryLow categories). This is the one genuinely new data-acquisition task on
this track. Options, roughly in order of effort:
1. A published national/regional liquefaction susceptibility product (state
   geological surveys publish these for CA, UT, TN/New Madrid region,
   Pacific NW -- coverage is NOT uniformly CONUS, unlike n10's national
   landslide layer). Check what actually has national coverage before
   assuming one exists.
2. A coarse proxy in the meantime (e.g. a single "Moderate" default
   nationwide, or a soil-type-derived proxy) -- explicitly labeled as a
   placeholder in the manifest, purely to unblock an end-to-end test run,
   not to be trusted as a real number.

### Step 4 -- Wire in behind a flag

`use_table_earthquake_liquefaction` (new, `vulnerability` section,
default `False`) -- same pattern as `use_table_damage_ratio_curves`. When
`True`, `compute_row_direct_damage_musd()`'s earthquake branch calls the new
liquefaction lookup for non-bridge rows instead of returning `0.0`.

### Step 5 -- The setup/validation run

1. Pick a fast, already-real earthquake scenario -- **401 (Mineral, M5.8)**
   is the smallest-footprint real earthquake already in the registry, good
   for a quick A/B.
2. Run Script 3 (damage analysis) twice for 401: once with the flag off
   (today's baseline, roads = $0), once on.
3. Diff `intersections_1_with_damage_values.csv`'s `direct_damage_mean_musd`
   for non-bridge rows -- expect nonzero values where the flag is on, zero
   where it's off (confirms the flag actually gates the new path and
   nothing else changed).
4. Sanity-check magnitude: sum road direct damage vs. the existing
   bridge-only direct damage for the same event. Road damage shouldn't
   dwarf bridge damage by orders of magnitude for a small-footprint
   moderate event like Mineral -- if it does, that's a signal the
   susceptibility-class placeholder (Step 3) is too aggressive, not
   necessarily a bug.
5. Once 401 looks sane, repeat for 403 (New Madrid) and 404 (Cascadia, once
   that scenario itself is running per `docs/REAL_VIZ_DATA_PLAN.md`).

---

## Track B: Winter storm cost + recovery (`winter_storm_cost_and_recovery.xlsx`)

### What this closes

Winter storm currently has no dedicated model on *either* side: direct cost
is still the flood-shim (confirmed 150-1000x off vs. real Jonas estimates),
and recovery falls through to the generic, hazard-agnostic `T26` table,
which gives **0 recovery days** for the "minor_moderate" bucket most snow
events land in -- so today's entire winter-storm "recovery model" is a
single static speed-penalty formula (`fragility/winter_storm_operational.py`)
applied once, nothing day-by-day after. All four sheets in this workbook are
real, sourced, winter-storm-specific replacements for both halves.

### Step 1 -- Formalize as parameter tables

Four new `T##` tables (next free slots), one per sheet:
- `cost_function` -> direct cleanup cost formula + coefficients
- `clearance_order` -> road-class clearance-priority/fleet-share model
- `clearance_schedule` -> day-of-reopening by rank x damage level x region
- `speed_recovery` -> post-reopening capacity-restoration curve

Manifest status: `SOURCED` for all four (real DOT/FHWA-cited coefficients,
not placeholders) -- but, same as Track A, usable only once Step 2's inputs
exist.

### Step 2 -- New inputs this needs that don't exist in the pipeline yet

1. **`duration_hours` and `air_temp_F` per event, per link.** The pipeline
   currently only carries `winter_storm_max_mm` (peak depth). The sheet
   cites its own sources: NOHRSC 6-hr gridded snowfall analysis (1km) for
   duration, ERA5-Land hourly 2m + NOAA nClimGrid-Daily/PRISM for
   temperature. This is a real prep-script task, same shape as
   `prepare_sandy_depths.py`/`prepare_cascadia_pga.py` -- source the
   rasters, align to the same grid `winter_storm_max_mm` already uses, per
   real event (Jonas/Uri/Elliott/Snowmageddon each need their own).
2. **Region classification** (high/moderate/low snow-plow capability, by
   mean annual snowfall: >=40in / 10-40in / <10in) per location -- a small,
   one-time NOAA climate-normals acquisition, joined to road segments by
   state or county.
3. **Winter-storm-specific damage-level thresholds.** Both recovery sheets
   take `damage_level` (minor/moderate/extensive/severe) as an input --
   once the flood-shim's thresholds are no longer the source, winter storm
   needs its own minor/moderate/extensive/severe cut points on
   depth/duration/temperature. Not in the workbook -- this is a modeling
   decision to make alongside the integration, not a data-acquisition task.

### Step 3 -- Wire in behind flags

Two new flags, same section/pattern as the rest:
- `use_table_winter_storm_cost` (replaces the flood-shim cost path in
  `scripts/3_damage_analysis.py` for `hazard_type == "winter_storm"`)
- `use_table_winter_storm_recovery` (replaces `T26`'s generic lookup with
  the clearance_order/clearance_schedule/speed_recovery chain for winter
  storm specifically)

Both default `False` until Step 2's inputs are real, not placeholders.

### Step 4 -- The setup/validation run

1. Use **601 (Jonas)** -- the best-documented real event, and the one
   already flagged (`docs/REAL_VIZ_DATA_PLAN.md`) as needing a rerun anyway
   post the winter-storm duplication-bug fix. One rerun serves both
   purposes.
2. Run Script 3 with `use_table_winter_storm_cost` off (today's flood-shim
   baseline) vs. on. Compare `combined_total_cost_usd` against the
   documented real-world Jonas damage estimate the flood-shim was checked
   against (`results/finale_2026_08/build_finale_figures.py`'s
   `WINTER_STORM_EXCLUSION` note has the reference figure) -- the new
   number should land far closer to it than the shim did, not just be
   "different."
3. Run Script 4 (rerouting/recovery) with `use_table_winter_storm_recovery`
   off vs. on. Confirm `total_recovery_days` is no longer silently 0 for a
   real Jonas-scale event, and that the recovery curve's shape (fast
   interstate reopening, slow local-road reopening, per `clearance_order`'s
   ranks) shows up in the per-road-class rerouting cost breakdown.
4. Once Jonas looks sane, repeat for Uri/Elliott/Snowmageddon (602-604) --
   these are exactly the reruns already planned for the duplication-bug
   fix, so this is the same SLURM submissions, just with the new flags on.

---

## How this fits with the parallel Anvil track

Nothing above requires Hopper specifically -- Script 3 (damage analysis) is
CPU/memory-light relative to Script 1 (Pass A) or Script 4 (rerouting) at
full CONUS OD scale, so the Track A/B validation runs (single-event Script 3
diffs) are a reasonable first thing to exercise on Anvil once
`docs/ANVIL_SETUP.md`'s environment is confirmed working -- they don't need
the full solved Pass A baseline, only the per-scenario disruption/damage
inputs already on scratch. Suggest: get Anvil's env verified with a cheap
Script 3 run on an existing scenario (e.g. re-run 401's damage analysis with
no flags changed, confirm it reproduces the known-good numbers) before
spending compute on the new-table A/B tests themselves.
