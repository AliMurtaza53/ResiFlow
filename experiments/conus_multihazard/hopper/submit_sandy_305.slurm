#!/bin/bash
#SBATCH --job-name=sandy_305
#SBATCH --partition=bigmem
# Full Script 2 -> 3 -> 3_postprocess -> 4 sequence for Hurricane Sandy
# (305, hazard_subtype=flood_sandy_northeast) -- a second real-flood case
# study alongside Harvey (304); both stay runnable. Never run before on any
# cluster -- run submit_sandy_prep.slurm first and confirm its output
# exists before submitting this.
#
# --partition=bigmem, defensively: Sandy's damaged-edge count against the
# CONUS network is genuinely UNKNOWN (never run). The CT/NJ/NY/RI footprint
# is a dense Northeast Corridor metro region, so this could plausibly land
# anywhere from a handful of edges to a winter_storm-sized widespread
# footprint depending on how much of Sandy's depth grid falls on FAF5
# strategic-network segments -- same reasoning submit_harvey_304.slurm used.
#
# --time=24:00:00 / --mem=900G: copied from submit_harvey_304.slurm's
# sizing, not a measured requirement for this specific hazard.
#
# --path-realization=streaming_arrays (not duckdb_chunked_compact, unlike
# Harvey's job this was originally modeled on): A/B tested on earthquake/403
# at identical CPU count, confirmed 22.4% faster (12h24m -> 9h37m) with
# dollar totals matching to 10 significant figures (2026-08-30, see
# docs/CONUS_MULTIHAZARD_METHODOLOGY.md's change log). This job has never
# run, so there's no prior-results comparability reason to keep the slower
# strategy -- switched 2026-09-11.
#SBATCH --time=24:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=900G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_sandy_305_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_sandy_305_%j.err
#SBATCH --exclude=hop059

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_RESULTS_VARIANT=convergence_cpu8_bounded18
export RESIFLOW_RESULTS_VARIANT=convergence_cpu8_bounded18
export NIRD_DUCKDB_MEMORY_LIMIT=800GB
export NIRD_DUCKDB_TEMP_DIRECTORY=/scratch/akothaw/multimodal_hazard_data/duckdb_tmp_multihazard
export NIRD_PATH_REALIZATION_STRATEGY=streaming_arrays
export NIRD_LCP_DEST_CHUNK_SIZE=1000
export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_LCP_SORT_BY_DEST_COUNT=1
export RESIFLOW_HAZARD_TYPE=flood
export RESIFLOW_FLOOD_SUBTYPE=flood_sandy_northeast
export RESIFLOW_SCENARIO_PARAM=305

REPO=/scratch/akothaw/multimodal_hazard_data/code/ResiFlow
python $REPO/scripts/2_intersection_analysis.py 305 1
python $REPO/scripts/3_damage_analysis.py
python $REPO/scripts/3_postprocess_damage.py
python $REPO/scripts/4_rerouting_and_recovery_scenario_loop.py 305 1 20 $SLURM_CPUS_PER_TASK
