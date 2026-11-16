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

Each job profiles assignment and checks for zero exported baseline shortcuts. Remaining gates include positive assigned connector flow at intended centroids, shared physical capacity, unassigned demand against Test 1, and recovery and Anaheim verification. The two assignment jobs precede recovery and any G allocation.
