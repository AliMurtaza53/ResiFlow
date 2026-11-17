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

## Audit of the other split ends and fix (2026-11-17)
- Against the **largest weakly connected component** (343,688 of 344,999 network nodes), exactly **one** connector end is outside it: 55804. The other 255 split nodes (511 ends) and all 493 unsplit county loading nodes are inside.
- Do NOT use the largest strongly connected component as the test: 57 split ends fall outside it, but only 55804 was isolated in the run, so link-direction flags make strong components over-reject. (The first version of this note recommended the strong component; that was wrong.)
- Fix: `resiflow.demand.connector_split.main_component_nodes` + `build_node_targets(..., valid_nodes)` drop ends outside the main component; the share goes to the remaining ends. A county left with one valid end loads at its own node (same as base); a county with none valid keeps all ends. `prepare_passenger_od_variants.py --network-links <faf5_road_links.gpq>` applies it and prints the dropped ends. Tests in `tests/test_connector_split.py` (5 pass).
- Effect: the split OD files must be rebuilt with `--network-links` before the next passenger run; existing results are unchanged (the 0.12% structural label is now explained).
- Codex's gateway and sub-county centroids need the same island check.

## Files
Probe script: scratchpad `probe55804.py` (not committed). Inputs named above.
