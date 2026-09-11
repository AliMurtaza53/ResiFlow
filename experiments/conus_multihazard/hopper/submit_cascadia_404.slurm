#!/bin/bash
#SBATCH --job-name=cascadia_404
#SBATCH --partition=bigmem
# Full Script 2 -> 3 -> 3_postprocess -> 4 sequence for the Cascadia M9
# earthquake (404, hazard_subtype=earthquake_cascadia_m9_scenario) -- a
# third real-earthquake case study alongside Mineral (401) and New Madrid
# (403); all three stay runnable. Never run before on any cluster -- run
# submit_cascadia_prep.slurm first and confirm its output exists before
# submitting this.
#
# --partition=bigmem, defensively: same reasoning as every other real-data
# hazard job (damaged-edge count against the CONUS network is genuinely
# unknown), PLUS this one's own aligned PGA raster is unusually large --
# ~1 billion pixels / 2.6GB (Cascadia's own-bounds footprint spans northern
# California to the Canadian border, confirmed 2026-09-11), notably bigger
# than New Madrid's own-bounds raster despite both being --own-bounds
# earthquake scenarios.
#
# --path-realization strategy: streaming_arrays, not duckdb_chunked_compact
# (unlike the older submit_harvey_304.slurm/submit_landslide_501.slurm this
# is otherwise modeled on) -- A/B tested on earthquake/403 at identical CPU
# count and confirmed 22.4% faster (12h24m -> 9h37m) with dollar totals
# matching to 10 significant figures (2026-08-30, see
# docs/CONUS_MULTIHAZARD_METHODOLOGY.md's change log and
# submit_earthquake_403_strategy_streaming_arrays.slurm). This is a brand
# new, never-run job with no prior results to stay comparable with, so
# there's no reason to use the slower strategy here.
#
# --time=24:00:00: not a measured requirement for this specific hazard --
# generous margin matching the other bigmem hazard jobs.
#SBATCH --time=24:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=900G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_cascadia_404_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_cascadia_404_%j.err
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
export RESIFLOW_HAZARD_TYPE=earthquake
export RESIFLOW_EARTHQUAKE_SUBTYPE=earthquake_cascadia_m9_scenario
export RESIFLOW_SCENARIO_PARAM=404

REPO=/scratch/akothaw/multimodal_hazard_data/code/ResiFlow
python $REPO/scripts/2_intersection_analysis.py 404 1
python $REPO/scripts/3_damage_analysis.py
python $REPO/scripts/3_postprocess_damage.py
python $REPO/scripts/4_rerouting_and_recovery_scenario_loop.py 404 1 20 $SLURM_CPUS_PER_TASK
