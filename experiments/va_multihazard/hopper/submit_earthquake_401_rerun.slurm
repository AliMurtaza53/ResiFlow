#!/bin/bash
#SBATCH --job-name=va_earthquake_401_rerun
#SBATCH --partition=normal
# Script-4-only re-run for earthquake (401) after the isolation-cost (SC) fix
# to 4_rerouting_and_recovery_scenario_loop.py (2026-08-09, see
# docs/VA_MULTIHAZARD_COMPARISON.md, "Resolved: negative day0 rerouting
# cost"). Script 2/3/3_postprocess already completed successfully for this
# scenario (submit_earthquake_401.slurm, job 9320320) -- damage data on disk
# is unaffected by this fix, only Script 4's cost math changed, so this skips
# straight to Script 4 rather than repeating Script 3's full-tree os.walk().
#
# --partition=normal, --mem=160G, 130GB DuckDB limit: same config the
# original 401 run completed successfully with (103 damaged edges).
#SBATCH --time=06:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=160G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_earthquake_401_rerun_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_earthquake_401_rerun_%j.err
#SBATCH --exclude=hop059

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_RESULTS_VARIANT=convergence_cpu8_bounded18
export RESIFLOW_RESULTS_VARIANT=convergence_cpu8_bounded18
export NIRD_DUCKDB_MEMORY_LIMIT=130GB
export NIRD_DUCKDB_TEMP_DIRECTORY=/scratch/akothaw/multimodal_hazard_data/duckdb_tmp_va_multihazard
export NIRD_PATH_REALIZATION_STRATEGY=duckdb_chunked_compact
export NIRD_LCP_DEST_CHUNK_SIZE=1000
export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_LCP_SORT_BY_DEST_COUNT=1
export RESIFLOW_HAZARD_TYPE=earthquake
export RESIFLOW_SCENARIO_PARAM=401

python /scratch/akothaw/multimodal_hazard_data/code/ResiFlow/scripts/4_rerouting_and_recovery_scenario_loop.py 401 1 20 $SLURM_CPUS_PER_TASK
