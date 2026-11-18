# C+S+G GIS review and sealing decision — 2026-11-17

## Decision

**Hold the Harvey C+S+G seal.** The freight OD allocation and intact-baseline mechanics pass, but an extended audit found that flood exposure of synthetic Class-50 centroid lines closes 41 connectors serving 39 centroids. All 41 have `damage_level_max=no`. This is a distinct operational-exposure issue; it is not the resolved Clark County passenger stub.

Freeze the current freight inputs as a versioned experimental allocation. Correct the treatment of virtual links in hazard exposure and rerun the matched stages 2–4 before accepting the Harvey comparison. Combined passenger/freight acceptance also remains outstanding.

No production routing, allocation, hazard rules or parameters were changed for this review. New compute work exported artifacts and audited saved results.

## Delivered GIS package

Local folder: `C:/Users/akothaw/Documents/ChatGPT/Transport Network Analysis/CSG_GIS_Review_20261117/`.

- `CSG_review.gpkg`: 58 layers, approximately 4.1 GB; ArcGIS Pro/QGIS compatible.
- `CSG_review.qgs`: relative-path styled QGIS project, initially over Houston.
- `DECISION_REPORT.html`: complete decision checks, comparison tables and route preview.
- `README.md`: layer/field meanings, sampling rules, scopes and limitations.
- `manifest.json`, `provenance.json`: feature counts, job IDs, source paths, validation and SHA-256.
- 12,090 individual path features: actual routed edge geometries and ordered edge-ID JSON, not straight OD desire lines.
- Complete baseline physical-road/connector comparison, all 3,497 official centroids, eight retained Connecticut road loading points, native facility reference points, county isolation polygons, flood damage and affected synthetic connectors.

Start with `synthetic_connectors_closed_by_flood`, `centroids_affected_virtual_flood_closure`, `n_g_d0_pre_paths`, `n_g_d0_post_paths`, and `n_g_d0_isolated_baseline_paths`.

Individual route features are a deterministic review sample: 250 highest-flow IDs plus the highest-flow route at each loaded G origin and destination. Recovery layers select identical OD pairs within each arm/day. Isolated-route layers separately recover intact routes for selected lost-service OD pairs. Paired recovery baseline exports intentionally exclude isolated trips.

Days 0, 7 and 90 have spatial path/cohort-edge layers; all six days have full-export statistics. Complete original path Parquets remain on Hopper; the manifest records their locations. C+S versus C+S+G endpoints differ, so neither `od_id` nor OD node pairs should be treated as a cross-arm join key.

## Original allocation and baseline checks

All original mechanics checks passed:

- Original routable trips/day: CONUS 1,510,749.556669; Harvey-15 754,974.302225.
- Cell conservation tolerance: 1e-9 relative for FAF zone-pair, commodity and market; maximum absolute residuals 1.42e-13 and 3.41e-13 trips/day.
- Mean geodesic haul: CONUS 193.1300 → 193.8684 miles (+0.3823%); Harvey-15 174.7201 → 175.6595 (+0.5377%). Both satisfy the predeclared ±2% window.
- Complete first-pass baseline assignment, no binding links or baseline isolation.
- Exact matched physical capacities; maximum permitted numerical exceedance 1e-6.
- Zero non-endpoint centroid shortcuts in all baseline audits and all 48 paired recovery path sets.
- Maximum reported freight-only physical access-road V/C: 0.08794 CONUS, 0.08632 Harvey-15.
- Ten existing endpoint/Anaheim regression tests passed locally at source revision 6afc118, including intact and deliberately closed-origin access. This is a focused routing/source-data regression, not a congested combined assignment.

Inventory C/S/G = 3,142 / 100 / 255. Positive CONUS loads occur at 3,100 C, all 100 S and 238 G. Harvey-15 loads 1,359 C, 79 S and 114 G. G counts refer to either direction; a centroid need not have positive load in both directions.

The ±2% haul gate is flow-weighted straight-line ellipsoidal OD endpoint distance, not realized route mileage. Separately, assigned physical-road miles per trip are 229.9867 → 230.8241 for CONUS and 205.6805 → 206.7410 for Harvey-15, using the model's saved link lengths and excluding synthetic connector mileage. Matched-road VMT excess over FAF22 rises from 28.32% to 28.80%; this uses common modeled link lengths and is not a comparison of independent OD trip counts. See `physical_routed_mileage.csv`.

The nine Connecticut planning-region keys retain eight original road nodes because exact official parent-centroid matches do not exist in the inventory. Node 312022 serves 09120 and 09190. Its aggregated node OD does not permit a unique county split; the GIS retains `CT_shared_09120_09190` instead of inventing one. All baseline origin/destination totals reconcile when these eight road nodes are included.

## Gateway allocation size and limits

CONUS moves 100,886.86 existing trips/day to G, 6.68% of the original routable input. Reconstructed eligible import/export cells contribute 64,320.98 / 57,508.30 trips/day, together 8.06% of the input. These are the cells in the allocation's covered gateway zones and saved routable support, not an assertion about every international shipment in FAF.

Allocated CONUS imports/exports are 56,934.57 / 43,952.29, versus published directional targets 64,981.45 / 46,337.32. Geographic available-demand caps leave 10,431.91 target trips/day unfilled; no extra demand was created to fill them.

Harvey-15 moves 61,480.98 trips/day. The top ten gateways carry 54.78% of allocated CONUS G activity and 69.94% of Harvey-15 G activity.

This G implementation moves import origins and export destinations. It does not reconstruct domestic facility OD or Caliper's facility-to-destination matrix. Connector agreement partly reflects the directional flows used to construct the allocation.

## Published FAF22 agreement: mixed, not an unqualified improvement

Scores use 312,073 common physical road IDs with published records, including 119 explicit zeros. Another 171,369 solver roads lack official records and remain NA. The common solver road universe contains 483,442 links; 157 native road IDs are outside it. Both matched arms restore the same 3,795 connectors.

Full-CONUS results, control → G:

- Pearson: national 0.5794 → 0.5842; LA 0.4758 → 0.5193; Harris 0.4875 → 0.5265.
- WAPE: national 1.1076 → 1.1055; LA 0.9309 → 0.8571; Harris 0.9403 → 0.9867.
- Matched-link traversal excess over FAF22 rises from 25.7% to 26.8%.

WAPE is sum absolute link error divided by sum official link traversals. Link sums count traversals, not generated trips. Higher correlation can coexist with worse absolute error.

In Harris, the two matched gateway-access roads improve absolute error by 9,289 summed traversals/day; other matched roads worsen by 176,225. F1 roads contribute +193,899 before offsets from other classes. The largest increases include an I-610 chain (642076, 642090, 641808, 641804, 641802), gaining about 3,895 trucks/day per link. Link 642076 rises from 6,830 to 10,725 against published 4,631.

This localizes disagreement downstream of access. It does not establish a unique cause or justify moving the gateway connector. Fixed 20-ton payload, eligible OD scope, cost/route choice and FHWA's different disaggregation/assignment methods remain differences. These current matched controls must not be mixed with earlier runs using different integrated vehicle/fuel settings. Harvey-15 demand on the national graph is not like-for-like with full FAF22 demand.

## Extended finding: virtual connector flood closure

Of 74 synthetic connectors intersecting the raster footprint, 41 are wet and closed: 31 C links, three S links and seven G links. They serve 39 centroids; all connectors at each of those 39 centroids are closed. Forty also have zero truck-specific speed.

Houston G 100146 uses connector 633909, assigned 2.571315 m depth and zero speed despite `damage_level_max=no`. Its baseline G flow is 9,286.82 trips/day. Its immediate physical approach, 633911, is dry and open; other downstream physical closures can still cut it off, so those 9,286.82 trips cannot all be called recoverable.

Source inspection confirms flood speed caps apply to the whole link frame, with no Class-50 exemption. Stage 4 consumes that speed restriction. Raster depth along an abstract centroid line is not a physical access-road exposure measurement.

Endpoint-only reachability sensitivities, keeping physical conditions fixed:

- Initial day 0: reopening only virtual links makes paths available to 74.74 currently isolated control trips/day and 53.19 G trips/day.
- Saved day-7 graph: corresponding values are 1,506.00 and 1,388.07.
- The day-7 sensitivity difference exceeds the reported 96.84-trip/day G-versus-control isolation benefit. This does not predict the sign of a capacity-constrained rerun; it makes the current comparison provisional.

These audits do not rerun assignment or claim delivery. Day 7 uses saved post-assignment positive speeds/capacities. Some isolated demand already has a path in that snapshot; path existence alone does not establish sufficient assignable capacity.

## Existing recovery and physical damage results

Raw full-CONUS isolation, control → G: day 0 58,368.44 → 58,309.88; day 7 15,404.42 → 15,307.59; zero from day 14 onward. Harvey-15: 55,687.15 → 55,630.39 at day 0; 13,031.66 → 12,932.20 at day 7; zero from day 14. Treat these as provisional because of the virtual-link policy above.

Direct physical damage is identical across all arms: $1.468883829 billion. Roads contribute about $1.137989 billion (5,302 damaged links), bridges $0.330895 billion (1,235), tunnels zero. Bridge/tunnel whole-structure cost is counted once per link; roads sum cell pieces.

Physical maximum depth: 9.143157 m, below the 9.144 m mask limit. Physical-link median/p95: 0.7002 / 7.0662 m among nonmissing link maxima. There are 7,490 wet physical links; wet virtual lines are a separate category.

Original stage-2 length ratio, including virtual lines: 0.999245910. Physical-only geodesic/projected ratio: 0.999238179, with p01/p50/p99 0.992029 / 0.999153 / 1.006797 for pieces at least 1 m long.

The two isolation-cost columns are alternative valuations, not additive. Repeated direct damage across sampled recovery days must not be summed. Six day snapshots are not a 90-day integrated recovery total.

## Required next steps

1. Preserve current OD and intact baseline outputs.
2. Exempt Class 50 from physical raster damage/exposure and geometry-based speed/closure/recovery restrictions. Continue applying all hazard effects to actual physical approaches.
3. Add dry-road/wet-virtual-link and flooded-physical-approach regressions, plus zero-shortcut and shared-capacity checks.
4. Reuse all four baselines and rerun the paired CONUS and Harvey-15 stages 2–4 under a new output variant. Require unchanged physical damage and physical hazard states, zero virtual geometry closures, complete accounting, and audited recovery paths.
5. Reassess the C+S+G comparison, then apply the combined passenger/freight access-capacity gate. Keep Harris route/destination diagnostics separate from allocation tuning.

## Reproduction and evidence

Original baseline jobs: 3784300 / 3784302 (Harvey-15), 3784304 / 3784306 (CONUS), using recorded integrated experiment revision 19b02b1. Gateway baseline assignments succeeded; their initial follow-up verifier path failed. Saved artifacts were revalidated and replacement recovery jobs completed.

Recovery jobs: 3784301 / 3787728 (Harvey-15), 3784305 / 3787729 (CONUS). All source runs were profiled; the package retains stage TSVs and `profiling_all_stages.csv`.

Review jobs: main export 3790925 (22m 44s), isolated-route sample 3790999, CT exceptions 3791056, day-0 virtual audit 3791078, day-7 snapshot audit 3791088.

Scripts: `export_csg_gis_review.py`, `audit_virtual_connector_flood.py`, `audit_virtual_connector_flood_day7.py`, `finalize_csg_gis_review.py`, and `augment_csg_virtual_findings.py` under `scripts/diagnostics/`. The package also retains isolated-route and CT export scripts. Run initial export/audits, copy their artifacts plus the complete intersection table into a fresh local package, run the finalizer, then run the virtual-finding augmentation. The finalizer uses the existing local assignment-review GeoPackage for reference labels and county geometry.

GIS SQLite integrity and every exported layer's feature count passed after transfer and enrichment. Route samples have zero missing edge geometries. The package's `provenance.json` records the final GIS SHA-256.
