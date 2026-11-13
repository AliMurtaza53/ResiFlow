# Harvey-15 stages 2 to 4 rerun on Hopper (handoff spec for Codex)

Written 2026-11-12. Bounded mandate in the AGENTS.md sense: one run, one report, stop.

## 1. Goal
Rerun intersection (stage 2), direct damage (stage 3), post-process, and rerouting/recovery (stage 4) for the Harvey-15 scenario on Hopper with the corrected inputs, and report whether the results are sensible. The first run is invalid for three reasons, all now fixed:
1. Flood depths were feet read as metres (rasters now converted, x0.3048).
2. Cells deeper than 30 ft (9.144 m) were water bodies and edge artifacts (now masked to NaN).
3. Bridge and tunnel whole-structure cost was summed once per raster-cell piece (about $500B total). Fixed in `src/resiflow/damage_aggregation.py` (each bridge/tunnel counted once per link, roads summed). Flood costing is also now sourced-only (T24 roads, T30 bridges, Rostami tunnels).

## 2. Prior knowledge (so you do not re-derive it)
- Baseline (15 assignment iterations, freight only, Harvey-15 OD subset, whole network kept) is finished: `/scratch/akothaw/multimodal_hazard_data/results/harvey15_streaming_cpu8/` (`edge_flows.gpq`, `odpfc_parts`, `odpfc_edge_index`). Do not rerun it.
- Code checkout to use: `/scratch/akothaw/multimodal_hazard_data/code/ResiFlow_harvey`, currently at `e63e9b5` on `feature/anaheim-assignment-diagnostics`. It already contains the aggregation fix and the sourced-only path. Only `git pull --ff-only` is allowed there.
- Raster the pipeline reads (already masked, metres): `/scratch/akothaw/multimodal_hazard_data/soge_clusters/inputs/multihazard_aligned/flood_harvey_houston/event_1.tif`. Sibling files (`*_unmasked`, `*_feet_unconverted`, `*_BAD_align_tool_shifted`) must not be used.
- Job script, ready and NOT submitted: `experiments/pass_a_convergence/hopper/submit_harvey15_stages2to4_v2.slurm`. It archives old outputs to `*_INVALID_feet_double_count`, sets the PROJ fix, uses the `sourced_asset_costs.json` override, profiles each stage, and prints corrected damage totals by asset type.
- Hopper environment: env `nird`; PROJ fix is `PROJ_DATA=<env>/lib/python3.10/site-packages/rasterio/proj_data` (already in the script). Never export `RESIFLOW_CONFIG_PATH`/`NIRD_CONFIG_PATH` outside the job script's own context for tests. Scratch purges files older than 90 days: check before submitting.
- Profiling is mandatory for CONUS-scale runs (`experiments/common/profile_stage.sh`, summarize with `scripts/diagnostics/summarize_hopper_profiles.py`). The script already does it.

## 3. Gates (do not submit until all are true)
1. **Owner sign-off on the masked Harvey raster.** The owner is checking it in GIS (local copy `C:\Users\akothaw\Desktop\ResiFlow\inputs\multihazard_raw\audit_2026-11-12\rasters\flood_harvey_houston_event_1_metres_masked.tif`). Ask the owner; do not assume.
2. The retirement test run (Hopper job 3699073) has finished with the full result read and any failure resolved by Claude. Claude owns that.
3. `ResiFlow_harvey` fast-forwarded to the tip of `origin/feature/anaheim-assignment-diagnostics` and `git status` clean. Run `git pull --ff-only` from a **login node shell**, not inside a Slurm job (a `git pull -q` inside a job failed silently and left the checkout stale on 2026-11-12). Check `git log --oneline -1` afterwards. The tip must include: the embankment unit fix (major roads were zeroed), the geodesic `length_geodesic_m` column and `length_check_<event>.json` from Script 2, and the aggregation fix.
4. `ls` confirms baseline outputs, the raster, and `/scratch/akothaw/conda_envs/nird` exist.

## 4. Steps
1. Verify the gates; report the commit hash.
2. Submit the v2 script as is (`sbatch`). Do not edit it; if it needs a change, stop and report (a change is a code change owned by Claude).
3. Monitor. Do not poll more than every 30 minutes. On failure read `logs_harvey15_stages2to4_v2_<jobid>.{out,err}`, report the first error verbatim, and stop; do not patch `src/` or `scripts/`.
4. When finished, collect per-stage wall time, max RSS, CPU efficiency from the profile (`stages.tsv`).
5. Sanity checks, each reported as number plus expectation:
   - Total direct damage (bridge/tunnel once, roads summed) is in the single-digit to tens of $B range for a Houston-scale event, not hundreds. A value above about $100B means the double counting or a unit problem is back: stop and report.
   - Split by asset type (road, bridge, tunnel) and count of damaged links.
   - Maximum flood depth reaching any link is at most 9.144 m; the distribution of link depths (min, median, p95, max).
   - Number of links with depth above zero, and the share on bridges versus roads.
   - Major roads: share of wet pieces and of links closed for HPMS F1-F3 versus F4-F7 (was zero for F1-F2 before the embankment fix). Bridges versus roads among flooded links (bridges take the ground-cell depth; see `docs/ASSUMPTIONS_REGISTER.md` E6).
   - Length check: report `length_check_<event>.json` (total ratio of geodesic to projected length, p01/p50/p99).
   - Rerouting: day-0 cost components and the 90-day recovery total are finite, nonnegative and not all zero; list the largest rerouted OD pairs.
6. Write the report to `docs/handoffs/HARVEY_RERUN_RESULT.md` on branch `ops/harvey-rerun-report` (a docs-only branch off the current tip) and push. Lead with goal, method, prior knowledge, then tables.

## 5. Out of scope (hand back to Claude or the owner)
- Any edit to `src/`, `scripts/` or parameters. Any conversion or masking of rasters.
- Any decision about how stage 2 chooses one depth per link (max or mean): report which it does, do not change it.
- Passenger OD (`RESIFLOW_DISABLE_PASSENGER_OD=1` stays), the corrected-OD freight run, and the testbed suite.
- Deleting or overwriting anything not named in the script's archive step.

Assumptions behind this run are listed in `docs/ASSUMPTIONS_REGISTER.md`; report any that you see violated.

## 6. Ledger row to add to AGENTS.md (the owner edits AGENTS.md; it has uncommitted changes)
| `ops/harvey-rerun-report` (docs only) | Codex (Harvey rerun session) | Hopper submission and monitoring of `submit_harvey15_stages2to4_v2.slurm`, report in `docs/handoffs/` | Active when the gates in the spec clear | 2026-11-12 |

## 7. Division of work with Claude
| Owner | Work | Why |
|---|---|---|
| Codex | This Harvey rerun and its report; later, other Hopper runs that need only existing scripts | Long waits, no code edits, easy to hand off |
| Claude | Retirement test run and pinned-baseline update; testbed suite (Sioux Falls and Anaheim); the passenger centroid loading investigation | These change code and tests in this branch |
| Owner | Masked-raster sign-off; interaction cases for the suite; decisions on any code change Codex reports |
Code changes found during the rerun go back to Claude on this branch; Codex does not commit to it.
