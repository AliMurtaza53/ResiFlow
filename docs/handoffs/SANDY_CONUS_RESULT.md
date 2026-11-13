# Hurricane Sandy on the full corrected CONUS freight baseline (2026-11-13)

## Goal and method
Run Sandy (scenario 305, `flood_sandy_northeast`, masked-free metre raster, 50 m) through stages 2, 3, 3-postprocess and 4 on the finished full-CONUS freight baseline (variant `harvey_conus_corrected`, corrected OD, freight only, passenger off), compare it with Harvey, and test bridge deck clearance (E6). Jobs: primary 3714877 (1.0 m embankment on major roads, stage 4 with OD path export), sensitivity 3714878 (same plus 2.0 m bridge deck clearance, stages 2 and 3 only), path join 3720624. Script `experiments/pass_a_convergence/hopper/submit_flood_conus_stages.slurm`; overrides `sandy_embankment_1m_sourced.json` and `sandy_embankment_1m_clearance_2m_sourced.json`. Code includes the baseline-demand fix (`b2d9f5a`).

## Prior knowledge
Owner decisions 2026-11-13: Sandy gets a 1 m embankment (Harvey's 2 m stays), "major roads" = HPMS F1 (Interstate), F2 (other freeways and expressways), F3 (other principal arterials). Sandy is typed `flood`, so the river embankment parameter (`flood_embankment_river_m`) was set to 1.0. Sandy depths are feet converted to metres (register H1); unlike Harvey, the Sandy raster has had no GIS check for water bodies or artifacts. Baseline and Harvey results: `HARVEY_CONUS_RESULT.md`.

## Footprint and intensity (raster, before the embankment)
| | Harvey | Sandy |
|---|---|---|
| Wet pixels (50 m) | 14.79M (about 37,000 km2) | 1.64M (about 4,100 km2) |
| Median / p90 / p99 / max depth | 1.27 / 5.09 / 8.52 / 9.14 m | 1.72 / 2.94 / 4.16 / 5.52 m |

## Exposure (stage 2, link level, depth after the embankment)
| | Harvey | Sandy | Sandy, 2 m bridge clearance |
|---|---|---|---|
| Flooded links | 7,490 | 3,017 | 2,494 |
| Truck-closed links | 5,623 | 2,509 | 1,958 |
| Flooded: roads / bridges / tunnels | 5,302 / 2,187 / 1 | 2,216 / 793 / 8 | 2,216 / 270 / 8 |
| Truck-closed: roads / bridges / tunnels | 3,904 / 1,718 / 1 | 1,820 / 683 / 6 | 1,820 / 132 / 6 |
| Depth on flooded links, median / p95 / max | 1.27 / 7.65 / 9.14 m | 1.48 / 3.47 / 4.50 m | 1.35 / 3.43 / 4.50 m |
| Flooded links F1-F3 (major) | 4,735 (63%) | 2,443 (81%) | |
| Flooded links F4-F7 | 2,754 (37%) | 565 (19%) | |
| Truck-closed F1-F3 | 3,324 (59%) | 2,013 (80%) | |
| Truck-closed F4-F7 | 2,298 (41%) | 487 (19%) | |
Sandy hits a much smaller area, but a much larger share of it is major roads (dense New York and New Jersey freeway network), and the 1 m embankment removes less depth than Harvey's 2 m. Per-class counts for all classes are in the stage 2 link files.

## Direct damage (sourced costs, each bridge or tunnel counted once)
| | Harvey | Sandy | Sandy, 2 m clearance |
|---|---|---|---|
| Roads | $1,138.0M (5,302 links) | $561.2M (2,207) | $561.2M (2,207) |
| Bridges | $330.9M (1,235) | $253.5M (313) | $22.5M (45) |
| Tunnels | $0 | $9.8M (4) | $9.8M (4) |
| **Total** | **$1,468.9M** | **$824.6M** | **$593.5M** |
Geodesic length check (Sandy): total ratio 0.99967, p01/p50/p99 0.98374 / 0.99899 / 1.01776.
**E6:** a 2 m clearance removes 91% of Sandy's bridge damage (Harvey-15: 48%) and 72% of flooded bridges. Sandy's depths are mostly under 2 m, so the primary bridge figure is an upper bound. Default clearance is unchanged (0 m).

## Freight isolation and rerouting (stage 4)
| Recovery day | Harvey (CONUS) | Sandy |
|---|---|---|
| 0: disrupted trips / isolated | 71,040 / 58,294 (82%) | 54,644 / 30,722 (56%) |
| 0: isolation cost / rerouting cost | $52.04M / $354,265 | $27.43M / $725,636 |
| 7: isolated / isolation cost / rerouting cost | 14,513 / $12.96M / $8.05M | 0 / $0 / $0 |
| 14 to 90 | zero | zero |
Path join (Sandy, `docs/handoffs/harvey_conus_2026-11-13/sandy_*_summary.json`): day 0 has 314,471 OD pairs; the join cost change ($725,636) equals the reported rerouting cost; 27,352 edges gain flow and 28,112 lose it. On day 7 baseline and post-flood paths are identical (delta cost 0), so the network is fully back by day 7.
Day-7 recovery is zero because no Sandy link stays closed after day 0; I have not traced the exact rule, but it is consistent with the T27 residual-depth gates (2 m and 6 m): Sandy's maximum depth after the embankment is 4.5 m, below the 6 m gate, while Harvey's p95 is 7.65 m. Treat that as a hypothesis.

## Profiling
Primary stages 2 / 3 / 3-post / 4: 577 s / 749 s / 2.7 s / 8,542 s; stage 4 peak 48.9 GB, CPU efficiency 0.34; job 2h45m. Sensitivity stages 2 and 3: 585 s and 742 s.

## Caveats
- Sandy raster not yet inspected in GIS for water bodies and artifacts (Harvey's was).
- The 82% and 56% isolated shares depend on one loading node per county (connector test 1 pending).
- Freight only, domestic OD; the OD is about 37% longer-haul than FAF on the network (see the FAF comparison); results are preliminary until demand and route choice are settled.
- 1 m (Sandy) versus 2 m (Harvey) embankment, so the two events are not like-for-like on major roads.
