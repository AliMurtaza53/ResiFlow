#!/bin/bash
#SBATCH --job-name=va_flood_301_rerun
#SBATCH --partition=normal
# Script-4-only re-run for flood (301) after the isolation-cost (SC) fix to
# 4_rerouting_and_recovery_scenario_loop.py (2026-08-09, see
# docs/VA_MULTIHAZARD_COMPARISON.md, "Resolved: negative day0 rerouting
# cost"). Only submit this if the check in the same message this script was
# handed over with confirms results/rerouting_analysis/convergence_cpu8_
# bounded18/301/1/cost_matrix_by_scenario.csv already exists (i.e. flood's
# Script 2/3/4 already completed once) -- damage data on disk is unaffected
# by this fix, only Script 4's cost math changed.
#
# --partition=normal, --mem=160G: flood (301) is a single-edge closure, the
# smallest of the 4 hazards -- this reuses earthquake's proven normal-
# partition config rather than under-provisioning, since there's no cost to
# the margin and no reason to re-derive a smaller number.
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=160G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_flood_301_rerun_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_flood_301_rerun_%j.err
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
export RESIFLOW_HAZARD_TYPE=flood
export RESIFLOW_SCENARIO_PARAM=301

python /scratch/akothaw/multimodal_hazard_data/code/ResiFlow/scripts/4_rerouting_and_recovery_scenario_loop.py 301 1 20 $SLURM_CPUS_PER_TASK
