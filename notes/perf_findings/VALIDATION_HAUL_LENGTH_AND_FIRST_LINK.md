# Validation findings: haul length against FAF, the saturated ramps, and the solo-connector load

Written 2026-11-11. Scripts in `scripts/diagnostics/`: `haul_length_check.py`, `saturated_ramps_vs_od_nodes.py`, `first_link_load.py`.
Nothing here is a model run; all three are computed from the files and a free-flow shortest-path prototype.

## 1. Haul length against the published FAF figure (first validation gate)

FAF5.7.1 publishes truck ton-miles (`tmiles_2022`). Average truck haul in 2022 = ton-miles / tons.

| Source | Mean haul (miles) | Median (mi) | Share of flow over 1,500 mi |
|---|---|---|---|
| FAF5.7.1 published (road distance, all trade types / domestic only) | 186 / 169 | | |
| OD as built, nodes at their intended positions (straight line) | 169 (193 excluding same-node pairs) | 85 | 1.0% |
| OD as run, same ids read in the current numbering (straight line) | **909** | 792 | **20.4%** |
| Corrected OD (re-snapped nodes, straight line) | 169 (193) | 85 | 1.0% |

Straight-line distance understates road distance by roughly 15 to 25%, so the intended and corrected OD agree with FAF; the OD as run does not (5 times too long).
This check would have caught the numbering mismatch on day one. It should run on every OD file before a model run: pass if the weighted mean straight-line haul is within about 25% of the FAF figure.

## 2. The saturated ramps are not the county loading nodes

The 23 edges that saturated in iterations 1 to 4 (logged by the blocked-edge diagnostic): 20 are Class 22 "Ramp" and 3 Class 21 "System Ramp"; 22 are freeway-tier, 1 arterial-tier; all are single-lane.
**None of the 23 touches an OD (county) node.** They are interchange links on long-haul paths. With the OD scrambled (previous section), flows crossed the country between random points and funnelled
through single-lane ramps whose modeled capacity is 2,400 vehicles per lane-hour for 24 hours (57,600 per day).
The OD nodes as run were random road nodes: 55% touch a ramp link, in line with ramps being 27% of all links.

## 3. The solo connector under the restored-connector design (free-flow all-or-nothing, 25 mph connectors, native attachments)

296 county origins (the 150 largest by tonnage and 150 random), each to all 3,142 county destinations, weighted by 2022 county-pair truck tons:

| | Largest 150 counties | Random 147 counties |
|---|---|---|
| Share of a county's tonnage on its busiest first road link | median 77% (p10 51%, p90 100%) | median 84% |
| First links needed for 90% of tonnage | median 2 | median 2 |
| Class of the busiest first link | arterial 76%, ramp 14%, local 7%, frontage 2%, freeway 1% | arterial 94%, ramp 5% |
| Freight-only load on that link as share of modeled capacity | median 3%, p90 9%, max 21% | median 0% |

So a single connector does funnel most of a county's freight onto one or two links, but they are mostly arterials, and freight alone stays well below the modeled capacity.
The concern is realism, not saturation: Los Angeles County would put about 14,700 trucks per day on one arterial link (77% of its tonnage), where real origins spread over thousands of places.
Spreading the load across sub-county centroids (Los Angeles has 9) is the natural remedy and matters far more for passenger demand (the busiest passenger node touches 2.1 million vehicles per day).

## 4. Validation still to build

| Quantity | Reference | Status |
|---|---|---|
| Average haul and ton-miles by zone pair | FAF `tmiles` | done for the national mean (section 1); zone-pair level not yet |
| Free-flow route times and distances | an independent router on a sample of county pairs (open routers such as OSRM or OpenRouteService with a truck profile; commercial sources such as HERE or TomTom need a licence; NPMRDS truck speeds need the FHWA data agreement) | not started |
| Assigned truck flows on links | HPMS truck AADT (combination and single-unit) | not started; the FAF-to-HPMS link match was about 22% nationally in the pilot (`docs/HPMS_FAF_LRS_TRANSFER.md`) |
| Where freight enters at ports, airports and borders | gateway counts (TransBorder, port tonnage, airport cargo) | not started |
