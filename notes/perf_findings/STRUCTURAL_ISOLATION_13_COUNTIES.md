# Structural isolation in the freight-only run is 13 counties on disconnected network fragments

**Date:** 2026-11-11. **Goal:** explain the 5,445.69 trips (0.36% of 1,513,650) that every freight-only run reports as structurally isolated in iteration 1. **Method:** treat the road network (483,599 links, patched network md5-identical on Hopper and Anvil) as an undirected graph, find weakly connected components, and sum OD flow whose two ends fall in different components. The county of each OD node comes from `parameters/crosswalks/county_node_crosswalk_conus_single_node.csv`.

## Result

| Quantity | Value |
|---|---|
| Nodes / links | 344,999 / 483,599 |
| Weakly connected components | 170; largest has 343,688 nodes (99.62%), second largest 702 |
| OD flow between different components (non-intrazonal) | **5,445.690** |
| Model log `Non_allocated_flow` (iteration 1) | 5,445.690477 |
| Counties whose OD node is outside the largest component | 13 |

The two numbers agree to three decimals, so the structural isolation is fully explained by these 13 counties. Every OD node is present in the link graph (0 missing).

**A hypothesis that was wrong:** that Alaska and Hawaii cause the isolation. Their nodes sit inside the largest component. Flow with an AK/HI end is 2,900 trips and is delivered normally.

## The 13 counties (node sits on a tiny fragment)

| County FIPS | Node | Component size rank |
|---|---|---|
| 01071 | 484 | small fragment |
| 04009 | 1049 | small fragment |
| 08061 | 67751 | small fragment |
| 08087 | 395 | small fragment |
| 08089 | 231862 | small fragment |
| 13125 | 366 | small fragment |
| 13211 | 34687 | small fragment |
| 17053 | 445 | small fragment |
| 21023 | 275197 | small fragment |
| 21059 | 972 | small fragment |
| 22023 | 857 | small fragment |
| 27161 | 1288 | small fragment |
| 36015 | 1162 | small fragment |

(From my memory of the FIPS codes, not from the data: Jackson AL, Graham AZ, Kiowa/Morgan/Otero CO, Glascock/Morgan GA, Ford IL, Bracken/Daviess KY, Cameron Parish LA, Waseca MN, Chemung NY. Fragment sizes in the source run are 3 to 131 nodes.)

## Why it matters

- This is a snapping problem: each county's OD node landed on a piece of network that does not connect to the main network. Re-snapping those 13 nodes to the main component would recover 5,446 trips (0.36%). It is the cheapest topology fix available, and it is the same family of problem as the connector work.
- It also shows the structural isolation is independent of capacity, algorithm and platform, which matches every run so far giving the same number.

## Not verified

- Whether the 13 nodes can be re-snapped to a nearby main-component node without changing any intended road semantics.
- Whether the Hopper copy of the network has the same components (the files are byte-identical by checksum, so it should).
