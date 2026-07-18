#!/bin/bash
#SBATCH --job-name=hazard_scale_cpu4
#SBATCH --partition=normal
#SBATCH --time=01:30:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_cpu4_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_cpu4_%j.err

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json

# One iteration only -- this is a scaling comparison test, not a convergence run.
export RESIFLOW_MAX_FLOW_ITERATIONS=1
export NIRD_MAX_FLOW_ITERATIONS=1

# Distinct output/db path so this doesn't collide with the other cpu-count run.
export RESIFLOW_RESULTS_VARIANT=scale_test_cpu4
export NIRD_RESULTS_VARIANT=scale_test_cpu4
export NIRD_BASELINE_DB_PATH=/scratch/akothaw/multimodal_hazard_data/scale_test_cpu4.duckdb

# Goal 15 validated fixes -- keep these regardless of core count
export NIRD_LCP_DEST_CHUNK_SIZE=300
export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_DUCKDB_MEMORY_LIMIT=32GB
export NIRD_LOG_RSS_CHECKPOINTS=1
export NIRD_LCP_SORT_BY_DEST_COUNT=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

python /scratch/akothaw/multimodal_hazard_data/code/ResiFlow/scripts/1_network_flow_model_revision.py 20 $SLURM_CPUS_PER_TASK
