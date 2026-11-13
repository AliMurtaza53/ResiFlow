# Hopper runs queued 2026-11-13 (handoff for Codex or the owner)

Claude cannot submit or edit on Hopper (the command wrapper is read-only), so these are prepared, committed and untested on the cluster. Run order and what to report. Always `git pull --ff-only` from a login-node shell and check `git log --oneline -1` first. Use a checkout that has the new files (the Harvey checkout `code/ResiFlow_harvey` is fine once pulled; no run is active there now).

## Goal
(1) Get the rerouted OD paths out of stage 4 so they can be joined to the network; (2) quantify assumption E6 (bridges take ground-cell depth); (3) run Harvey on the full corrected CONUS freight OD with every switch on and profiling.

## Prior knowledge
Harvey-15 (job 3704490, 47m50s) results are in `HARVEY_RERUN_RESULT.md` on `ops/harvey-rerun-report`. The Harvey-15 OD is geographically correct (register F6). Stage 4 hard-set path export off; it is now switchable (`RESIFLOW_STAGE4_EXPORT_OD_PATHS=1`, default off, no behaviour change when off). The profiler needed `/usr/bin/time`, missing on compute nodes; `experiments/common/profile_stage.sh` now falls back to `time_wrap.py`.

## Order
1. `sbatch experiments/pass_a_convergence/hopper/submit_harvey15_stage4_odpaths.slurm` (about 40 min). First test of the export switch. Archives the old stage 4 outputs to `rerouting_analysis/harvey15_streaming_cpu8_v2_nopaths`. Success = `odpfc_freight_s1_day{0,7,...}.pq` and `..._baseline.pq` in `results/rerouting_analysis/harvey15_streaming_cpu8/304/1` and costs equal to the first run (day 0 rerouting $308,988.84, isolation $49,656,436.32). If the export errors, report the first error verbatim and stop; do not edit code on Hopper. The full-CONUS chain below depends on this passing.
2. `sbatch experiments/pass_a_convergence/hopper/submit_harvey15_e6_clearance.slurm` (about 15 min, separate results variant). Report bridge flooded links, bridges with priced damage, bridge cost and truck-closed bridges against the primary run (2,187 / 1,235 / $330.9M / 1,718).
3. Upload the corrected OD, then `bash experiments/pass_a_convergence/hopper/submit_harvey_conus_chain.sh` from the repo root (baseline, then stages 2-4 with `--dependency=afterok`). Upload from the laptop: `C:\Users\akothaw\Desktop\data\soge_clusters\census_datasets_conterminous\faf5_od_matrix_conterminous.pq` to `/scratch/akothaw/multimodal_hazard_data/inputs_corrected/faf5_od_matrix_conterminous.pq`. The baseline checks the file exists and exits 2 otherwise. Resources (bigmem, 600G, 5 days) are a guess from Harvey-15 (150G for 1.85M OD rows; this has 9.66M); the profile will say. Passenger stays off (register F5). Check the `.err` shows freight only.

## Report (to `docs/handoffs/HARVEY_RERUN_RESULT.md` follow-up, same branch)
Per step: job id, commit, exit code, wall time, max RSS, CPU efficiency (`stages.tsv`), and the numbers above. Do not run step 3 stages 2-4 manually if the baseline did not exit 0.

## Out of scope
Code edits, changing the default of `bridge_deck_clearance_m`, deleting archived outputs.
