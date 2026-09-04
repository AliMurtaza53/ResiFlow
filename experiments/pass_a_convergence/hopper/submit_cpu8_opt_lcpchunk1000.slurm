#!/bin/bash
#SBATCH --job-name=hazard_opt_lcpchunk1000
#SBATCH --partition=normal
# Optimization experiment 4 of 5 (see docs/ORC_HOPPER_SETUP.md "Optimization
# experiments" section). Isolates ONE variable against the cpu8 baseline
# (job 9000424, 2026-07-21: total 83.5min, LCP pool dispatch=17.9min,
# "Chunked LCP dispatch: 3143 origin-tasks split into 34374 tasks
# (dest_chunk_size=300)"): NIRD_LCP_DEST_CHUNK_SIZE raised 300 -> 1000.
#
# Why this matters: igraph's get_shortest_paths recomputes the full
# single-source Dijkstra tree on every call regardless of how many
# destinations are batched into that call (see the comment above this
# env var's read site in road_revised.py, ~line 2889). At dest_chunk_size
# =300 with ~3081 destinations/origin on average, each origin's tree gets
# rebuilt ~11x (34374 tasks / 3143 origins) instead of once. Raising the
# chunk size to 1000 cuts that to ~4x rebuilds/origin -- a real reduction
# in redundant tree computation, at the cost of ~3.3x more per-task
# memory (still bounded, not full removal of chunking). This chunking
# was originally sized for higher OD-scale memory safety (Goal 15, see
# docs/ORC_HOPPER_SETUP.md); the LCP phase happens BEFORE itter_path, so
# RSS at that point in the baseline was only ~24GB against a 128G
# allocation -- there's ample headroom to test relaxing it.
# Watch RSS checkpoint [iter1_lcp_pool_done] to confirm no memory
# regression, and "Pool dispatch (imap_unordered consumption) time"
# against baseline's 1075.57s (17.93min).
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_cpu8_opt_lcpchunk1000_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_cpu8_opt_lcpchunk1000_%j.err

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json

# One iteration only -- this is a timing experiment, not a convergence run.
export RESIFLOW_MAX_FLOW_ITERATIONS=1
export NIRD_MAX_FLOW_ITERATIONS=1

# Distinct output/db path so this doesn't collide with other runs.
export RESIFLOW_RESULTS_VARIANT=opt_lcpchunk1000_cpu8
export NIRD_RESULTS_VARIANT=opt_lcpchunk1000_cpu8
export NIRD_BASELINE_DB_PATH=/scratch/akothaw/multimodal_hazard_data/opt_lcpchunk1000_cpu8.duckdb

export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_DUCKDB_MEMORY_LIMIT=100GB
export NIRD_LOG_RSS_CHECKPOINTS=1
export NIRD_LCP_SORT_BY_DEST_COUNT=1
export NIRD_PATH_REALIZATION_STRATEGY=duckdb_chunked_compact
export NIRD_DUCKDB_TEMP_DIRECTORY=/scratch/akothaw/multimodal_hazard_data/duckdb_tmp_opt_lcpchunk1000

# THE VARIABLE UNDER TEST -- 1000 instead of the baseline's 300.
export NIRD_LCP_DEST_CHUNK_SIZE=1000

export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

python /scratch/akothaw/multimodal_hazard_data/code/ResiFlow/scripts/1_network_flow_model_revision.py 20 $SLURM_CPUS_PER_TASK
