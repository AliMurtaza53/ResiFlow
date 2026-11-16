# FAF5 Test 2a preflight and submission

Test 2a reallocates Harvey-15 freight from parent county centroids to their parent and sub-county centroids. The endpoint-only solver is pinned to the Test 1 checkout at `682cf95`. Facility-range allocation follows the Phase 2a assignment gates.

The ordered native node rows match both geometric endpoints of all 3,795 original Class 50 links exactly. The centroid is at the first (A) end on 2,694 links and the last (B) end on 1,101. The exporter uses that orientation to translate AB and BA flows into outbound and inbound totals. The exact Harvey-15 solver input has only origin, destination, and aggregate trucks/day. Market directions are retained as evidence and all-market flows supply the pilot shares. Commodity- and market-specific rollups require a keyed OD source.

Both full allocations conserve all 889,997.819056 trips/day at each original OD pair within 1e-9 relative tolerance. They split 35 Harvey-15 parent counties. Both haul checks use weighted geodesic distance for the same original inter-county pairs.

| Scope | Control, miles | ±2% go window, miles | Missing parent zero, miles | Missing parent mean, miles |
|---|---:|---:|---:|---:|
| Harvey-15 | 174.6889 | 171.1951–178.1827 | 174.7545 | 174.7201 |
| Los Angeles-related pairs | 256.3345 | 251.2078–261.4612 | 256.5427 | 256.4555 |
| Harris-related pairs | 214.0289 | 209.7484–218.3095 | 214.4964 | 214.4084 |

The full product split would activate approximately 52,482 (zero parent) or 63,813 (mean parent) previously same-node trips as inter-centroid movements. For this assignment comparison, both inputs retain the exact Test 1 routable scope of 754,974.302225 trips/day from original inter-county pairs. The full allocations are retained separately.

| Sensitivity | Assigned-input rows | Hopper job |
|---|---:|---:|
| Missing parent weight zero | 1,966,330 | 3764994 |
| Missing parent weight mean | 2,065,563 | 3764996 |

## Baseline assignment and recovery submission

Both assignment jobs completed and delivered 754,974.302225 trips in one iteration, with zero isolation, zero residual demand, and zero physical-link capacity violations. The zero and mean variants had zero shortcuts across 1,966,330 and 2,065,563 paths, respectively. All 1,403 intended centroids in the zero variant and all 1,438 in the mean variant had positive accumulated connector flow.

Hopper recovery jobs are `3765325` (zero) and `3765326` (mean). Each uses its own recovery database and output directory. Both use the Test 1 hazard and cost settings and audit the baseline plus the disrupted and reference paths at each recovery checkpoint.

## Agreement with the published 2022 FAF5 assignment

The comparison uses accumulated model trips/day joined to the published bidirectional link flows by native link ID. All three arms use the same link support in each row. Missing published records are kept out of the metric and published zeros are included. The pilot footprint is the union of road links with positive modeled flows in any arm.

| Fixed comparison support | Links with published records | Pearson, parent only | Pearson, zero | Pearson, mean |
|---|---:|---:|---:|---:|
| All shared road links | 312,073 | 0.4343 | 0.4694 | 0.4673 |
| Road links in the pilot footprint | 116,284 | 0.4407 | 0.4867 | 0.4835 |
| LA road links | 4,360 | 0.3673 | 0.5564 | 0.5305 |
| Harris road links | 3,351 | 0.3354 | 0.5135 | 0.4949 |
| County connectors | 3,338 | 0.4562 | 0.4564 | 0.4564 |
| Sub-county connectors | 101 | Undefined | 0.6093 | 0.6747 |
| Facility-range connectors | 289 | Undefined | Undefined | Undefined |

Sub-county connector weighted absolute relative error was 100% in the parent-only arm, 60.65% in the zero arm, and 54.69% in the mean arm. It is computed as the sum of absolute link-flow errors divided by the published flow sum. Pearson correlation is undefined when modeled flow is constant. Connector flows informed the allocation, so connector agreement serves as a calibration check. The road-link comparison is an independent diagnostic of the resulting route volumes. Absolute error includes the volume difference between the Harvey-15 demand subset and the national published assignment.

The comparison script `scripts/diagnostics/compare_faf_subcounty_flows.py` also writes class-specific and LA/Harris centroid results. Recovery and Anaheim verification remain pending.
