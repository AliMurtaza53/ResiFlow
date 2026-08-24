#!/bin/bash
#SBATCH --job-name=nandu_flood_301
#SBATCH --partition=normal
# Full Script 2 -> 3 -> 3_postprocess -> 4 for flood (301) against the
# conus_nandu_v1 baseline. The earlier 4-hazard nandu_v1 batch
# (043603b, "Add Pass A + 4-hazard Hopper jobs for conus_nandu_v1
# baseline") only added earthquake/landslide/winter_storm/harvey and
# missed flood -- submit_flood_301.slurm still targets the old
# convergence_cpu8_bounded18 baseline, not this one.
# --time bumped 24h (2026-08-24): the original 6h budget assumed flood
# was the smallest of the 5 hazards ("single-edge closure") -- wrong.
# Confirmed on Hopper (job 9456528): Script 2 alone took 9388s (~2.6h),
# leaving Script 3/4 too little of the remaining budget and the job hit
# TIMEOUT with no output. flood's damaged-edge footprint is evidently
# comparable to winter_storm's, which needed up to 18.5h -- match that.
#SBATCH --time=24:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=160G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_nandu_flood_301_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_nandu_flood_301_%j.err
#SBATCH --exclude=hop059

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_RESULTS_VARIANT=conus_nandu_v1
export RESIFLOW_RESULTS_VARIANT=conus_nandu_v1
export NIRD_DUCKDB_MEMORY_LIMIT=130GB
export NIRD_DUCKDB_TEMP_DIRECTORY=/scratch/akothaw/multimodal_hazard_data/duckdb_tmp_va_multihazard_nandu
export NIRD_PATH_REALIZATION_STRATEGY=duckdb_chunked_compact
export NIRD_LCP_DEST_CHUNK_SIZE=1000
export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_LCP_SORT_BY_DEST_COUNT=1
export RESIFLOW_HAZARD_TYPE=flood
export RESIFLOW_SCENARIO_PARAM=301

REPO=/scratch/akothaw/multimodal_hazard_data/code/ResiFlow
python $REPO/scripts/2_intersection_analysis.py 301 1
python $REPO/scripts/3_damage_analysis.py
python $REPO/scripts/3_postprocess_damage.py
python $REPO/scripts/4_rerouting_and_recovery_scenario_loop.py 301 1 20 $SLURM_CPUS_PER_TASK
