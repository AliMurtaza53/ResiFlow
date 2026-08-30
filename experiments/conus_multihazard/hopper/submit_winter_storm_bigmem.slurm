#!/bin/bash
#SBATCH --job-name=winter_storm_601
#SBATCH --partition=bigmem
# Targeted Script 4 run for winter_storm (601) only -- NOT the full 4-hazard
# orchestrator. Script 2/3 already completed successfully for this event in
# earlier attempts (confirmed: "Loaded script-3 damages for scenario=601
# event=1: edges=11556" in prior logs, meaning damage_analysis output
# already exists on disk); re-running the full orchestrator would
# needlessly redo flood/earthquake/landslide too.
#
# --partition=bigmem: winter_storm's damaged-edge set (11,556 of 483K CONUS
# edges, 2.4% -- over 100x earthquake's 95) OOM'd repeatedly on the `normal`
# partition's ~180GB nodes even after two rounds of load_odpfc_source
# fixes (index-based lookup, then narrow-then-widen SQL dedup -- see
# docs/CONUS_MULTIHAZARD_METHODOLOGY.md, "Resolved: Stage 2 row explosion for
# widespread hazards"). bigmem nodes (amd069-090) have 1TB+ RAM confirmed
# via `sinfo -p bigmem -o "%N %m %c"` (2026-08-05).
#
# --time=24:00:00: the narrow-then-widen fix IS confirmed working now (an
# interactive 2h test on 2026-08-05 got load_odpfc_source down to 1,774,874
# candidate rows -- was 16.67M before the fix -- with zero OOM, then
# proceeded cleanly into Script 4's own internal rerouting network_flow_
# model() re-solve, completing iteration 1 in ~32 min and reaching 67%
# through iteration 2's LCP dispatch before the 2h interactive session's
# OWN time limit (not a crash) cut it off. That re-solve's iteration
# controls are max_iterations=unbounded (stagnant_limit=3), so the true
# total runtime across all iterations -- and however many recovery-day
# scenarios follow -- isn't known yet. 24h is a generous margin, not a
# measured requirement; bigmem allows up to 7 days if this proves
# insufficient.
#SBATCH --time=24:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=900G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_winter_storm_601_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_winter_storm_601_%j.err
#SBATCH --exclude=hop059

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_RESULTS_VARIANT=convergence_cpu8_bounded18
export RESIFLOW_RESULTS_VARIANT=convergence_cpu8_bounded18
# 800GB, not the full 900G --mem request -- leaves headroom for Python/
# pandas/igraph objects alongside DuckDB's own allocation, same margin
# philosophy as the normal-partition 160G/130GB pairing (docs/
# CONUS_MULTIHAZARD_METHODOLOGY.md, odpfc_edge_index section).
export NIRD_DUCKDB_MEMORY_LIMIT=800GB
export NIRD_DUCKDB_TEMP_DIRECTORY=/scratch/akothaw/multimodal_hazard_data/duckdb_tmp_multihazard
export NIRD_PATH_REALIZATION_STRATEGY=duckdb_chunked_compact
export NIRD_LCP_DEST_CHUNK_SIZE=1000
export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_LCP_SORT_BY_DEST_COUNT=1
export RESIFLOW_HAZARD_TYPE=winter_storm
export RESIFLOW_SCENARIO_PARAM=601

python /scratch/akothaw/multimodal_hazard_data/code/ResiFlow/scripts/4_rerouting_and_recovery_scenario_loop.py 601 1 20 $SLURM_CPUS_PER_TASK
