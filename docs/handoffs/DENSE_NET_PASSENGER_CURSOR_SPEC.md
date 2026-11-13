# Dense network and sub-county passenger zones: pilot (handoff spec for the Cursor agent)

Written 2026-11-12. Bounded mandate: a small pilot, a written comparison, then stop and report. Owner idea: replace county-centroid loading on the FAF5 network with a much denser network (OSM or similar, collectors and up) and passenger demand at sub-county zones, to learn what the centroid and network choices do to results.

## 1. Question
How much do passenger link flows, travel times and hazard rerouting cost change when the same passenger demand is loaded (a) at county centroids on the FAF5 network, versus (b) at sub-county zones on a dense network that keeps collectors and above, joined by explicit centroid connectors?

Learning targets: sensitivity to centroid placement and connector design; whether FAF5 undercounts local/collector capacity; what zone size is needed before results stop changing; runtime and memory cost of density (for Hopper planning).

## 2. Prior knowledge (do not re-derive)
- The converted FAF5 network has **no centroid connectors**: all 3,795 Class 50 links were dropped; the OD builder snaps each county to the nearest suitable road node, one node per county. See `notes/perf_findings/FAF_CENTROIDS_AND_DISAGGREGATION_AUDIT.md` (native counts, 3,497 unique loading centroids, multi-connector centroids).
- Passenger demand today: LODES8 home-to-work, county to county, `S000` jobs as the daily person-trip proxy; within-county disaggregation was deferred. See `docs/lodes_passenger_module.md`, `src/nird/lodes_county_od.py`, `scripts/build_lodes_passenger_od.py`. LODES is published at census-block level, so sub-county zones (tract or block group) need only a different crosswalk aggregation.
- Assignment: `src/resiflow/road_revised.py` (`network_flow_model`). The Anaheim testbed (416 nodes, 38 zones, 118 centroid connectors) already has explicit connectors and a UE setup; see `docs/testbeds/tntp_adapter.md`.
- Everything is in EPSG:9311 internally (see `docs/ASSUMPTIONS_REGISTER.md` H4). Reproject any OSM data into it. FAF links carry NAD27-shifted coordinates, so match against the stored network, not raw NAD83.
- Hopper runs at CONUS or semi-CONUS scale must be profiled (`experiments/common/profile_stage.sh`). This pilot should stay small enough to run on a laptop or one Hopper node.

## 3. Method (suggested, adjust and say so)
1. **Pick a pilot area**, small and well known. Suggested: Orange County, CA (Anaheim testbed already exists for comparison), or one Texas metro county if the owner prefers Harvey relevance. State the choice and why.
2. **Dense network**: OSM drive network for the area (osmnx or a Geofabrik extract), keep `motorway`, `trunk`, `primary`, `secondary`, `tertiary` and their links (collector and up), contract degree-2 nodes, map classes to HPMS F-class with the rule in `src/resiflow/testbeds/assets.py` (add classes there only through a test). Free-flow speed and lanes from tags with documented defaults.
3. **Zones**: census tracts (try block groups as a second run). Zone centroid = population-weighted or geometric centroid, say which. Connectors: link each centroid to the K nearest collector-or-above nodes within a radius, non-binding capacity, length from geometry. Document K and the radius, and test two values.
4. **Demand**: LODES block OD aggregated to the zones, same year and same job-count proxy as the county run.
5. **Baseline for comparison**: the same pilot area's county-to-county demand on the stored FAF5 network (existing pipeline), and the Anaheim TNTP result if Orange County is used.
6. **Assign** both, UE with the same convergence settings, and compare: link flow correlation on shared roads (class-aggregated, since segments differ), total vehicle-km and vehicle-hours, volume over capacity by class, and the share of flow on collectors. Then run one synthetic flood or closure scenario on both and compare rerouting cost.
7. **Sensitivities**: connector K, zone size (tract vs block group), and with versus without collectors.

## 4. Deliverables
- A short report `docs/handoffs/DENSE_NET_PASSENGER_RESULT.md` on branch `exp/dense-net-passenger`: goal, method, prior knowledge, then tables and a plain recommendation (what zone size and network density is worth it, and the runtime and memory cost per 1,000 links).
- Scripts under `scripts/experiments/dense_net/` (new directory, no edits to existing scripts). Tests for any helper you add.

## 5. Constraints and boundaries
- Own worktree and branch off the current tip of `feature/anaheim-assignment-diagnostics`. Do not edit `src/resiflow/road_revised.py`, `scripts/3_damage_analysis.py`, damage or disruption modules, parameters, or the Harvey job scripts. If a core change looks necessary, stop and report it.
- No CONUS-scale runs and no Hopper submissions without the owner confirming. The Harvey rerun is using Hopper; do not compete with it.
- OSM data stays out of git (`inputs/` is ignored); commit only code, small summaries and the report.
- Report negative results too. Do not tune connectors to make the two runs agree.

## 6. Ledger row to add to AGENTS.md (the owner edits AGENTS.md)
| `exp/dense-net-passenger` | Cursor (dense-network pilot) | `scripts/experiments/dense_net/`, report in `docs/handoffs/` | Active | 2026-11-12 |

## 7. Why not in the main pipeline yet
Whatever this teaches feeds the structural fix for centroid loading (key the OD by real centroid ids, restore connectors). Doing the pilot separately keeps the Harvey run and the testbed suite on stable code.
