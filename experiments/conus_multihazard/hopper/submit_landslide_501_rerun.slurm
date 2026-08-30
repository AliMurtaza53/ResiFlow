#!/bin/bash
#SBATCH --job-name=landslide_501_rerun
#SBATCH --partition=bigmem
# Script-4-only re-run for landslide (501) after the isolation-cost (SC) fix
# to 4_rerouting_and_recovery_scenario_loop.py (2026-08-09, see
# docs/CONUS_MULTIHAZARD_METHODOLOGY.md, "Resolved: negative day0 rerouting
# cost"). Only submit this if the check in the same message this script was
# handed over with confirms results/rerouting_analysis/convergence_cpu8_
# bounded18/501/1/cost_matrix_by_scenario.csv already exists (i.e.
# submit_landslide_501.slurm's full Script2->3->4 run already completed) --
# damage data on disk is unaffected by this fix, only Script 4's cost math
# changed. If that file does NOT exist yet, landslide is still running (or
# hasn't started) under the original submit_landslide_501.slurm -- do not
# submit this alongside it; let that job finish, it'll already include this
# fix once the code is pulled.
#
# --partition=bigmem, --mem=900G: matches submit_landslide_501.slurm's own
# config (landslide's damaged-edge count for this baseline was unknown at
# submission time, so it defensively used bigmem from the start).
#SBATCH --time=24:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=900G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_landslide_501_rerun_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_landslide_501_rerun_%j.err
#SBATCH --exclude=hop059

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_RESULTS_VARIANT=convergence_cpu8_bounded18
export RESIFLOW_RESULTS_VARIANT=convergence_cpu8_bounded18
export NIRD_DUCKDB_MEMORY_LIMIT=800GB
export NIRD_DUCKDB_TEMP_DIRECTORY=/scratch/akothaw/multimodal_hazard_data/duckdb_tmp_multihazard
export NIRD_PATH_REALIZATION_STRATEGY=duckdb_chunked_compact
export NIRD_LCP_DEST_CHUNK_SIZE=1000
export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_LCP_SORT_BY_DEST_COUNT=1
export RESIFLOW_HAZARD_TYPE=landslide
export RESIFLOW_SCENARIO_PARAM=501

python /scratch/akothaw/multimodal_hazard_data/code/ResiFlow/scripts/4_rerouting_and_recovery_scenario_loop.py 501 1 20 $SLURM_CPUS_PER_TASK
