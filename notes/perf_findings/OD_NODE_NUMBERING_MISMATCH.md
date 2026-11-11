# The OD node ids and the road network use different node numberings

**Date:** 2026-11-11. Replaces `STRUCTURAL_ISOLATION_13_COUNTIES.md`, whose explanation (13 counties on disconnected fragments) was wrong.

## Goal, method, what was known

- **Goal:** explain the 5,445.69 structurally isolated trips (0.36%) in every freight-only run, then make the OD conterminous.
- **Method:** compare each county's OD node with (a) the county's true centroid, (b) the state label of the road links at that node, using three node/link files that exist locally and on Hopper/Anvil.
- **Known beforehand:** OD node ids exist in the road network, so nothing ever errored.

## Evidence

| Test | Result |
|---|---|
| OD node location in the **old nodes file** (May 28, local `faf5_road_nodes.gpq`) vs county centroid | median **1.7 km**; 99.8% within 25 km |
| OD node location in the **Oct-23 nodes file** (Hopper/Anvil) vs county centroid | median **1,386 km**; 0.6% within 100 km (about chance) |
| Links' first coordinate vs `from_id` node, Oct-23 nodes | median 29 m; 99.6% within 100 m (the links belong to this numbering) |
| Links' first coordinate vs `from_id` node, old nodes | median 1,484 km (they do not) |
| Counties whose OD node touches a link labelled with the county's own state | **2.9%** (91 of 3,109), the same for the May-28, Sep-24 and Oct-23 links files |
| Same node ids, same positions? | Same 344,999 ids; positions of the two numberings differ by a longitude-dependent 13-70 m offset; matching by coordinate is not one-to-one (38,418 collisions) |

So the OD uses an older numbering and the links use a newer one. The pair runs without error, but every county's demand enters the network at an unrelated place. Examples: Autauga County AL sits on Arkansas links, Baldwin AL on Oregon links, all 30 Alaska and all 5 Hawaii county nodes are mainland nodes.

The "13 isolated counties" are a by-product: the small disconnected fragments hold 0.38% of the nodes, and 3,143 random draws are expected to put about 12 of them there.

## Consequences (not yet re-run)

Every Hopper and Anvil run so far (Stage 1, 1b, 2, the dump probes, all earlier combined baselines and the hazard stages built on them) used geographically scrambled OD. Computational findings (iteration counts, timings, memory, strategy equivalence) stand as measurements of those runs, but anything geographic does not: state totals, the ramp-saturation pattern (the saturated ramps in AR, MO, OH, IA may be an artifact of random long-distance OD pairs), hazard exposure, rerouting. Whether the slow freight tail survives a correct OD is the next experiment.

## Fix (`scripts/make_conterminous_od.py`)

1. For each distinct OD node, take its true location from the old nodes file.
2. Snap to the nearest eligible node of the current network: main connected component, no freeway-tier or ramp-class link, not used by another OD node (KD-tree, projected metres).
3. Rewrite the OD node ids. Drop Alaska and Hawaii (the study is the conterminous US); report the dropped flow.
The road network is not edited.

| Result on the real data | Value |
|---|---|
| Snap distance (km) | median 0.028, p90 1.44, p99 12.1, max 50.9 |
| Counties on links of their own state | 2.9% -> **99.8%** |
| New node vs county centroid (km) | median 2.0, p99 18.9 |
| Freight OD flow | 1,735,334.699 -> 1,729,652.527 (AK/HI dropped: 5,682.172; non-intrazonal supply for the model: 1,513,649.919 -> 1,510,749.556 expected) |
| Freight flow between disconnected components | 5,445.690 -> **0.000** |
| Passenger OD flow | 147,181,931 -> 146,261,048 (AK/HI dropped: 920,883); between-component 147,203 -> 0 |
| Conservation residual | about 1e-10 |

Outputs (not in git; 90 MB): `census_datasets_conterminous/faf5_od_matrix_conterminous.pq`, `lodes_passenger_od_matrix_conterminous.pq`, `report.json`. In git: `parameters/crosswalks/county_node_crosswalk_conterminous.csv` (county, state, node in the CURRENT network's numbering, 3,109 counties) and `conus_od_node_remap.csv` (old node, new node, distance).

## Not verified

- No model run on the corrected OD yet (a freight-only probe is the cheap confirmation: structural isolation should print 0 and the tail should be re-measured).
- Which numbering the older Hopper combined baselines used is not established; the files on Hopper and Anvil that I checked all show the mismatch.
- `county_node_crosswalk_conus_single_node.csv` is in the OD's (old) numbering; use the `_conterminous` file with the corrected OD.
- Why the numberings diverged (renumbering during the Oct harmonization is a hypothesis, not established).
