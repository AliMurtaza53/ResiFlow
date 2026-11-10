#!/bin/bash
#SBATCH --job-name=hpms_la_AFTER_1iter
#SBATCH --partition=bigmem
#SBATCH --time=06:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=400G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_hpms_la_AFTER_1iter_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_hpms_la_AFTER_1iter_%j.err

# Short twin after dict-lookup fix (gate 1.17x). One iter only — compare
# vehicles/compute-hour vs BEFORE iter1. No 24h wall.

source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=/scratch/akothaw/multimodal_hazard_data/scratch_tests/hpms_la_challenger/config_hopper_hpms_la.json
export NIRD_CONFIG_PATH=$RESIFLOW_CONFIG_PATH
OUT=/scratch/akothaw/multimodal_hazard_data/scratch_tests/hpms_la_challenger
export NIRD_PASSENGER_OD_PATH="$OUT/passenger_od_hpms_la.pq"
export RESIFLOW_PASSENGER_OD_PATH="$OUT/passenger_od_hpms_la.pq"
export NIRD_MAX_FLOW_ITERATIONS=1
export NIRD_RESULTS_VARIANT=hpms_la_after_1iter
export NIRD_BASELINE_DB_PATH=/scratch/akothaw/multimodal_hazard_data/dbs/hpms_la_after_1iter.duckdb
export NIRD_DUCKDB_MEMORY_LIMIT=350GB
export NIRD_PATH_REALIZATION_STRATEGY=streaming_arrays
export PYTHONFAULTHANDLER=1

python -u /scratch/akothaw/multimodal_hazard_data/code/ResiFlow/scripts/1_network_flow_model_revision.py 20 "$SLURM_CPUS_PER_TASK"
echo EXIT:$?
