# How much does connector speed matter? A CONUS measurement, and how it differs from Anaheim

Written 2026-11-11. Script: `scripts/diagnostics/connector_exit_sensitivity.py` (about 3 minutes on a laptop; shortest paths only, no assignment, no capacity).

## Question

If the FAF5 Class 50 centroid connectors go back into the routing network, connector capacity will be set non-binding (decided). Does the connector speed (FAF's own value is 25 mph for all 3,795) change which connector a county's trips use to reach the road network?

## Method

Restore the native connectors onto the current road graph: the 483,599 road links plus 3,795 connectors give 487,394 edges, exactly the native link count. Each connector's road end snaps to the nearest road node
(median 25 m, p99 97 m, max 176 m). Road time = length / `AB_FinalSpeed` (median 40 mph); connector time = native length / connector speed. For each of the 257 county centroids that have 2 connectors
(all have exactly 2), compute the shortest path to every county centroid (3,142) at connector speeds 25, 30, 35 mph and at about zero cost, and record which connector the path leaves by.
Tonnage weights are the 2022 county-to-county truck tons from the OD build (965 million tons leave these 257 origins).

## Results

| Measure | Value |
|---|---|
| Connectors per centroid (county FIPS) | 3,203 have 1, 257 have 2 (these are the ones tested) |
| Connector length at the 257 (miles) | shorter one median 2.0, longer one median 3.7 |
| Destinations using the busiest connector at 25 mph | median 89% (range 51% to 100%) |
| Exit changes, 25 to 35 mph, share of destinations | median 0%, mean 5.8%, max 100% |
| Exit changes, 25 to 30 mph, tonnage-weighted | 6.5% of the tonnage from these origins; 13 of 257 centroids change more than 10% of their tonnage |
| Exit changes, 25 to 35 mph, tonnage-weighted | 8.8%; 24 of 257 centroids above 10% |
| Exit changes, 25 mph to free access, tonnage-weighted | 15.6%; 75 of 257 centroids above 10% |
| Paths that pass through a centroid node (undirected graph) | 14 of 803,382 |

Most sensitive centroids (share of their tonnage that changes exit at 35 mph): FIPS 13051 (Chatham GA, connectors 0.15 and 0.70 mi) 99.8%, 40017 95%, 48325 84%, 48303 80%, 27089 71%.
They are near-ties between two connectors; the choice between them is decided by small time differences and by where each connector joins the road network.

## What this means

- A centroid with one connector (92% of them) has no exit choice: the connector speed adds the same time to every trip and does not change any route.
- At multi-connector centroids, one connector usually carries most trips (median 89%), and the destination direction decides the split, as expected. Speed matters in a few places (about 24 centroids at 35 mph).
- Through-routing via centroids is negligible at 25 mph, but the 14 cases show it can happen; a leaf-only rule is still the safe design.

## How Anaheim differs (so its results would not transfer)

| | Anaheim testbed | CONUS (FAF5) |
|---|---|---|
| Connectors per zone | median 4 (min 2, max 4) | 1 for 92% of centroids; 2 for 257 county centroids |
| Connector length | median 0.25 mi, max 1.0 | median 1.06 mi, p99 12.8, max 35.7 (outside AK/HI) |
| Connector speed | 30 to 100 mph (artificial) | 25 mph, all 3,795 |
| Connector capacity | 5,400 to 12,600 veh/h | no lanes and no capacity in the native data |

## Caveats

Free-flow all-or-nothing only (no congestion, which would shift choices further); road speed from `AB_FinalSpeed`; tonnage weights are by origin county pair, not by SCTG group; the 37 gateway or
sub-county centroids with 2 or more connectors and the destination side of connectors are not separately analysed.
