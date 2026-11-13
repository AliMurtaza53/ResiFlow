# Test 1: official FAF5 county connectors versus current loading points (handoff spec for Codex)

Written 2026-11-13. Bounded mandate: one comparison, one report, then stop. Cursor's dense-network pilot is on hold, so this is the only centroid-loading work in flight.

## 1. Question
Do FAF5's official centroid connectors, used as the loading points, change convergence, isolation and rerouting results compared with ResiFlow's current single nearest-node loading per county? OD volume and link capacities stay fixed, so only where the demand enters changes.

## 2. Prior knowledge (do not re-derive)
- ResiFlow's base export keeps all 483,599 native FAF5 road links by ID and omits all 3,795 official centroid connectors (Class 50). See `notes/perf_findings/FAF_CENTROIDS_AND_DISAGGREGATION_AUDIT.md`, `notes/perf_findings/CONNECTOR_EXIT_SENSITIVITY.md`, `scripts/convert_faf5_network.py`.
- The corrected county loading points (crosswalk `parameters/crosswalks/county_node_crosswalk_conterminous.csv`) are usually close to FAF's road attachments (median 29 m), but 540 of 3,100 matched counties are more than 1 km away.
- FAF's 2022 assignment has positive truck flow at 348 non-county centroids that get no direct demand in ResiFlow's county OD. Published connector flows imply 21.6 tons per truck against 20 in ResiFlow's OD build.
- Harvey-15 (job 3704490, `HARVEY_RERUN_RESULT.md` on `ops/harvey-rerun-report`): 84% of day-0 freight trips were isolated (55,619 of 66,341), Harris County about 16,000. With one loading node per county, one flooded access link isolates the whole county. This is the result most likely to change.
- OD node ids must be the corrected numbering (register F6). Run the haul check before any run (`scripts/diagnostics/haul_length_check.py`; Harvey-15 subset 175 mi, corrected full OD 193 mi, FAF published 186 mi).
- Hopper: profile every run (`experiments/common/profile_stage.sh`, now with a fallback when `/usr/bin/time` is missing). Code edits happen on a branch off the tip of `feature/anaheim-assignment-diagnostics`; `git pull --ff-only` only from a login-node shell.

## 3. Method
1. **Restore connectors as network links** without changing capacity: add the 3,795 Class 50 connectors back with non-binding capacity and length from geometry, behind a switch (default off). Do not change the existing links.
2. **Key the OD by official centroid**: map each county to its FAF centroid and the centroid's connector exits. Where a county has several connectors, load demand on the centroid node and let routing choose the exit. Keep totals per county and commodity identical to the current OD.
3. **Pilot first**: the Harvey-15 subset (1.85M OD rows, 15 states) and one county group (Harris plus neighbours). Run baseline stage 1 with both loadings, same iterations (15), same settings as `submit_harvey15_streaming_cpu8.slurm`.
4. **Measure**: unassigned demand per iteration, iterations and wall time to the same assigned share, saturated links near loading points, link flow correlation with FAF's published assignment on shared links (class-aggregated), and the 540 far-offset counties separately.
5. **Harvey effect**: rerun stages 2-4 on the connector baseline and report isolated trips (day 0 and 7) and isolation cost against the primary run.

## 4. Out of scope
Sub-county or gateway allocation (test 2), payload changes (test 3), the 348 non-county centroids beyond listing what they are, passenger OD, and edits to `road_revised.py` beyond what step 1 needs (stop and report if a solver change looks necessary).

## 5. Deliverable
`docs/handoffs/CONNECTOR_TEST1_RESULT.md` on branch `exp/connector-loading-test1`: goal, method, prior knowledge, then tables and a plain recommendation. Report negative results too. Do not tune connectors to improve agreement.

## 6. Ledger row (owner edits AGENTS.md)
| `exp/connector-loading-test1` | Codex (connector loading test 1) | FAF5 connector restore behind a switch, OD keyed by official centroid, Harvey-15 pilot, report in `docs/handoffs/` | Active | 2026-11-13 |
