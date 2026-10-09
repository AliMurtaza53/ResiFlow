# Flood tables and parameters: review and FAF harmonization

Scope: every table, JSON, workbook and parameter the **flood** path reads, what it does in the model, its
current status, and what must be fixed or confirmed. Written 2026-09-26 from the code and data as they are
today; nothing here has been changed. Companion to `parameter_diff_final.xlsx` (the audit matrix; row
numbers cited as "audit #n") and `parameters/tables/manifest.csv`.

Legend: **FIX** = clear defect, **CONFIRM** = needs your decision or a source check, **NOTE** = context.

---

## Resolved + audit, 2026-10-09: T35 wired; fuel-only cost bug fixed; all 4 hazards x 3 costs reviewed

### T35 wired (winter storm residual speed)

T35 is winter storm's equivalent of T37/T38 (earthquake/landslide residual
speed) and T27 (flood residual speed) -- the piece that turns "when does a
closed link become passable again, and how fast" into a day-by-day speed
cap in Script 4. It was sitting unwired (confirmed in yesterday's audit).

- Fixed T35's own CSV first: a quoted comment line and an unquoted trailing
  "formula note" row were both corrupting its own parse (the same recurring
  CSV-quoting bug as T08b/T20/T27 before it) -- confirmed via direct
  `pd.read_csv`, same as those earlier fixes.
- New `resiflow.hazards.winter_storm_clearance.residual_speed_factor_winter_storm()`:
  turns T34's real `day_open` (already computed at disruption-build time by
  `add_clearance_columns()` -- this part was already wired) plus the
  current `event_day` into a per-link speed factor from T35's real
  FHWA-sourced post-plow recovery curve. Major/minor uses this project's
  one canonical split (`hpms_fclass.damage_threshold_major_from_fclass`,
  F1-F3 major) for consistency with flood/T20, rather than inventing a
  winter-storm-specific one (T33 has no literal "road_class" column
  despite T35's own header comment implying one).
- Wired into Script 4 as a new `elif _hazard == "winter_storm"` branch,
  parallel to the existing earthquake/landslide (T37/T38) and flood (T27)
  branches -- **replacing** the flood-shim depth gates winter_storm was
  silently falling through to before (T27's depth thresholds on a fake
  "flood_depth_max" repackaged from snow/ice depth -- a real, pre-existing
  gap, now closed for this half of winter storm's model; Script 3's
  *damage*-cost shim for winter storm is separate and still open, see
  below).

### Real bug found and fixed: "fuel" cost wasn't fuel-only

While confirming the "track time, fuel, tolls" requirement, found that
`road_revised.compute_costs_for_links()` -- the one function all operating
cost in this project runs through, baseline and every hazard's rerouting
alike -- was **always** adding a real, nonzero non-fuel operating cost
(`cons.NON_FUEL_PENCE_PER_KM`, e.g. for a car: `(8.74 + 239.77/v_kmph)/100`
USD/km) on top of fuel, regardless of `use_table_nonfuel_curve`. That flag
was only ever supposed to choose non-fuel cost's *source* (table vs.
formula) -- there was no path that actually produced zero non-fuel cost --
directly contradicting this project's own documented Wave-1 scope
("Li-like constant **fuel-only**"; "no non-fuel VOC" -- manifest.csv's T04/
T05 rows and unified_parameters.json's own `cost_operating` comment). At a
typical 60 km/h for a car, this hardcoded non-fuel term (~$0.127/km) was
*larger* than the fuel cost itself (~$0.087/km) -- silently more than
doubling "operating cost" everywhere in the model.

Fixed: `use_table_nonfuel_curve=false` (the default) now means what it
always should have -- fuel-only, non-fuel cost is exactly 0. The table-based
opt-in path is unchanged and still available if ever switched on. This
changes real $ outputs project-wide (baseline flows and every hazard's
rerouting cost all run through this one function) -- re-derived and
updated the toy pipeline tests' own hardcoded expected-cost constants
against the corrected values rather than leaving them stale.

### All 4 hazard types x 3 costs (damage, rerouting, isolation): reviewed

| Hazard | Damage cost | Rerouting cost (speed/capacity input) | Isolation cost |
|---|---|---|---|
| Flood | REAL -- `damage_ratio_road_flood.xlsx`/`damage_cost_road_flood.xlsx` (default), or T22/T24 CP25/T30/Rostami tunnel (NHCCI-harmonized, behind `use_sourced_asset_costs`, off by default) | REAL -- T19 (speed-depth) + T27 (residual speed, now table-driven) + T26 (capacity recovery; data-bundle default on, bridge/road-split table off by default) | REAL |
| Earthquake | REAL -- HAZUS 6.1 Sa(1.0s)/PGD via `hazus_bridge.py` for bridges; T31 liquefaction-PGD for roads, but **regional-only** (8 CUSEC states -- pre-existing, documented limitation, not new) | REAL -- T37 (residual speed) + T36 (day-1 operational factor) + T26 | REAL |
| Landslide | REAL -- HAZUS PGD via `hazus_bridge.py`, bridges and roads both | REAL -- T38 + T36 + T26 | REAL |
| Winter storm | **SHIM** -- `use_table_winter_storm_cost` defaults false, so damage still prices via the flood-shim (ice/snow depth repackaged as a fake flood depth; previously confirmed 150-1000x off real estimates). T32's real DOT-regression cost model exists, tested, and is ready -- same "available, not yet the default" pattern as every other real-table swap this project has made | **REAL as of today** -- T33 (clearance rank) + T34 (day_open) + T35 (now wired) | REAL |

Rerouting cost's three tracked components (time/fuel/toll) are computed by
one shared, hazard-agnostic function (`network_flow_model()` ->
`compute_costs_for_links()`), so the fuel-only fix above and the "three
components tracked, saved as separate columns" confirmation below both
apply uniformly to all four hazards, not just flood:
`rerouting_cost_{mode}_s{scenario}_day{event_day}.csv` already carries
`rer_time`, `rer_operate` (now fuel-only), and `rer_toll` as separate
columns alongside the combined `rerouting_cost` -- this was already true
before today, just verified. Isolation cost (`isolation_usd_per_day` x
VOT) is computed the same single, hazard-agnostic way for all four --
confirmed via code search that `hazard_type` is referenced exactly once in
the whole of Script 4 (the speed/capacity branch above), nowhere near the
isolation-cost computation.

**Urgent, found while wiring T35 -- `HEAD` is currently broken for
winter_storm:** the already-committed `disruption/build.py` imports
`resiflow.fragility.winter_storm_speed` and
`resiflow.hazards.winter_storm_rate` -- neither has ever been committed
(confirmed via `git ls-files`; both are untracked in the working tree,
alongside a committed-but-now-deleted `winter_storm_operational.py` that
`winter_storm_speed.py` appears to replace). A fresh clone of this branch
cannot run the winter_storm disruption path at all -- `ModuleNotFoundError`
on import. This isn't something today's work caused; it's concurrent
in-progress work on this same branch that hasn't been committed yet.
`winter_storm_clearance.py` (this section's own T35 work, also previously
untracked) is committed alongside today's changes since Script 4 now
depends on it directly and it's complete/tested; the other two files are
left for whoever is mid-refactor on them to commit, or **CONFIRM** you
want me to commit them as-is.

**Still open:** winter storm's damage-cost shim (flag exists, default
off -- a decision for you, same as every other such flag); T31's
regional-only earthquake road liquefaction coverage (pre-existing,
documented, not addressed today).

---

## Audit, 2026-10-08 (3): all parameter JSONs + every table under parameters/tables/

Project-wide, not flood-only (this doc's own scope line above is the
flood path specifically; this pass checked everything).

### Parameter JSONs: consistency check

Read all 8: `unified_parameters.json`, `assignment_profiles.json`,
`network_mapping.{faf5,osm,tntp}.json`, `hazards.example.json`,
`hazards.conus_multihazard.example.json`, `sa_morris_design.json`.

- **`network_mapping.{faf5,osm,tntp}.json`, `hazards*.json`,
  `sa_morris_design.json`:** consistent, nothing to fix. `network_mapping.faf5.json`
  in particular is now correctly understood as a *fallback-only* source
  (today's `normalize_network_links()` fix means FAF5's real per-link
  tiers win whenever present; this file only fills the gaps) --
  confirmed compatible, no content change needed.
- **`assignment_profiles.json`:** consistent with the T08 sync decision
  logged earlier today.
- **`unified_parameters.json` -- 3 dangling table-name references found**
  (a parameter names a file that isn't at the path it names, because the
  file has since been archived). All three flags default `false`, so none
  are *actively* broken today, but each would fail loudly
  (`FileNotFoundError`) if switched on without also updating the name --
  documented inline at each one rather than silently left as a trap:
  1. `cost_operating.fuel_curve_table` -> `T04_fuel_consumption_speed_UK_TAG_current`
     (now `archive/...`). Pre-existing, not something this session did;
     T05 non-fuel is already `OUT_OF_SCOPE` by design and this flag
     should never be flipped on regardless.
  2. `cost_operating.nonfuel_curve_table` -> `T05_nonfuel_cost_speed_UK_TAG_current`
     (now `archive/...`). Same as above.
  3. `vulnerability.damage_threshold_table` -> `T20_damage_level_depth_thresholds`.
     This one **was actively broken**: the file had been deleted from
     `parameters/tables/` (by concurrent work on this branch) three
     separate times across today's sessions. Restored again and flagged
     inline in the JSON with the exact restore command, since it's the
     *default* table (used by `use_table_damage_thresholds`, not a
     secondary candidate) and needs to keep existing.
  4. (Already known, logged 2026-10-08 earlier today, not new:)
     `vulnerability.damage_ratio_curves_table` -> the archived T22
     TEMPLATE -- accepted, safer-failure-mode, not fixed further.
- **`manifest.csv` had gone stale in one place**: its own note on
  `T26_recovery_design_current.csv` claimed `recovery.use_table_recovery_design`
  now defaults `true` -- true only briefly, before being reverted later
  the same day once it broke E2E tests (see the entry above). Corrected.

### Every table under `parameters/tables/`: wiring audit

Checked every file directly under `parameters/tables/` (34 before this
pass) plus `archive/`, `updates_ak/`, `nandu_sep2026/`, `raw/` against
real code references (not just docstring mentions -- confirmed an actual
`load_table(...)` / `Path(tables_root())/...` read in each case), and
against `manifest.csv`'s own status labels.

**Newly confirmed wired** (had no manifest row, or a wrong one, until now):
`T19_alt_snowfall_rate_speed_capacity.csv` (`hazards/winter_storm_rate.py`),
`T19_winter_speed_closure_crosswalk.csv` (`fragility/winter_storm_speed.py`),
`T33_winter_storm_clearance_order_new.csv` (`hazards/winter_storm_clearance.py`
-- the manifest had been describing the *old*, now-superseded
`T33_winter_storm_clearance_order.csv` by the same conceptual name; the
real live file has a `_new` suffix the manifest never recorded).

**Confirmed NOT loaded, by design (not neglect) -- left in place, manifest
now says so explicitly:**
`T04_avg_fuel_VOC_sealed.csv` (documents what the live hardcoded fuel-cost
formula coefficients resolve to), `T32_ice_event_assumption_note.csv`
(`winter_storm_categorical.py`'s own docstring: "documentation of that
choice, not a separate code path"), `T36_damage_state_operational_factors_inventory.csv`
(research ledger; already documented this way).

**Confirmed NOT loaded, genuinely unwired (not documentation-by-design):**
`T35_winter_storm_speed_recovery.csv` -- zero code references anywhere;
manifest already said "directly usable once T34 supplies day_open" (i.e.
known-pending), now says so more explicitly. Left in place, not archived
-- it's a real near-term dependency of in-progress work (T34), not dead.

**Moved to `archive/`** (confirmed superseded, zero remaining code
references, each with a note at its new manifest row explaining why):
- `T24_asset_unit_costs_US_candidate.csv` -- superseded by
  `T24_asset_unit_costs_US_candidate_CP25.csv` (2026-10-05 work).
- `T22_damage_ratio_curves_updated.csv` -- already manifest-flagged
  `ARCHIVED_REJECTED` (incomplete reshape attempt) but still sitting at
  top level; physically relocated to match its documented status.
- `damage_cost_road_flood_US.xlsx` -- untracked; the same
  Interstate/US Route/State Route/Local figures already documented (and
  superseded) in this doc's own "T24 unit costs" table above, under a new
  filename.
- `NewT0_updated.xlsx` -- untracked; a VOT/fuel citation source referenced
  only in a comment in `scripts/seal_t04_emfac_fuel_voc.py`, never loaded.

**Flagged, not moved** (genuine ambiguity -- these sit in personal/named
staging areas or look like in-progress renames, and moving them risked
disrupting someone else's active work rather than cleaning up dead
weight):
- `T20_damage_level_depth_thresholds_US.csv` -- byte-identical duplicate
  of `T20_damage_level_depth_thresholds_US_candidate.csv` under a shorter
  name, untracked, no code reference. **CONFIRM** intent and consolidate
  to one filename.
- `parameters/tables/updates_ak/` (4 files) -- a personal staging folder;
  its `T24_asset_unit_costs_US_candidate_CP25.csv` and
  `T30_bridge_replacement_unit_costs_US.csv` are byte-identical to the
  already-promoted top-level copies (redundant, safe to delete at your
  discretion); `T22_damage_ratio_curves_US_candidate.csv` is now moot
  given the permanent decision to stay on the xlsx for T22;
  `T04_EMFAC2025_CA_fuel_speed_SUV_SUtruck.csv` not independently checked.
- `parameters/tables/nandu_sep2026/` (4 files, incl. `parameter_diff_final.xlsx`
  -- the audit matrix this doc itself cites) -- a named collaborator
  staging folder; not touched.

**Every `use_table_*`/`use_sourced_*` flag in `unified_parameters.json`
confirmed referenced by real code** (none orphaned/dead).

---

## Resolved, 2026-10-08: Section 4 items 5/6/7/9/14, T08/T26/T27 confirmed, NHCCI dollar-year harmonization

Per your explicit decisions this round.

**Item 5 (T22 TEMPLATE):** Archived by you (`archive/T22_damage_ratio_curves_TEMPLATE.csv`).
`damage_ratio_road_flood.xlsx` is confirmed the permanent, final T22 source
-- not a placeholder pending replacement. No upstream code change was
needed (the xlsx was already the hard default; `use_table_damage_ratio_curves`
has always defaulted off). One thing worth your attention: that flag's
default table name (`damage_ratio_curves_table`) still names the now-archived
file by its old top-level path. Flipping the flag on without also updating
that name will now fail loudly (`FileNotFoundError`) instead of silently
serving illustrative values -- I left it that way (the safer failure mode)
rather than removing the flag/table machinery outright. **CONFIRM** if you'd
rather I delete that dead path entirely.

**Item 6 (T26 bridges):** `T26_recovery_schedule_US_candidate_bridges.xlsx`
converted to a real CSV (same schema as the road table) and wired in:
Script 4's `load_scenarios()` now pairs it with the road
`T26_recovery_design_current.csv` via a new
`resiflow.tables.recovery_schedule_from_bridge_and_road_tables` (the two
tables' day checkpoints rarely coincide -- e.g. bridge/average's full
recovery is 147 days vs. road/average's 90 -- so both are evaluated at
their shared union of checkpoints). `recovery.use_table_recovery_design`
flipped to **true** (was false) since you confirmed both tables as
correct/final; this is a real default-behavior change to every flood run
using the recovery schedule, not a dormant option. The bridge schedule is
re-anchored to NCHRP Web-Only Document 390 (2024) -- the Hurricane Harvey
/ I-69 South bridge case for the average scenario, and WOD 390's
Figure B-14 years-tail for the slow scenario.

**Item 7 (T27):** Confirmed correct/final. Script 4's flood residual-speed
restriction now actually **reads** T27 (`resiflow.tables.flood_residual_speed_gate`)
instead of a hardcoded `if event_day == 1/2/3` check. Two real, previously
undiscovered bugs surfaced while wiring this:
  - **T27 was dead code in every real run.** This project's real
    recovery-schedule day checkpoints are 0, 7, 14, 30, 60, 90 (T26's own
    day columns) -- none of which are 1, 2, or 3, so the old hardcoded
    check never fired for any real scenario. The restriction existed in
    the model's design but never actually executed.
  - Even on paper, the old hardcoded version had a gap T27's schedule
    doesn't: on the "intermediate-depth" day it explicitly excluded deep
    (>6m) segments, so a severely flooded road briefly got NO speed
    restriction at all before being re-gated the next day. T27's schedule
    is cumulative (its "depth > 2m" tier also covers deep segments), so
    this is now fixed too.
  - **How T27 is used / what it's supposed to inform** (since this
    qualifies as the harmonization issue you asked me to flag): it tells
    Script 4, for each day after a flood, which previously-flooded
    segments (by their initial depth) still have their speed capped at
    the T19 speed-depth value vs. which have recovered to full speed --
    i.e. it's the residual-speed half of recovery, separate from T26's
    capacity-recovery half. `recovery.residual_depth_gates_m` (2m/6m)
    still supplies the depth thresholds; T27 now supplies the day ranges.
  - **Invariant this fix depends on, now made explicit:** day 0 always
    runs first and fully closes every flooded segment (T27's own "all
    flooded segments" row); later days only narrow which segments *stay*
    closed as the water recedes. Both `recovery_schedule_from_table()`
    (`event_days` seeded with `{0, ...}`) and the real production data
    bundle's own `recovery design_updated.csv` (first row is
    `event_day=0`) already guarantee this. One place didn't: the toy test
    fixtures' single-checkpoint recovery design stub used `event_day=1`,
    skipping day 0 entirely -- under the old hardcoded gate this was
    harmless (day 1 happened to also mean "close everything"), but under
    the real T27 schedule it meant a shallow-but-still-fully-closed toy
    flood edge reopened immediately, since the fix correctly assumes day
    0 already ran. Fixed the fixture to use `event_day=0` (matching the
    real convention) and the dependent output filenames
    (`..._s1_day1.gpq` -> `..._s1_day0.gpq`) across
    `tests/test_toy_pipeline_disruptions.py` and
    `tests/test_sioux_falls_pipeline_disruptions.py`.

**Item 9 (re-keying + tolls):**
  - Re-keying turned out to be a real, confirmed bug, not just a cleanup:
    `resiflow.networks.normalize_network_links()` was **unconditionally
    overwriting** the real `hpms_fclass`-derived `assignment_tier` that
    `convert_faf5_links()` computes (F1/F2->freeway, F3/F4->arterial,
    F5/F6->collector, F7->local_access) with the old name-based
    `network_mapping.faf5.json` mapping, immediately after Script 1 loads
    the network -- every FAF5 `primary` link was being forced back to
    "arterial" regardless of its real F_Class, silently discarding the
    2026-10-02 fix. Fixed: it now only fills in `assignment_tier`/
    `damage_profile` from the JSON mapping where a real value isn't
    already present, so FAF5 keeps its real per-link tiers and non-FAF5
    networks (OSM/TNTP/toy) keep working exactly as before. Real impact on
    the national network: **72,674 links (15.0%)** had a different
    assignment tier under the bug than their real `hpms_fclass` says --
    worst on `collector`, which the bug collapsed from a real 35,604 links
    down to 784 (the name-based mapping only ever assigns "collector" to
    the rare `tertiary` tag, never to the real F5/F6-class links hiding
    inside the generic `primary`/`motorway_link` names).
  - **Toll costs**: real and already in the generalized cost. FAF5's own
    `TRUCKTOLL` field (5-axle average toll x segment length, real per-link
    data) drives `average_toll_cost` in `convert_faf5_links()`; Script 1/4's
    route-assignment cost model (`road_revised.py`) sums it directly into
    `total_cost = cost_fuel + cost_time + cost_toll + cost_fare` and reports
    `cost_toll`/`toll_cost_total` as its own line item. This is the
    **travel/routing** cost (it affects route choice and rerouting-cost
    estimates), not the disaster **damage** cost -- Script 3's direct
    damage figures (bridge/road/tunnel repair cost) correctly do not
    include tolls, since a toll has nothing to do with what it costs to
    fix a flooded road.

**Item 14 (surface floods never reaching extensive/severe):** Confirmed
intentional by you -- no action taken.

**T08, T26, T27 confirmed correct -- other files brought into line:**
  - `assignment_profiles.json`'s own default values (previously the
    UK-relabeled numbers this doc's own audit flagged -- arterial 2,200
    veh/lane-h and 60 mph vs. the real US 900 and 45) now match
    `T08_assignment_tiers_US_candidate.csv` directly: `flow_cap_plph`/
    `free_flow_speed`/`urban_speed_cap`/`min_speed_cap` copied verbatim.
    `flow_breakpoint`/`congestion_factor` are **derived**, not copied --
    T08's own flow_breakpoint column is BPR-oriented text ("n/a (use BPR)"
    for 3 of 4 tiers, a range for the 4th) because it assumes a classic
    BPR a/b power-law congestion curve, which this codebase's actual
    edge-speed model doesn't implement (it's piecewise-linear:
    breakpoint + slope). Both are derived via the same NCHRP 825 Exhibit
    128 linearization already used in `t08b_profile.py`
    (`Q_bp = 0.85 x capacity`; `slope = free_flow_speed / (1.15 x capacity)`),
    so the derivation is reused, not invented fresh. `assignment.tier_table`
    default repointed from the now-archived UK file to the real US
    candidate; `resiflow.networks.profiles._load_profiles_from_table`
    applies the identical derivation when the flag path is used, so both
    paths agree (confirmed by test).
  - This is, like the T26 flag flip, a real default-behavior change --
    baseline arterial capacity drops from the UK-relabeled 2,200 veh/lane-h
    to the real US 900 for every flood scenario using the default
    (non-T08b) assignment path.

**USD harmonization (NHCCI):** T24 CP25 (2018 USD), T30 (2024 USD), and the
Rostami et al. tunnel model (December 2008 USD) were three different
dollar-years being summed together unescalated the moment
`vulnerability.use_sourced_asset_costs` is turned on -- a gap I noticed
while reporting back on 2026-10-05's work and you asked me to close using
`NHCCI_20260922.csv`. New `resiflow.nhcci` module reads FHWA's real
National Highway Construction Cost Index (seasonally adjusted composite,
2003 Q1-2026 Q1) and computes escalation factors; a construction-specific
CPI fallback was considered but not needed -- all three source years
already fall within NHCCI's own coverage. All three cost modules
(`cp25_road_cost.py`, `bridge_cost_t30.py`, `tunnel_cost.py`) now escalate
to the **latest available NHCCI quarter** (2026 Q1 as of this writing) by
default -- an objective, non-arbitrary target that updates automatically
as the NHCCI file is refreshed, rather than a hardcoded future year.
Real factors as of this writing: T24 (2018 Q4->2026 Q1) x1.692; T30
(2024 Q4->2026 Q1) x0.977 (NHCCI's seasonally-adjusted composite actually
dipped slightly over that window); tunnels (2008 Q4->2026 Q1) x1.916.
Every function keeps an explicit `escalation_factor=1.0` override for
anyone who wants the table's literal, unescalated published values.

**Decisions made this pass (logged per your standing instruction):**
1. `recovery.use_table_recovery_design`: false -> **true**.
2. `recovery.recovery_bridge_design_table`: new, `T26_recovery_schedule_US_candidate_bridges`.
3. `assignment.tier_table`: `T08_assignment_tiers_UK_current` (archived) -> **`T08_assignment_tiers_US_candidate`**.
4. `assignment_profiles.json`: UK-relabeled defaults -> real US T08 values (verbatim + NCHRP-825-derived breakpoint/congestion).
5. T27 read live instead of hardcoded; depth-gate day ranges now table-driven.
6. All three sourced-cost modules escalate to the latest NHCCI quarter by default (not the literal published dollar-year).
7. T22 TEMPLATE formally archived; xlsx confirmed permanent.

---

## Resolved, 2026-10-05: Real sourced costs for roads (T24 CP25), bridges (T30), tunnels (Rostami et al.)

Per your explicit decisions: T22 stays on `damage_ratio_road_flood.xlsx`
(Van Ginkel-based, unchanged); roads now cost via T24 CP25; bridges via
T30; tunnels via the Rostami et al. (2013) method you specified in
`docs/BRDIGE_COSTS.md`. All wired behind a new
`vulnerability.use_sourced_asset_costs` flag (default **False** -- same
SA-seam convention as every other real-table swap this project has made;
the legacy `damage_cost_road_flood.xlsx`-based path is unchanged and stays
the default until you flip it) in `scripts/3_damage_analysis.py`'s new
`calculate_damage_sourced()`.

- **T22**: confirmed the real xlsx (and the T22 CSV alternative) both
  produce bare `C1`..`C6` columns -- `create_damage_curves()`'s old
  `Interstate`/`US Route`/`State Route`/`Local` name-translation path never
  actually matched either real source (it silently fell through to a
  positional fallback that happened to work by coincidence); simplified to
  require `C1`-`C6` directly, and fixed the CI/toy fixtures
  (`tests/toy_pipeline_fixtures.py`, `tests/sioux_falls_fixtures.py`) that
  *were* relying on the old named columns to use real `C1`-`C6` instead.
- **T24 CP25 (roads)**: new `resiflow.networks.cp25_road_cost` joins on
  `region` (your own `urban` flag) x `functional_class` (real HPMS names,
  matches `hpms_fclass` 1-7 exactly) x `subcategory_or_terrain`. Urban side
  joins T39/`resiflow.census_urban_area` for real population tier --
  **99.95% real match rate** (360,512/360,684 road links nationally).
  Rural side has no reliable per-link terrain source yet (HPMS LRS
  `Terrain_Type` matches only ~22% of national miles and isn't merged into
  production `road_links`) -- every rural link uses a flagged `Rolling`
  default until real terrain is wired; **CONFIRM** whether that's
  acceptable or whether wiring the 22%-coverage real terrain now is worth
  it. `improvement_type` is fixed to `Total Reconstruct Existing Lane`
  (analyst default -- T24 has no "flood repair" row; this is the "repair in
  kind, no added capacity" choice) -- **CONFIRM**.
- **T30 (bridges)**: new `resiflow.hazards.bridge_cost_t30` joins state
  (NBI's own per-bridge FIPS code, falling back to FAF5's `STATE`) x
  NHS/non-NHS -- **100% real match rate** (122,514/122,514 bridges
  nationally). The $/ft2 replacement cost is scaled by the discrete HAZUS
  6.1 Table 11-10 damage-state ratio, the *same* ratio this pipeline
  already uses for earthquake bridges, instead of a second
  independently-invented bridge damage scheme. **CONFIRM**: T30's own
  source citation for `cost_used_for_2024_estimate_usd_per_ft2` isn't
  documented (methodology resembles the standard state-DOT/ARTBA
  poor-bridge-cost approach, including the industry-standard 68%-rehab
  convention, but this wasn't independently verified against a named
  source) -- flagged in the table's own header.
- **Tunnels (Rostami et al.)**: new `resiflow.hazards.tunnel_cost`
  implements `docs/BRDIGE_COSTS.md`'s spec exactly, reproducing its own
  worked example ($78.67M for 1km/2-lane/1-bore default geometry) to the
  dollar. Direct damage reuses the same discrete HAZUS tunnel ratio used
  for bridges, per the spec's own step 5. Resolves for **all 401 real
  highway tunnels** nationally, 0 errors; total implied construction value
  **$16.3 billion (2008 USD)** across the inventory.
  - **Real bug found and fixed while wiring this**: NTI's `tunnel_length_g1`
    and `roadway_width_curb_to_curb_g3` fields are in **feet**, not meters
    -- confirmed empirically against 5 real named tunnels (Eisenhower,
    Holland, Lincoln, Hampton Roads, Fort McHenry) whose raw values matched
    their real published lengths *in feet* exactly, while
    `scripts/load_ntad_tunnel_gpkg.py` was loading them unconverted under a
    `_m` column name. Fixed with the `0.3048` conversion `docs/BRDIGE_COSTS.md`
    itself calls for. National mean `tunnel_length_m` dropped from an
    implausible 1,675m to a plausible 453m after the fix (max dropped from
    17,112m -- longer than any real US highway tunnel -- to 4,054m, matching
    the longest real tunnels in the inventory).
  - **Second bug found and fixed**: `scripts/build_nti_tunnel_index.py` was
    summing tunnel length across all NTI records matched to one FAF5 link
    (double-counting a multi-bore tunnel as if its bores were end-to-end);
    per the spec's own step 2 ("grouped NTI records use longest-bore
    length"), switched to `max()`, and added the bore count/lane-count/
    width fields the Rostami model needs (`tunnel_bores`,
    `tunnel_lanes_total`, `tunnel_roadway_width_m`, `tunnel_length_m_min`
    for an unequal-bore-length flag) -- none of these were being carried
    through to `road_links` before.

**Still open / needs your input:**
1. Rural terrain default (`Rolling`, flagged) vs. wiring the real
   22%-coverage HPMS terrain now.
2. T24's `Total Reconstruct Existing Lane` improvement-type choice for
   flood repair costing.
3. T30's unconfirmed source citation.
4. The new pathway is off by default (`use_sourced_asset_costs: false`) --
   confirm you want it flipped on, or left as an available option for now.

---

## Resolved, 2026-10-02 (2): Census urban-area population crosswalk

Closes the recurring blocker from the first 2026-10-02 pass below: T08b's
own unapplied 8% small-metro adjustment and T24/CP25's Small Urban/Small
Urbanized/Large Urbanized/Major Urbanized tiers both needed an
urbanized-area-size crosswalk this project didn't have.

- **New `T39_census_urban_area_population_2010.csv`** -- real U.S. Census
  Bureau 2010 Urban Area population list
  (https://www2.census.gov/geo/docs/reference/ua/ua_list_all.xls, raw copy
  kept at `parameters/tables/raw/census_2010_ua_list_all.xls`), built by
  `scripts/prepare_census_urban_area_population.py`. **Vintage confirmed,
  not assumed**: all 503 distinct real Urban_Code values in the national
  FAF5 network match a 2010 UACE code exactly (0 unmatched) -- spot-checked
  against real population figures (63217 = New York--Newark, 18,351,295;
  51445 = Los Angeles--Long Beach--Anaheim, 12,150,996; etc., not just a
  format match).
- **`hpms_urban_size_tier`** thresholds are quoted verbatim from FHWA's
  HERS/C&P Report (23rd Edition, Appendix A, p.A-3 -- fetched and read
  directly, not from memory): small_urban 5,000-49,999; small_urbanized
  50,000-200,000; large_urbanized >200,000-1,000,000; major_urbanized
  >1,000,000 -- rural below 5,000 (a real, FHWA-documented floor; confirmed
  zero FAF5 links actually hit this edge case, since FAF5 routes every
  small-urban link through its own generic 99998 sentinel rather than a
  specific small-urban-cluster code).
- **`nchrp825_population_gt_250k`** is a separate column for T08b's own,
  independent >250,000 cutoff (NOT derived from the HERS tiers -- a
  different source, kept distinct rather than conflated).
- **New `resiflow/census_urban_area.py`** joins FAF5's raw `Urban_Code`
  (now also carried through `convert_faf5_links`, alongside the existing
  binary `urban` flag) against T39, handling both sentinels explicitly
  (`99998` -> `small_urban`, no population; `99999`/missing -> `rural`, no
  population -- never a fabricated figure).
- **T08b's 8% small-metro adjustment is now live**
  (`resiflow.networks.t08b_profile._apply_small_metro_adjustment`):
  capacity is cut 8% for Downtown/Urban/Suburban arterial/collector links
  in metro areas at or under 250,000 population, with
  `flow_breakpoint_Qbp_pc_per_lane_hr` and `congestion_slope_mph_per_pcu`
  re-derived from the adjusted capacity using T08b's own documented
  formulas (`Q_bp = 0.85 x capacity`; `slope = free_flow_speed / (1.15 x
  capacity)`) so the three stay internally consistent, not independently
  guessed at. T08b's own CSV is untouched (still Exhibit 128's literal
  published values) -- the cut is applied at join time only. Real result
  on the harmonized national network: **58,266 links (12.0%) get the
  cut** -- 34.8% of the urban arterial/collector links the adjustment is
  scoped to. Freeway and Rural rows are untouched, confirmed.
- **Still open**: the Downtown/Urban/Suburban *sub-split itself* (as
  opposed to the population-size adjustment, which doesn't need it).
  Population size cannot distinguish a CBD link from a suburban-fringe
  link in the same metro -- that needs real land-use/CBD-distance data
  this project doesn't have; T08b's "Urban" row stays a documented
  approximation covering all three. T24/CP25 is not wired to consume T39
  yet (T24 remains out of scope for this pass, per the first 2026-10-02
  entry below) but the crosswalk is ready for it.

---

## Resolved, 2026-10-02 (1)

Implemented against your direct decisions. Real-data numbers below are from
re-running `convert_faf5_links()` against the actual raw FAF5 geodatabase
(`Desktop/data/faf5_data/network_data/FAF5Network.gdb`, 483,599 links after
centroid-connector filtering) -- not estimated.

- **Item 1 (urban all-1 bug):** Fixed -- `Urban_Code` now coerced to numeric
  before the `!= 99999` compare, with an explicit `notna()` guard so missing
  values default to rural (not silently "urban" under `!=`'s NaN semantics).
  Real result: **74.8% urban / 25.2% rural**, matching the 24.7% estimate
  almost exactly. `99998` ("small urban area" per the FAF5 Network Data
  Dictionary -- confirmed, not `n/a` as this doc guessed) correctly counts
  as urban. See `resiflow.preprocess.faf5_network.convert_faf5_links` step 7.
- **Item 8 part 1 (lanes, bidirectional):** Fixed -- `DIR==0` links now sum
  `AB_Lanes + BA_Lanes`; `DIR==1` (and the real geodatabase's undocumented
  `DIR==-1`, 391 links, logged) keep `AB_Lanes` alone. See step 6.
- **Item 10 (`hpms_fclass`):** Added -- real `F_Class` (1-7) from the raw
  gdb, with the documented faf5_class-based fallback for the 4.5% null/
  out-of-range (confirmed: codes up to 10 appear; 10 and null both fall
  back) -- `resiflow.hpms_fclass.derive_hpms_fclass`. Also added
  `nhs_designation` (FAF5's own real `NHS` field, not inferred) and
  `assignment_tier` (the Section 1 harmonization rule, F1/F2→freeway etc.).
- **Item 3 / 11 / "Proposed FAF harmonization" rows 1, 2, 4 (T08/T20/T22
  classification):** Implemented as proposed, with one correction: the real
  NHS field (not F_SYSTEM/Interstate-name proxying) now drives sophistication.
  Real before/after on the harmonized network: the old name-based major/minor
  split called **96.6%** of links "major" (confirming this doc's own
  observation that it was nearly degenerate); the new `hpms_fclass`-based
  split gives **79.4%** -- a real, more differentiated split, not just a
  renaming. **89,598 links (18.5%) flip classification**, almost entirely
  (85,862 of them) FAF5 Class-14 `primary` links reclassified major→minor --
  exactly the Class-14 "arterial OR major collector" merge this doc flagged
  (item 3/Section 1) getting genuinely split apart by the real F_Class
  attribute, not just renamed.
  - T22 (`compute_damage_fraction`, `scripts/3_damage_analysis.py`): when
    `nhs_designation` is available, curve family is van Ginkel's real
    sophisticated(C1/C2)/simple(C3/C4)/ordinary(C5/C6) scheme -- on NHS +
    tunnel / on NHS no tunnel / not on NHS -- replacing the old "major by
    name" proxy that put Class 14 on C3/C4 regardless of real NHS status.
    Falls back to the legacy name-based proxy when nhs_designation is
    absent (non-FAF5 networks).
  - T20 (`flood_categorical.py`): major/minor (`_is_major`) now prefers
    real `hpms_fclass` (F1-F3 major) over the name-based set. Separately,
    the van Ginkel/Li 3-way sophisticated/simple/ordinary scheme is fully
    wired and auto-selected when `vulnerability.damage_threshold_table`
    points at the new `T20_damage_level_depth_thresholds_US_candidate.csv`
    -- sophistication now correctly splits within NHS roads using real
    tunnel presence (`road_label=='tunnel'`, NTI-matched), closing the gap
    that table's own header flagged ("will resolve identically until a
    second attribute... splits them").
  - T08 (`assignment_tier_from_fclass`): F1/F2→freeway, F3/F4→arterial,
    F5/F6→collector, F7→local_access, same rule as proposed, now also the
    `facility_type` join key for the new T08b wiring below.
  - T08b (NEW): `T08b_facility_area_capacity_speed_US_candidate.csv`
    (NCHRP 825 Exhibit 128, verified against the source image) is now
    joined per-link on real `(facility_type, area_type, lane_category)`
    keys -- `resiflow.networks.t08b_profile` -- behind
    `assignment.use_table_t08b` (default off). Real match rate: **483,408
    of 483,599 links (99.96%)**. `area_type`'s Downtown/Suburban split and
    T08b's own unapplied 8%-small-metro-population adjustment are NOT
    resolved -- both need an urbanized-area-size crosswalk this project
    doesn't have (same gap as T24's CP25 Small/Large/Major Urbanized
    tiers, item 15 below); collapsed to a single "Urban" row, documented
    as an approximation, not guessed per-link.
  - T24/T30 (bridge cost class, rural/urban × terrain cost class): **not
    done** -- out of scope for this pass, same open gap as before.
- **Item 13 (car vs. truck closure threshold):** `flood_operational.
  apply_max_speed_to_links` now computes an additional `max_speed_truck`
  column (60cm, `hazard_disruption.flood_closure_threshold_truck_cm`)
  alongside the existing passenger `max_speed` (30cm) -- confirmed
  `v_ratio_xd15` has zero consumers anywhere in this project, left
  unwired. The shared assignment-stage speed/capacity solve still runs on
  one combined freight+passenger flow at the car threshold (matches the
  existing pattern Script 4's `overlay_combined_flows` already uses
  elsewhere: one shared physical solve, cost split per mode afterward) --
  **`max_speed_truck` is NOT yet consumed by Script 4's freight
  rerouting-cost stream**; wiring that in is a real follow-up (confirmed
  via research to be a moderate change, not a one-line fix -- Script 4's
  freight/passenger cost split already exists at specific call sites, it
  just needs to read `max_speed_truck` instead of reusing the car column
  for the freight mode).
- **Item 17 (`Urban_Code` 99998 meaning):** Resolved -- confirmed via the
  FAF5 Network Data Dictionary (`Desktop/data/faf5_data/network_data/
  FAF5 Network Data Dictionary.pdf`): "small urban area". Not a mystery
  code; correctly treated as urban (see item 1).

**Still open, unchanged by this pass:** items 2, 4 (bridge d(H) -- the NBI
join itself was already fixed in the prior bridge/tunnel session), 12, 15
(partial -- urban-size and dollar-year now resolved, rural terrain still
isn't), 16 (resolved 2026-10-05 via Rostami et al.). Items 5, 6, 7, 9, 14
resolved 2026-10-08 -- see that section above.

---

## 0. The flood path in one page

```
raster depth ──► [Script 2] intersect with links
   ├─ speed:   flood_operational.py   T19 (speed-depth) ──► max_speed            (closure at depth_key = 30 cm)
   ├─ level:   flood_categorical.py   T20 (thresholds)  ──► damage_level (no…severe)
   └─ cost:    Script 3               depth ──► d(H) from C1–C6 curves  (xlsx / T22)
                                      × unit cost (xlsx roads / bridges)  × length × lanes (roads) or width (bridges)
              Script 4               damage_level ──► T26 recovery;  max_speed / depth gates ──► T27-style residual speed
              Script 1/4             assignment_profiles.json + network_mapping.faf5.json ──► capacity, speed, tiers
```

Roads follow your note's formula exactly: `length × 1e-3 × lanes × unit_cost[class] × d(H)`, evaluated for min and
max cost and averaged. **Bridges do not**: `width × length × unit_cost[level]`, with **no d(H)** (Section 4, item 4).

---

## 1. The network facts every table depends on

Live network (`faf5_road_links.gpq`, 483,599 links), joined to the raw FAF5 geodatabase.

| FAF5 `Class` | Meaning | Links | % of length | `road_classification` now |
|---|---|---|---|---|
| 11 / 13 / 33 | Interstate / non-freeway interstate (AK) / express lane | 16.8% | 16.5% | motorway |
| 12 | Other controlled-access (freeway/expressway) | 10.1% | 6.6% | trunk |
| **14** | **Arterial or major collector (merged)** | **41.4%** | **70.6%** | primary |
| 21 / 22 | System ramp / ramp | 27.4% | 4.8% | motorway_link |
| 23 | Collector/distributor lane | 0.95% | 0.16% | **primary** |
| 15 | Local road | 0.16% | 0.02% | tertiary |
| 16 / 17 / 18 / 19 / 36 | Frontage, circle, turn lane, access, admin road | 3.2% | 0.6% | service |
| 41 | Ferry | 0.04% | 0.76% | **service** |

Three facts drive most of the issues below:

- **The raw FAF5 carries `F_Class` (the HPMS functional system, 1–7), and the network parquet does not.**
  It splits the merged class 14 into Other Principal Arterial (51% of class 14), Minor Arterial (30%) and
  Major Collector (12%), and gives every ramp its parent system. This is the key that T22, T24 and T30 are
  written in. Joining it costs the same as the `faf5_class` join already done.
- **`urban` is 1 on every link.** Raw `Urban_Code` is a *string*; the converter compares it to the integer
  99999, which is never equal, so nothing is ever rural. In truth 24.7% of raw links are `99999` (rural) and
  9.0% are `99998` (meaning not documented in this repo).
- **`lanes` is `max(AB_Lanes, BA_Lanes)`.** Correct for one-way links (DIR = 1: 65% of links, e.g.
  interstate carriageways), but **understates bidirectional links** (DIR = 0: 35%, including 81% of class 14).
  For those, cost should count AB + BA. 157 links have 0 lanes.

### Proposed FAF harmonization (spine for every table below): CONFIRM

Primary key = `hpms_fclass` (raw `F_Class`); `faf5_class` for ramp/topology handling and exclusions.

| Attribute | Rule | Replaces |
|---|---|---|
| **Curve family (T22)** | F1, F2 → C1–C4 (freeway with embankment); F3–F7 → C5/C6 | `_is_major_road` (see Section 4, item 3) |
| **Threshold class (T20)** | *major* = F1–F3, *minor* = F4–F7 (ramps take their F_Class; C/D lanes take F1/F2) | 5-name set that covers ~97% of links |
| **Cost class (T24)** | HPMS functional class × rural/urban (× terrain or urban size) | 4-label GB workbook |
| **Bridge cost class (T30)** | NHS / non-NHS from NBI `HIGHWAY_SYSTEM_104` × NBI state | not wired |
| **Assignment tier (T08)** | F1, F2 → freeway; F3, F4 → arterial; F5, F6 → collector; F7, frontage/access → local | `network_mapping.faf5.json` (name-based) |
| **Excluded** | Class 41 (ferry), class 50 | ferries priced as roads today |

Where `F_Class` is null (4.5% of raw links) or 10, fall back by `faf5_class` and log the share.

---

## 2. Table register

### T19 `T19_speed_depth_curve_discretized.csv` — ADOPTED, wired (`use_table_speed_depth: true`)
- **Use:** `flood_operational.apply_max_speed_to_links` → `max_speed = free_flow × V/V₀(depth)`, closed at
  `depth_key`. Columns are `v_ratio_xd15 / xd30 / xd60` (Pregnolato 2017 quadratic, discretized every 5 cm).
- **FAF keying:** none. One curve for every class.
- **FIX/CONFIRM:** (a) The table is interpolated by column name `v_ratio_xd{depth_key}`; any closure threshold
  outside 15/30/60 raises. (b) Every flood scenario uses `closure_threshold = 30` (cars). Freight demand is
  trucks; the 60 cm column (Kramer 2016) exists but nothing selects it: **decide car vs. truck vs. ensemble**
  (audit #18). (c) `speed_depth_exponent` is ignored while the table is on (a warning is logged only if a non-default exponent is set).

### T20 `T20_damage_level_depth_thresholds.csv` — CURRENT+FLAGGED, **not wired** (`use_table_damage_thresholds: false`)
- **Use (when on):** `flood_categorical` → `damage_level`. With the flag off the identical numbers are
  hard-coded in the module. Levels feed: which rows survive the Script 3 filter, bridge cost lookups, and
  Script 4 recovery (T26).
- **FAF keying:** binary major/minor by name.
- **FIX:** the major/minor split is degenerate on FAF5: `secondary` and `local` never occur, so **minor =
  3.4% of links** (service + Class 15). **CONFIRM** the F-class rule in Section 1.
- **CONFIRM:** *surface* thresholds cap at "moderate" for both classes. Since T26 only removes capacity at
  extensive/severe, **surface flooding can never cost capacity, at any depth.** Intentional?
- **FIX:** coastal thresholds are placeholders; the hard-coded coastal branch in `flood_categorical.py` still
  runs when the flag is off (the table only gates it out when on). Gate it in code too.
- **NOTE:** T20 "minor from 1 cm" for river-minor differs trivially from the code's `depth > 0`.

### T22 damage-ratio curves — three artefacts, do not confuse them

| Artefact | State |
|---|---|
| `damage_curves/damage_ratio_road_flood.xlsx` (data bundle, **the live curves**) | 121 rows, 0–6 m every 5 cm, fractions C1–C6 |
| `T22_damage_ratio_curves_TEMPLATE.csv` | **Illustrative shapes only.** Yet it is the *default table name* behind `use_table_damage_ratio_curves` |
| `updates_ak/T22_damage_ratio_curves_US_candidate.csv` | van Ginkel 2021 Table 2 knots × HPMS class × terrain, with US $ columns |

- **Verified:** all 34 distinct knots in the US candidate reproduce the live xlsx exactly (0 mismatches). The
  curves are already van Ginkel's; only the *labels and dollar basis* are new.
- **FIX (hazard):** flipping `use_table_damage_ratio_curves` today would replace the real curves with the
  TEMPLATE's illustrative ones. Build the wide `depth_cm, C1_…, C6_…` table from the verified knots (fractions
  only, no $) and retire the TEMPLATE. The US candidate's long, $-embedded schema will not load as is
  (`_load_damage_ratio_table` expects wide fractions).
- **FIX (classification):** see Section 4, item 3. The code selects the curve family from `_is_major_road`, which puts
  **class 14 (70% of length) on C3/C4**, but van Ginkel/T22 assign "other roads" (primary and below) to C5/C6.
  At 1 m: C3 0.4% / C4 4% versus C5 2.5% / C6 20%.
- **CONFIRM:** interstates use C3/C4 ("simple") in code; T22's note defaults Interstate/Freeway to C1/C2
  ("sophisticated"). Today C1/C2 are used only for *tunnels*.
- **NOTE:** low/high-flow curve pairs are both evaluated; consolidation is in `damage_aggregation.py` (not
  reviewed here).

### T24 unit costs — the biggest gap

| Artefact | State |
|---|---|
| `asset_costs/damage_cost_road_flood.xlsx` (**live**) | 4 road labels (Interstate 0.45–0.90, US Route 0.30–0.60, State Route 0.20–0.40, Local 0.10–0.25 *million per lane-km*); bridges 0.0008–0.0016 (river 0.001–0.002) *million per m²*, **identical for every damage level**; tunnels = road values |
| `T24_asset_unit_costs_US_candidate.csv` | ranges only, `APPROXIMATE_VERIFY` |
| `updates_ak/T24_asset_unit_costs_US_candidate_CP25.csv` | FHWA HERS Exhibit A-5…A-8, 833 verified rows, $K per lane-mile, **2018$**, functional class × (rural terrain or urban size) × improvement type |

- **Use:** `compute_damage_values` in Script 3. Cost keys built from lanes/urban/form-of-way
  (`m_lt8_urb`, `asingle_sub`, …) **never exist** in the 4-label workbook, so every road falls through to
  `fallback_asset_label` (motorway/trunk → Interstate; primary/secondary → US Route; **tertiary and service →
  State Route**; else Local). On FAF5 the "Local" label is effectively unused, and ferries price as State Route.
- **FIX (units):** currency and dollar-year are unresolved (audit #24). `GBP_TO_USD` (1.27) exists but is
  **not applied** in Script 3, so GB values are used as if dollars.
- **Size of the gap** (workbook mean vs HERS "Total Reconstruct Existing Lane", per lane-km):

  | Class | Workbook | HERS rural flat | HERS urban (large) | Workbook ÷ HERS |
  |---|---|---|---|---|
  | Interstate | 0.675 M | 1.08 M | 2.25 M | 0.63 rural, **0.30 urban** |
  | Principal arterial | 0.45 M | 0.99 M | 2.07 M | 0.46 / 0.22 |
  | Major collector | 0.30 M | 0.81 M | 1.60 M | 0.37 / 0.19 |
  | Local | 0.175 M | 0.69 M | 1.33 M | 0.25 / **0.13** |

  So the live costs are **1.6× to 7.6× below** US reconstruction cost, worst exactly where urban/local would
  apply. With `urban` wrongly all-1 (Section 1) the urban column is the relevant one.
- **FIX:** the 3.3%/yr GB escalation is inherited (audit #25); use FHWA NHCCI to a chosen target year.
- **CONFIRM:** CP25 needs terrain (rural) or urban size, which the network lacks. Options: default "rolling"
  and a fixed urban size, or derive from a DEM/Census urban-area population. Pick one and log it.
- **CONFIRM:** tunnels have no national cost source (T24 marks OPEN, "do not reuse road costs"); the workbook
  reuses road costs. Keep out of totals, or price with a flagged assumption.
- **NOTE:** min/max/mean are kept in the workbook and averaged; keep the range for sensitivity analysis.

### T30 `updates_ak/T30_bridge_replacement_unit_costs_US.csv` — new, **not wired**
- 52 states × {NHS, non-NHS}, USD/ft² **2024** (NHS median $308, range $109–$1,606). Would replace the
  workbook's ~$1,200/m² (≈ $110/ft²), i.e. roughly **2.8× higher** at the median.
- **FIX:** the split needs the bridge's NHS status; the NBI field `HIGHWAY_SYSTEM_104` is in
  `docs/nbi_schema.md` but `build_nbi_bridge_index.py` does not carry it. Add it to the index (state is
  already carried as `bridge_state`).
- **NOTE:** cost is per ft² of deck, so it needs the NBI deck width (Section 3, network attributes).

### T26 `T26_recovery_design_current.csv` — CURRENT+CANDIDATE, **not wired** (`use_table_recovery_design: false`)
- **Use (when on):** replaces the data-bundle `recovery design_updated.csv` in Script 4. Steps: 0 → 50% →
  100% capacity by damage level and fast/average/slow scenario. Minor/moderate: no capacity loss.
- **FIX:** the bundle CSV has **separate bridge and road columns**; T26 has none, so switching flags
  silently gives bridges the road schedule. Add an asset split before enabling.
- **CONFIRM:** durations are European; re-anchor to US Emergency Relief records (audit #26).

### T27 `T27_speed_restriction_schedule.csv` — **documentation only**
- The model does not read this file. The behaviour lives in Script 4 and `recovery.residual_depth_gates_m`
  (2 m / 6 m): day 1 caps speed on every road, day 2 on roads with depth 2–6 m, day 3 on ≥ 6 m.
- **FIX:** the CSV's windows (days 1–3 for > 2 m, 3–7 for > 6 m, none after 7) do not match what the code does.
  Make one the source of truth (audit #27: parameterize per flood type; exposed gates already exist).

### T08 `T08_assignment_tiers_*` and `assignment_profiles.json` — capacity and speed under flood
- **Use:** baseline capacity, breakpoints, free-flow and minimum speeds per tier, which set baseline flows and
  therefore every rerouting cost. `use_table_tier_values: false`, table name defaults to the UK file.
- **Current values are UK values relabeled** (audit #8–10): arterial 2,200 veh/lane-h and 60 mph vs. the US
  candidate's 900 and 45; collector 1,700 / 55 vs. 700 / 40; local 1,000 / 35 vs. 550 / 30. Freeway is close.
- **CONFIRM:** US candidate is `APPROXIMATE_VERIFY` (planning-level HCM/NCHRP 825 reads); confirm exact
  exhibit values before adoption.

---

## 3. JSON and workbook parameters

### `parameters/network_mapping.faf5.json`
- Maps **name-based** `road_classification` → assignment tier and `damage_profile`. It cannot see
  `faf5_class` or `F_Class`.
- **FIX:** (a) Ramps (`motorway_link`, 27% of links) get freeway capacity 2,400 and 70 mph free-flow, though
  ramps run ~1.4 lanes at low speed. (b) `tertiary` → collector, but on FAF5 `tertiary` is Class 15 *Local
  Road*. (c) The `local` (→ arterial) key is never hit on FAF5, and `secondary`/`unclassified`/
  `centroid_connector` are near-unused; audit #16 flags the contradictory `local`/`tertiary` entries and the
  generous unknown-class default (arterial). (d) `damage_profile` (major_road/minor_road) is written to every
  link but **no consumer was found**; flood's own major/minor logic ignores it.
- **Action:** re-key on `hpms_fclass` / `faf5_class` per Section 1.

### `parameters/assignment_profiles.json`
- Source of the T08 values above and of the congestion slopes (0.033 / 0.05). Consumed by
  `networks/profiles.py`. Same UK-relabel issue; keep in step with T08.

### `parameters/hazards.example.json` (and the built-in scenario registry)
- Flood scenarios carry `closure_threshold: 30` (**cm**); other hazards carry mm. Units differ per entry and
  are only inferable from code (audit #31). For flood it selects the T19 column. **NOTE:** 304 (Harvey) and
  305 (Sandy) are the real events; 301–303 are generic subtypes.

### `parameters/unified_parameters.json` (flood-relevant keys)
| Section.key | Value | Note |
|---|---|---|
| `hazard_disruption.flood_closure_threshold_cm` | 30 | default when a scenario gives none |
| `hazard_disruption.use_table_speed_depth` / `speed_depth_table` | true / T19 | wired |
| `hazard_disruption.speed_depth_exponent` | 2.0 | ignored while the table is on |
| `vulnerability.use_table_damage_thresholds` | false | T20 hard-coded copy in use |
| `vulnerability.use_table_damage_ratio_curves` | false | default table name is the **TEMPLATE** (see T22 above) |
| `vulnerability.damage_threshold_scale`, `curve_theta`, `depth_scale_lambda` | 1.0 / null / null | sensitivity seams |
| `damage_costs.road_cost_scale`, `bridge_cost_scale` | 1.0 | sensitivity seams |
| `recovery.residual_depth_gates_m` | 2.0 / 6.0 | the real T27 |
| `recovery.use_table_recovery_design` | false | see T26 |
| `conversions.gbp_to_usd` | 1.27 | **not applied to flood costs** |

### Network attributes that enter the flood cost (from `format_intersections`)
- **FIX** `urban` (all 1), `lanes` (Section 1), **`averageWidth` = lanes × 3.5 m** (multiples of 3.5; US lane is
  3.66 m; Script 3 has a second default of 3.65; omits shoulders; audit #34). Bridges should use NBI deck width.
- **FIX** Script 3 fills `form_of_way = "Single Carriageway"`, `trunk_road = False`, `urban = 0` when absent
  (audit #37). None exist on FAF5, so these are dead inputs to the key builder.
- **FIX** `road_bridge` is `no` on every link in the network I hold (audit #36; the NBI join is built but not
  applied here), so no link is priced as a bridge locally.

---

## 4. Issues, ranked

**Blocking (results are wrong until fixed)**
1. **`urban` is 1 on every link** (string vs. int compare). Re-patch the parquet.
2. **Unit cost basis**: workbook is GB with unresolved currency/year and 1.6–7.6× below US reconstruction
   cost; `GBP_TO_USD` unused.
3. **Curve family**: class 14 (70% of length) uses C3/C4 instead of C5/C6.
4. **Bridges**: no d(H); cost identical across damage levels; NBI join not applied locally.

**Fix before enabling flags**
5. **T22 TEMPLATE** is the default table behind `use_table_damage_ratio_curves`.
6. **T26** lacks the bridge/road split the bundle CSV has.
7. **T27 CSV** disagrees with the code and is not read.
8. **`lanes`** (bidirectional), `averageWidth` (3.5 vs 3.66 vs 3.65), dead cost-key defaults.
9. **Ramps** priced and routed as freeways; `tertiary` = Local mapped to collector; ferries priced as roads.

**Confirm (decisions)**
10. Add `hpms_fclass` (raw `F_Class`) to the parquet and adopt Section 1's harmonization.
11. Interstate curves: C1/C2 (T22 note) or C3/C4 (current code).
12. Bridge cost: apply d(H) as in your note, or keep level-based costs.
13. Car vs. truck closure threshold (T19 xd30 vs. xd60).
14. Surface floods never reaching extensive/severe.
15. Terrain/urban-size assumption for HERS; target dollar year (NHCCI).
16. Tunnels: exclude or flagged assumption.
17. `Urban_Code` 99998 meaning (9.0% of links).

## 5. Suggested order
1. Patch the parquet: fix `urban`, add `hpms_fclass`, correct `lanes` for bidirectional links, set width.
2. Build the FAF/HPMS crosswalk table and re-key T20/T22/T24/T30/T08 on it.
3. Convert the T22 candidate to the wide fractions-only table; retire the TEMPLATE.
4. Add the cost loader (CP25 + T30, one target dollar year) and decide the bridge d(H).
5. Add the invariant tests from the earlier plan against the new loader.
