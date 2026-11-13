# Harvey on the full corrected CONUS freight OD, with OD path export (2026-11-13)

## Goal and method
Run Harvey (scenario 304, masked metre raster, sourced costs) on the full conterminous freight OD (corrected node numbering, 9,656,720 OD rows, passenger off) and compare with the Harvey-15 subset; export stage 4 OD paths so rerouting can be joined to the network. Jobs: baseline 3710402, stages 2 to 4 3710403 (`experiments/pass_a_convergence/hopper/submit_harvey_conus_*.slurm`), path join 3710929 and 3710930 (`scripts/diagnostics/join_rerouted_paths.py`). Harvey-15 path-export test: 3708559. E6 sensitivity: 3708560.

## Prior knowledge
Harvey-15 results in `HARVEY_RERUN_RESULT.md` (branch `ops/harvey-rerun-report`). OD geography verified (register F6: mean haul 175 mi Harvey-15, 193 mi full; FAF 186 mi).

## Results
| | Harvey-15 | Full CONUS |
|---|---|---|
| Baseline | 1 iteration (assigned 100%) | 1 iteration (assigned 100%), 1h07m, 162 GB peak |
| Direct damage | $1,468.88M | $1,468.88M (same: damage does not depend on the OD) |
| Day 0 disrupted / isolated trips | 66,341 / 55,619 | 71,040 / 58,294 |
| Day 0 rerouting / isolation cost | $308,989 / $49.66M | $354,265 / $52.04M |
| Day 7 isolated trips / isolation cost | 12,155 / $10.85M | 14,513 / $12.96M |
| Day 7 rerouting cost (corrected, see below) | $8.22M | $8.05M |
| Day 14, 30, 60, 90 | zero | zero (rounding residuals below 1e-6) |
Stage 4 with path export: 41m44s, 19.6 GB peak (Harvey-15); 1h43m, 36.6 GB (CONUS; rerun 1h37m, 37.0 GB), CPU efficiency about 35%. Path files: 12 per run, up to 862 MB each, 9 GB total for CONUS.
**Reading:** Harvey's freight effect is almost all inside the 15 states; the full OD adds about 5 to 7%. The large isolated share (82%) remains.

## Path join (day 0 and 7; `docs/handoffs/harvey_conus_2026-11-13/*_summary.json`, corrected runs)
Join delta cost equals the stage 4 rerouting cost exactly and baseline and post flow now match on both days. Day 0: CONUS 166,029 OD pairs, 24,167 edges gain flow, 21,009 lose. Day 7: CONUS 276,960 OD pairs, 29,109 gain, 29,277 lose (Harvey-15: 19,231 and 19,214).

## Bug found and fixed in this work (day-7 rerouting cost)
The first runs gave day-7 rerouting of $14.89M (Harvey-15) and $15.62M (CONUS). The path join showed 55,530 OD pairs with 24,000.0 routed flow that had no baseline path, in both runs. All of them were partially isolated pairs (some flow isolated, some routed): Script 4 dropped the whole pair from the baseline demand, so their routed flow had a post cost and no pre cost. Fix (`b2d9f5a`): `resiflow/rerouting_baseline.py` subtracts the isolated flow per pair. Reruns (jobs 3712081, 3712082; old results kept under `*_v3_pre_baselinefix` and `*_v1_pre_baselinefix`): day-7 rerouting **$8.22M (Harvey-15) and $8.05M (CONUS)**, down 45% and 48%. Day 0 and days 14 and later are unchanged. The toy `three_parallel` test pinned the old value (235.53) and now pins 67.32 freight, 20.20 passenger. Any earlier result with partially isolated OD pairs carries the same overstatement of rerouting cost; isolation cost is unaffected.

## Also from the Harvey-15 runs
E6 (2 m bridge clearance): bridges with priced damage 1,235 to 677, bridge damage $330.9M to $170.5M, total $1,468.9M to $1,308.5M; default clearance unchanged (0).

## Not done
Isolation breakdown by access link; passenger demand; rerun of the other hazards and earlier results for the same partial-isolation overstatement.
