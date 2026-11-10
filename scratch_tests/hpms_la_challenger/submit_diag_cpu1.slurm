#!/bin/bash
#SBATCH --job-name=hpms_diag_cpu1
#SBATCH --partition=bigmem
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=1
#SBATCH --mem=400G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_hpms_diag_cpu1_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_hpms_diag_cpu1_%j.err

# Single-process (no Pool) + stride-50: if a specific origin crashes LCP,
# we get an in-process traceback instead of silent worker zombies.

source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=/scratch/akothaw/multimodal_hazard_data/scratch_tests/hpms_la_challenger/config_hopper_hpms_la.json
export NIRD_CONFIG_PATH=$RESIFLOW_CONFIG_PATH
OUT=/scratch/akothaw/multimodal_hazard_data/scratch_tests/hpms_la_challenger
export NIRD_PASSENGER_OD_PATH="$OUT/passenger_od_hpms_la.pq"
export RESIFLOW_PASSENGER_OD_PATH="$OUT/passenger_od_hpms_la.pq"
export NIRD_MAX_FLOW_ITERATIONS=1
export NIRD_RESULTS_VARIANT=hpms_la_diag_cpu1
export NIRD_BASELINE_DB_PATH=/scratch/akothaw/multimodal_hazard_data/dbs/hpms_la_diag_cpu1.duckdb
export NIRD_DUCKDB_MEMORY_LIMIT=350GB
export NIRD_PATH_REALIZATION_STRATEGY=streaming_arrays
export PYTHONFAULTHANDLER=1

# argv: chunks, cpus=1, stride=50
python -u /scratch/akothaw/multimodal_hazard_data/code/ResiFlow/scripts/1_network_flow_model_revision.py 20 1 50
echo EXIT:$?
