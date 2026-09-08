# Parameter audit checklist

Tracks every item in Nandu's `parameter_diff_final.xlsx` (`Parameter_DIFF_Matrix`
sheet, 38 rows) against the actual pipeline state, verified 2026-09-08. Row
numbers below (`#N`) match that sheet's `id` column. Use this to close the
parameter-audit thread out systematically rather than re-litigating it from
scratch each time.

## Already resolved -- no action needed

- [x] **#2 Average car occupancy** -- `road_revised.py` reads
  `cons.AVG_VEHICLE_OCCUPANCY_CAR` (1.52, NHTS 2022 Table 5-2), no longer
  hardcoded 1.06.
- [x] **#1 VOT values** -- parameterized via `unified_parameters.json`'s
  `vot_usd_per_hour`, US-sourced (USDOT VTTS 2022). Naming cleanup
  (`VOT_POUND_PER_HOUR` should be renamed/deprecated per the audit's own
  recommendation) is still open but cosmetic, not a value problem -- low
  priority, fold into a future cleanup pass.
- [x] **T19 speed-depth curve** -- wired AND activated
  (`use_table_speed_depth: true`). Verified the discretized table reproduces
  the exact same `V/Vmax = (1-d/xd)^2` formula already in production
  (d=15,xd=30 -> 0.25 exactly) -- behavior-neutral activation.
- [x] **#28 Freight OD disaggregation validation** -- "keep + validate vs
  FAF5 assignment AADTT" is essentially what the FAF5-vs-new-truck-OD
  demand comparison this session already did (found the ~3.9x gap). Treat
  this row as substantially addressed; the finding just hasn't been formally
  closed out in the spreadsheet itself.

## Wiring built this session, waiting on real data

- [ ] **#22 Damage-ratio curves (T22)** -- wiring done
  (`use_table_damage_ratio_curves`, off by default). **Next step:** replace
  `parameters/tables/T22_damage_ratio_curves_TEMPLATE.csv`'s illustrative
  values with real extraction from `damage_ratio_road_flood.xlsx` (archive
  that file into git first -- see hygiene section) and/or van Ginkel et al.
  2021 SI, then flip the flag.

## Wiring exists, needs value verification before activating

- [ ] **#3/#4 Fuel consumption curve (T04)** -- status `APPROXIMATE_VERIFY`.
  Source real EPA MOVES4 values before flipping `use_table_fuel_curve`.
- [ ] **#5 Non-fuel operating cost (T05)** -- status `MIXED` (ATRI headline
  figures sourced, component split needs verification against report
  tables). Verify, then consider flipping `use_table_nonfuel_curve`.
- [ ] **#8/#9 Assignment tiers (T08)** -- status `APPROXIMATE_VERIFY`. Pull
  exact HCM 7th ed. / NCHRP 825 exhibit values before flipping
  `use_table_tier_values`.
- [ ] **#20 Damage-level depth thresholds (T20)** -- status
  `CURRENT+FLAGGED`, coastal rows are placeholders. Do not flip
  `use_table_damage_thresholds` until #21 (below) is resolved; confirm with
  Nandu whether the non-flood-coastal rows are closer to ready on their own.
- [ ] **#26 Recovery design (T26)** -- status `CURRENT+CANDIDATE_NOTE`,
  "endpoint re-anchoring pending ER-record review." Re-anchor recovery
  durations to actual US emergency-response records before flipping
  `use_table_recovery_design`.
- [ ] **#27 Speed-restriction schedule (T27)** -- status
  `CURRENT+CANDIDATE`, per-flood-type recession gates not yet exposed.
  Decide if worth exposing in config before use.
- [ ] **#29 Payload conversion factors (T29)** -- status
  `APPROXIMATE_VERIFY`. Swap in the FAF5 Traffic Analysis commodity table
  verbatim -- directly related to the flat-20-ton-payload freight
  undercount already found this session.

## Needs a methodology decision, not a code task

- [ ] **#23/#24 Asset unit costs (T24)** -- no wiring exists. Needs: a
  point-estimate method from the low/high ranges, a way to derive
  per-damage-level costs (T24 only has one "reconstruct" cost per class, not
  minor/moderate/extensive/severe), and a tunnel-cost source (currently
  `status=OPEN`, "no national unit-cost source identified, do NOT reuse road
  costs"). Decide with Nandu or a domain expert before this becomes a
  wiring task.
- [ ] **#7 Freight isolation economic loss** -- mechanism retained, but
  freight-specific monetization was left undefined by the audit. Script 4
  currently uses `VOT_USD_PER_HOUR["ogv"] x 24h` as the isolated-freight-flow
  proxy (see `4_rerouting_and_recovery_scenario_loop.py`) -- confirm whether
  that's considered the intended answer to this row, or still genuinely
  open.
- [ ] **#30 LODES mode-share / telework scaling** -- jobs used directly as
  car trips, no mode-share or telework adjustment applied. Relates to the
  ~10% gap already found this session against the independent NHTS-style
  passenger dataset -- decide if that's close enough or worth a real fix.

## Blocking / top-priority per the audit's own language

- [ ] **#21 Coastal flood damage thresholds** -- still literally
  `PLACEHOLDER` in `flood_categorical.py`. **Do not run coastal scenarios**
  until resolved.
- [ ] **#23 Bridge/tunnel damage-model silent fallbacks**
  (`3_damage_analysis.py` ~L605-665) -- missing tunnel sheet silently reuses
  road costs; single-row bridge sheet silently broadcasts one cost to every
  damage level. At minimum make these fail loud; re-source bridge costs
  properly (ties to T24 above).
- [ ] **#24 Asset cost workbook provenance** -- GBP-to-USD conversion
  history for `damage_cost_road_flood.xlsx` is unrecorded/unclear. Audit and
  document before any further edits.
- [ ] **#36 Bridge identification default** -- infrastructure exists
  (`scripts/build_nbi_bridge_index.py`), but confirmed
  `nbi_bridge_index_path` is `null` in production config -- the index was
  built but never pointed at a real run. Production still defaults every
  link to `road_bridge="no"` (now with a loud warning instead of a silent
  one, at least). **Next step:** actually run the NBI index build for
  conus_nandu_v1 and set the path.

## Lower priority / documentation-only

- [ ] **#6 GBP->USD conversion factor** (1.27, now unused) -- remove now
  that US-native costs exist.
- [ ] **#15 Urban area definition (ETISplus GB mask)** -- dead code path
  for CONUS, present but unusable. Replace or remove, not blocking.
- [ ] **#17 Undirected network graph** -- directedness never re-established
  for FAF5's directional links. Verify current behavior is intentional;
  consider migrating to directed.
- [ ] **#25 Construction-cost escalation rate** (3.3%/yr, UK ONS) --
  inherited unchanged. Replace with a US index (FHWA NHCCI) alongside the
  T24 work above.
- [ ] **#33-35 Network attribute defaults** (`faf5_network.py`: lanes
  default=2, dual lane-width defaults 3.5m vs. 3.65m inconsistency,
  length/CRS fallback with no CRS guard) -- real engineering bugs,
  independent of the parameter-table system. Needs direct code fixes, not
  wiring.
- [ ] **#37 Cost-key classification fallbacks**
  (`3_damage_analysis.py` ~L493-500) -- all-defaulted attributes price every
  unlabeled link as suburban single-carriageway. At minimum, log the
  fallback share so its real prevalence is visible.
- [ ] **#38 Toll cost** (default 0, toll term disabled in cost function) --
  document as a deliberate scope decision, or wire in FHWA toll data if
  tolls matter to the research question.

## Process / hygiene

- [ ] **Reconcile or retire `feature/sensitivity-analysis`.** It's 134
  commits behind current work as of 2026-09. Either cherry-pick forward
  whatever unique value remains, or explicitly retire it -- don't let it
  keep existing in limbo.
- [ ] **Archive the two ungitted xlsx workbooks** (`damage_curves/
  damage_ratio_road_flood.xlsx`, `asset_costs/damage_cost_road_flood.xlsx`)
  into git now, as-is, before any further edits. The manifest itself
  repeatedly asks for this ("archive it... before replacement") -- do it
  before any more provenance gets lost.
- [ ] **Sync with Nandu directly** on which of the "needs methodology
  decision" items above he already has an informed answer for vs. which
  need a fresh decision from you or an advisor.
