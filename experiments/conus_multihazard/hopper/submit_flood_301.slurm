#!/bin/bash
#SBATCH --job-name=flood_301
#SBATCH --partition=normal
# Full Script 2 -> 3 -> 3_postprocess -> 4 sequence for flood (301) --
# confirmed on Hopper (2026-08-09) that results/rerouting_analysis/
# convergence_cpu8_bounded18/301/1/cost_matrix_by_scenario.csv does not
# exist yet, unlike earthquake/landslide/winter_storm which all have at
# least one completed run -- flood has never been run end-to-end against
# this baseline. Includes the isolation-cost (SC) fix
# (4_rerouting_and_recovery_scenario_loop.py, 2026-08-09) from the start,
# so no rerun will be needed afterward.
#
# --partition=normal, --mem=160G: flood (301) is a single-edge closure, the
# smallest of the 4 hazards -- reuses earthquake's proven normal-partition
# config rather than under-provisioning.
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=160G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_flood_301_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_flood_301_%j.err
#SBATCH --exclude=hop059

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_RESULTS_VARIANT=convergence_cpu8_bounded18
export RESIFLOW_RESULTS_VARIANT=convergence_cpu8_bounded18
export NIRD_DUCKDB_MEMORY_LIMIT=130GB
export NIRD_DUCKDB_TEMP_DIRECTORY=/scratch/akothaw/multimodal_hazard_data/duckdb_tmp_multihazard
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
