# Harvey-15 stages 2–4 rerun on Hopper

## Goal and method

Rerun intersection, direct damage, postprocessing, and freight recovery using the existing 15-iteration Harvey freight baseline. The rerun used the masked metre-based raster (9.144 m cap), sourced asset costs, and link-level aggregation that counts each bridge or tunnel once. Passenger demand remained disabled. The owner's instruction to submit was taken as masked-raster sign-off.

Job `3699951` at `ddadbe3` failed before Stage 2 because the compute node lacked `/usr/bin/time`. Job `3704490` used commit `748c271`, which includes the sourced-cost postprocessing fix. A scratch copy of the job pointed to a scratch profiler using a shared GNU time executable tested on a compute node. The tracked job script and model code were unchanged. The job finished at 00:01:35 Eastern on November 13, 2026, after 47m 50s, with exit code 0.

## Direct damage and flooded links

| Asset | Flooded links | Links with positive priced damage | Direct damage, USD millions |
|---|---:|---:|---:|
| Road | 5,302 | 5,302 | 1,137.989 |
| Bridge | 2,187 | 1,235 | 330.895 |
| Tunnel | 1 | 0 | 0 |
| Total | 7,490 | 6,537 | 1,468.884 |

Bridges were 29.2% of flooded links and roads 70.8%, with one flooded tunnel. The $1.469B total is below the handoff’s rough single-digit-to-tens-of-billions expectation and well below its $100B failure threshold. Raw deduplicated and postprocessed totals agree. This is modeled damage to the covered network, and the scale check alone cannot validate it against observed losses. Bridge exposure uses the underlying ground cell under assumption E6.

| HPMS class | Network links | Flooded links | Wet pieces | Truck-closed links |
|---|---:|---:|---:|---:|
| F1 | 170,385 | 1,542 | 13,689 | 1,035 |
| F2 | 80,014 | 1,297 | 10,219 | 888 |
| F3 | 133,559 | 1,896 | 32,271 | 1,401 |
| F4 | 61,987 | 766 | 31,462 | 664 |
| F5 | 34,462 | 1,956 | 29,609 | 1,607 |
| F6 | 1,142 | 2 | 3 | 2 |
| F7 | 1,859 | 30 | 249 | 25 |
| Unknown | 191 | 1 | 40 | 1 |
| Total | 483,599 | 7,490 | 117,542 | 5,623 |

F1–F3 accounted for 47.8% of wet pieces, 63.2% of flooded links, and 59.1% of truck closures. F4–F7 accounted for 52.2%, 36.8%, and 40.9%, respectively, with a small unclassified remainder. F1 and F2 both have positive exposure after the embankment unit fix. Truck closures use the Stage 2 `max_speed_truck == 0` field and include 3,904 roads, 1,718 bridges, and one tunnel.

## Depth and geodesic length

Stage 2 takes the maximum of piece depths for each link. Among the 7,490 positive-depth links, minimum, median, p95, and maximum were **0.0000323, 1.2710, 7.6516, and 9.1432 m**. Across all 483,599 links, the minimum, median, and p95 were zero. The maximum remained below 9.144 m.

| Depth interval, m (upper bound included) | Links |
|---|---:|
| Dry (0) | 476,109 |
| 0–0.1 | 341 |
| 0.1–0.3 | 528 |
| 0.3–0.6 | 998 |
| 0.6–1 | 1,276 |
| 1–2 | 1,611 |
| 2–4 | 1,291 |
| 4–6 | 629 |
| 6–8 | 564 |
| 8–9.144 | 252 |

`length_check_1.json` covers 552,468 pieces at least 1 m long with a geodesic measurement. Projected and geodesic totals were 21,644,644.83 m and 21,628,155.49 m. The total ratio was **0.999238**, and p01/p50/p99 piece ratios were **0.992029 / 0.999153 / 1.006797**.

## Freight isolation and recovery

| Recovery day | Isolated trips | Added rerouting cost, USD | Modeled isolation cost, USD |
|---|---:|---:|---:|
| 0 | 55,618.77 | 308,988.84 | 49,656,436.32 |
| 7 | 12,155.40 | 14,892,537.62 | 10,852,342.02 |
| 14, 30, 60, 90 | 0 | Approximately 0 | 0 |

Day 0 rerouting comprised $270,331.97 in time, $37,532.24 in operating cost, and $1,124.63 in tolls. Day 0 combined cost including direct damage was $1.519B. The day-90 checkpoint's incremental rerouting cost was under one cent and isolation cost was zero. Stage 4 writes checkpoint costs. A separate 0–90 day estimate using linear interpolation between checkpoints gives $105.33M in rerouting and $249.76M in modeled isolation, or **$355.09M** combined incremental cost, excluding the one-time direct damage. These are finite and nonzero over the window. Tiny negative values in later checkpoints are floating-point residuals (less than $0.000001).

The [county isolation CSV](HARVEY_COUNTY_ISOLATION.csv) contains both endpoint views for days 0 and 7. Days 14, 30, 60, and 90 had no isolation records. The Harvey subset crosswalk had 1,359 distinct nodes and counties, and every origin and destination matched. The two endpoint views each sum to the day total and count the same trips from opposite ends.

| County (FIPS) | Day-0 trips by origin | Day-0 trips by destination |
|---|---:|---:|
| Harris, TX (48201) | 16,051.61 | 16,080.91 |
| Fort Bend, TX (48157) | 2,773.58 | 4,663.91 |
| Montgomery, TX (48339) | 2,672.80 | 3,641.12 |
| Brazoria, TX (48039) | 1,847.83 | 2,765.83 |
| Galveston, TX (48167) | 1,793.20 | 2,343.42 |
| Jefferson, TX (48245) | 1,769.04 | 1,867.38 |

Harris remained the largest day-7 endpoint in both views (1,635.08 origin and 1,838.10 destination). The largest day-0 isolated OD pairs were Harris → Fort Bend (2,229.90 trips), Harris → Montgomery (1,741.46), Fort Bend → Harris (1,361.09), Montgomery → Harris (1,332.33), and Harris → Brazoria (1,291.25). Stage 4 hard-codes OD path export off, so the successfully rerouted OD ranking is unavailable.

## Profiling

| Stage | Wall time, s | Max RSS, GiB | CPU efficiency across 8 cores |
|---|---:|---:|---:|
| 2 Intersection | 321.10 | 6.2 | 12% |
| 3 Damage | 346.12 | 2.6 | 12% |
| 3 Postprocess | 2.45 | 0.3 | 12% |
| 4 Rerouting | 2,195.17 | 17.7 | 36% |

All stages exited 0. Slurm reported 29,533,560 KiB for batch MaxRSS, a separate job-level measure. Source files on Hopper are under `results/{disruption_analysis,damage_analysis,rerouting_analysis}/harvey15_streaming_cpu8/304`. Profiles are in `/home/akothaw/multimodal_hazard_project/profiles/harvey15_stages2to4_v2_3704490/stages.tsv`.
