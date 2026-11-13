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
| Day 7 rerouting cost | $14.89M | $15.62M |
| Day 14, 30, 60, 90 | zero | zero (rounding residuals below 1e-6) |
Stage 4 with path export: 41m44s, 19.6 GB peak (Harvey-15); 1h43m, 36.6 GB (CONUS), CPU efficiency about 35%. Path files: 12 per run, up to 862 MB each, 9 GB total for CONUS.
**Reading:** Harvey's freight effect is almost all inside the 15 states; the full OD adds about 5 to 7%. The large isolated share (82%) remains.

## Path join (day 0 and 7; `docs/handoffs/harvey_conus_2026-11-13/*_summary.json`)
Join delta cost equals the stage 4 rerouting cost exactly ($354,265 and $15,622,296 CONUS; $308,989 and $14,892,538 Harvey-15), so the path files and the cost accounting agree. Day 0: 166,029 OD pairs, 24,167 edges gain flow, 21,009 lose. Day 7: 276,960 OD pairs, 68,318 edges gain, 13,464 lose.

## Anomaly (needs a trace before day-7 rerouting cost is used)
On day 7 the disrupted-network path file has 55,530 OD pairs totalling exactly **24,000.0** flow that have **no row in the baseline file** (CONUS: post flow 56,527 vs baseline 32,527; Harvey-15: 54,186 vs 30,186, also 24,000). Rerouting cost is post minus baseline, so if those pairs' baseline cost is missing, the day-7 rerouting cost ($15.6M, 44 times day 0) may be overstated, perhaps by about half using the average baseline cost per unit flow. Same round number in two runs points to a mechanism, not data. Days 14 and later cost zero, so this only affects day 7. Owner decision needed on who traces it (Script 4 candidate selection for the `_baseline` pass).

## Also from the Harvey-15 runs
E6 (2 m bridge clearance): bridges with priced damage 1,235 to 677, bridge damage $330.9M to $170.5M, total $1,468.9M to $1,308.5M; default clearance unchanged (0).

## Not done
Isolation breakdown by access link; passenger demand; checking the 24,000 anomaly; a corrected baseline for `rerouting_cost` if the trace finds an error.
