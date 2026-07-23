#!/bin/bash
#SBATCH --job-name=hazard_scale_cpu4
#SBATCH --partition=normal
# Matches the cpu8 run's proven-working budget (see submit_cpu8.slurm for the
# full history): 01:30:00/64G/32GB repeats the exact OOM + time-limit
# failures already fixed there. Post-chunking-fix, peak memory is driven
# mostly by total OD row count (9.68M, unchanged across core counts) since
# the final accumulated tables hold all rows regardless of chunking -- core
# count only affects the transient per-chunk join buffers -- so cpu4 is not
# expected to need much less than cpu8 needed.
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=128G
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
# 1000 validated at cpu8 2026-07-23 (job 9049761): -22.7% LCP dispatch
# time for negligible memory cost. Mechanism (fewer per-origin Dijkstra
# tree rebuilds) is core-count-independent, not retested at cpu4 directly.
# See docs/ORC_HOPPER_SETUP.md section 7.
export NIRD_LCP_DEST_CHUNK_SIZE=1000
export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_DUCKDB_MEMORY_LIMIT=100GB
export NIRD_LOG_RSS_CHECKPOINTS=1
export NIRD_LCP_SORT_BY_DEST_COUNT=1

# Same itter_path fix as cpu8 -- default legacy_compact_sql runs the
# path-explode join unchunked over the full OD table; this bounds peak
# per-chunk working set instead. See docs/ORC_HOPPER_SETUP.md.
export NIRD_PATH_REALIZATION_STRATEGY=duckdb_chunked_compact
export NIRD_DUCKDB_TEMP_DIRECTORY=/scratch/akothaw/multimodal_hazard_data/duckdb_tmp_cpu4

export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

python /scratch/akothaw/multimodal_hazard_data/code/ResiFlow/scripts/1_network_flow_model_revision.py 20 $SLURM_CPUS_PER_TASK
