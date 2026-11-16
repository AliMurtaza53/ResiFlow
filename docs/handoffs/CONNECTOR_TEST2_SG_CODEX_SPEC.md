# Test 2: populate sub-county (S) and facility-range (G) centroids (handoff spec for Codex)

Drafted 2026-11-16 by Claude for the owner. Intended location: `docs/handoffs/CONNECTOR_TEST2_SG_CODEX_SPEC.md` on `exp/connector-loading-test1` (Codex's branch; Claude did not touch that worktree). Bounded mandate: allocate, assign, verify, one report, then stop.

## 1. Question
With all official FAF5 centroids (C parent county 3,142, S sub-county 100, G facility-range 255) and their 3,795 Class 50 connectors in the network, can freight OD be loaded at S and G in a conservation-checked, FAF-informed way that routes cleanly through endpoint-only connector access, and does it improve agreement with the published 2022 assignment on connector and surrounding road links? Physical capacities and total OD volumes stay fixed.

## 2. Prior knowledge (do not re-derive)
- FAF5 geodatabase: 348,495 distinct nodes (344,998 road, 3,142 C, 100 S, 255 G), 487,394 links (483,599 road, 3,795 Class 50). `FAF5_Nodes` has 974,788 raw rows (3,796 centroid rows); count distinct node ids. Source: `C:\Users\akothaw\Desktop\data\faf5_data\network_data\FAF5Network.gdb`.
- The 2022 assignment (BTS/ROSAP dot/88267) is flow records keyed by link id, 315,895 of 487,394 links. A link with no record still exists. There is no node-flow record.
- Connector coverage in the 2022 data: C 3,338 of 3,399 positive, 61 missing; S 101 of 101 positive; G 286 positive, 3 explicit zero, 6 missing of 295. Centroids with positive activity: C 3,086 of 3,142 (56 with no record), S 100 of 100, G 248 of 255 (3 zero, 4 missing).
- Connector counts per centroid: C 2,885 with 1, 257 with 2; S 99 with 1, 1 with 2; G 219 with 1, 34 with 2, 1 with 3, 1 with 5.
- The 100 S centroids belong to 45 parent counties; only one of those 45 parents also has two connectors. Los Angeles: parent 06037 plus five S centroids; the parent has one connector and no matching 2022 flow record.
- Why S got no direct OD: the BTS county disaggregation guide (`UserGuide_48_51_countydisagg.pdf`, section 5.2) stops at county FIPS. ResiFlow multiplies origin and destination factors (`src/resiflow/faf5_conus_county_od.py`, around line 165) to get county-pair demand and loads one node per county.
- Endpoint-only connector access (separate departure and arrival vertices for official centroids, no through-routing) already exists on this branch (`CONNECTOR_ENDPOINT_ACCESS.md`). The initial Test 1 run crossed its 0.1% shortcut threshold. The endpoint-only rerun at `682cf95` cleared the gate: Hopper job `3735397` had zero shortcuts across 1,844,969 baseline paths, and job `3735398` had zero shortcuts in all 12 recovery exports (disrupted and reference paths at six checkpoints).
- Link totals constrain endpoint activity but not destinations: many OD matrices fit the same totals. Allocated destinations are model estimates, not FHWA's.
- The published link tables include AB and BA flow. The `faf5_native_connectors_2022` layer in `faf5_2022_assignment_review.gpkg` already carries AB/BA trip and tonnage fields by market. Verify which topology end is the centroid before translating AB/BA to outbound/inbound. Use the original tables for directional commodity detail where available.
- OD node ids must be the corrected numbering (register F6). Haul check before any run (`scripts/diagnostics/haul_length_check.py`). Profile every Hopper run (`experiments/common/profile_stage.sh`).

## 3. Method

### Phase 2a: C + S split (Harris and LA first, then all 45 parents)
1. For each county i let A_i = {c_i} union S_i. From the directional 2022 connector flows (and the connector's endpoint orientation) estimate O_c, trucks per day leaving c onto the network, and I_c, trucks arriving from it. Do it by market and commodity group where published.
2. Outbound share p_ic = O_c / sum over A_i of O; inbound share q_ic = I_c / sum over A_i of I. Counties without S get share 1 at c_i.
3. For county-pair demand D_ij (existing OD, unchanged): D_ijcd = D_ij * p_ic * q_jd for c in A_i, d in A_j. Keep each commodity and market total where those keys are retained.
4. **Missing parent record**: if c_i has no 2022 record (LA), the default is to treat it as unknown, not zero. Run two variants and report both: (a) parent weight zero, all county demand to S; (b) parent weight equal to the mean of its S centroids. Do not pick silently.
5. Roll-up gate: summing the new OD back to counties must reproduce the original county OD exactly (per commodity and total), tolerance 1e-9 relative.
6. Haul-length check on the fitted OD against the county-level OD (mean haul must stay within 2 percent unless the report explains why).

### Phase 2b: G (separate allocation, after 2a passes)
1. Match G centroids to FAF zones with a facility crosswalk (needs building; the facility-range ids do not map to counties directly; check the NTAD intermodal facilities file `NTAD_Intermodal_Freight_Facilities_Air_to_Truck_...gpkg` in the same data folder).
2. Allocate the appropriate existing freight legs (imports, exports, and the matching inbound/outbound regional zone-pair flows) to G using published directional activity. Preserve regional zone-pair, commodity and market totals. Treat explicit zeros (3 centroids) and missing records (4 centroids) separately and document each fallback. Do not force positive load at a centroid that has no positive published evidence.
3. Same conservation and haul gates as 2a.

### Phase 3: assign and verify
1. Run the fitted OD (2a alone, then 2a+2b) through endpoint-only assignment on the Harvey-15 subset, same settings as test 1 (15 iterations, 8 CPUs, `streaming_arrays`), then Anaheim as the regression testbed.
2. Gates (stop and report on any failure): conservation of total demand; zero shortcut paths (no path traverses a centroid that is not its origin or destination); intended centroids have positive assigned connector flow; shared physical capacity respected; unassigned demand per iteration not worse than test 1.
3. Metrics: assigned connector flow versus published 2022 connector totals (calibration target; report correlation and relative error by centroid class); surrounding road-link flow correlation with the published assignment on shared links (class-aggregated; this is the check, not a tuning target); LA and Harris specifically; isolated trips day 0 and 7 for the Harvey stage 4 rerun.

## 4. Out of scope
Passenger OD, payload changes, any edit to `road_revised.py` beyond what the existing endpoint-only access already did (stop and report if something else is needed), recovering FHWA's original destinations, tuning shares to improve agreement.

## 5. Deliverable
`docs/handoffs/CONNECTOR_TEST2_SG_RESULT.md`: goal, method, prior knowledge, then tables, the two LA parent variants side by side, every fallback used, and a plain recommendation. Report negative results. Allocation files go under `parameters/` or `Claude outputs/` per the repo's norm, not into the OD builder defaults, until the owner approves.

## 6. After this test passes (not Codex's scope, owner sequencing)
Resume the final result program: freight-only, passenger-only (the `pax_cty1_*` runs, already submitted), then combined freight plus passenger with truck PCE 2.0 (capacity only), then regenerate the paper figures from the registry (`results/viz/figlib/`). Combined runs depend on `fix/vehicle-classes` being merged, which is on hold.

## 7. Ledger
Update the existing row `.worktrees/connector-loading-test1` to add "test 2: S and G allocation" to its scope and refresh Last synced; no new branch unless the owner confirms a fork.
