#!/bin/bash
#SBATCH --job-name=hazard_opt_chunk40
#SBATCH --partition=normal
# Optimization experiment 3 of 5 (see docs/ORC_HOPPER_SETUP.md "Optimization
# experiments" section). Isolates ONE variable against the cpu8 baseline
# (job 9000424, 2026-07-21: total 83.5min, pass1=43.9min): num_of_chunk
# (the script's first CLI arg) raised from 20 to 40 -- more, smaller
# itter_path chunks, trading higher per-query planning/compilation overhead
# against lower peak per-chunk memory. Fusion stays OFF (unset) so this
# isolates chunk count alone, in the opposite direction from opt_chunk10.
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_cpu8_opt_chunk40_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_cpu8_opt_chunk40_%j.err

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json

# One iteration only -- this is a timing experiment, not a convergence run.
export RESIFLOW_MAX_FLOW_ITERATIONS=1
export NIRD_MAX_FLOW_ITERATIONS=1

# Distinct output/db path so this doesn't collide with other runs.
export RESIFLOW_RESULTS_VARIANT=opt_chunk40_cpu8
export NIRD_RESULTS_VARIANT=opt_chunk40_cpu8
export NIRD_BASELINE_DB_PATH=/scratch/akothaw/multimodal_hazard_data/opt_chunk40_cpu8.duckdb

# Goal 15 validated fixes -- unchanged from baseline
export NIRD_LCP_DEST_CHUNK_SIZE=300
export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_DUCKDB_MEMORY_LIMIT=100GB
export NIRD_LOG_RSS_CHECKPOINTS=1
export NIRD_LCP_SORT_BY_DEST_COUNT=1
export NIRD_PATH_REALIZATION_STRATEGY=duckdb_chunked_compact
export NIRD_DUCKDB_TEMP_DIRECTORY=/scratch/akothaw/multimodal_hazard_data/duckdb_tmp_opt_chunk40

export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

# THE VARIABLE UNDER TEST -- num_of_chunk=40 instead of the baseline's 20.
python /scratch/akothaw/multimodal_hazard_data/code/ResiFlow/scripts/1_network_flow_model_revision.py 40 $SLURM_CPUS_PER_TASK
