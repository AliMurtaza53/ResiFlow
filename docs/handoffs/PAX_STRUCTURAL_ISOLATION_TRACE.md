# Trace: 61,352 structurally isolated trips in the CONUS split run (2026-11-17)

## Goal
Explain why `pax_cty1_conus_split` has 61,352 structurally isolated trips (0.12% of 51.72M) while `pax_cty1_conus_base` has none.

## Method
- Read-only on the pulled run outputs (`Claude outputs/pax_cty1_runs/`), the OD files (`passenger_od_county_oneway/`) and the connector crosswalk; one read-only connectivity query on Hopper (`faf5_road_links.gpq`, two columns, no job).
- "Structural" = demand with no path (or an absent node) at iteration 1 (`road_revised.py` iteration log).

## Prior knowledge
Split spreads 256 two-connector counties 50/50 over both connector road ends. The split changed delivery by at most 0.05 points; structural isolation appeared only in the split run (iteration 1: 61,352.0452 trips, 5 origins with no out edges in both runs).

## Findings
1. Exactly one node is isolated in full: road node **55804**, as origin (41,971.776 trips) and as destination (19,380.269 trips). Sum = **61,352.045**, identical to the iteration-1 structural figure. Nothing else is structural.
2. 55804 is one of the two road ends of the connector for **county 53011 (Clark County, WA)**: crosswalk rows `306463 -> road node 55804` and `306464 -> road node 55797` (centroid 398010). The split sends half of Clark County's demand to each end.
3. In the network, 55804 has **1 outgoing link, 0 incoming links**, and sits in a 2-node weak component (strong component size 1). The other end, 55797, is in the main component (301,160 nodes in the largest strong component). So 55804 is an orphan stub: demand can neither reach it nor leave it.
4. The base run does not use 55804, so it has no structural isolation.

## Conclusion
Not a model or capacity effect. The split builder picked a connector road end that is not connected to the road network. The correct handling for this county is to put 100% of the demand on 55797 (the connected end).

## Recommendation (not implemented, owner to approve)
- In `scripts/diagnostics/prepare_passenger_od_variants.py`, drop any split end that is not in the largest strongly connected component, and send its share to the connected end. Log each dropped end.
- Audit the 255 other split nodes the same way (none showed full isolation here, but a partial or one-way stub would show only as congestion isolation).
- The same check belongs in the connector pipeline Codex is building (official connectors, endpoint-only access): a gateway or sub-county centroid attached to a stub gets zero effective demand.
- Delivery numbers in `PAX_CTY1_RESULT.md` stay valid; only the 0.12% label changes from "unexplained" to "stub connector end, Clark County WA".

## Files
Probe script: scratchpad `probe55804.py` (not committed). Inputs named above.
