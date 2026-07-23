#!/bin/bash
#SBATCH --job-name=hazard_opt_fuse
#SBATCH --partition=normal
# Optimization experiment 1 of 5 (see docs/ORC_HOPPER_SETUP.md "Optimization
# experiments" section). Isolates ONE variable against the cpu8 baseline
# (job 9000424, 2026-07-21: total 83.5min, pass1=43.9min, LCP=17.9min):
# NIRD_DUCKDB_CHUNKED_FUSE_PASS1=1 fuses pass 1's two per-chunk queries
# (edge_total_parts + od_results_iter) into one CROSS JOIN UNNEST/join,
# feeding both aggregates from a single materialized chunk_exploded temp
# table instead of re-exploding+re-joining the same rows twice. Everything
# else matches the baseline exactly (chunk count=20, dest_chunk_size=300).
# Compare "DuckDB compact pass 1 complete" timestamp minus pass-1 start
# against baseline's 43.9min, and diff odpfc.pq / edge_flows.gpq against
# the baseline run's output for correctness.
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_cpu8_opt_fuse_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_cpu8_opt_fuse_%j.err

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json

# One iteration only -- this is a timing experiment, not a convergence run.
export RESIFLOW_MAX_FLOW_ITERATIONS=1
export NIRD_MAX_FLOW_ITERATIONS=1

# Distinct output/db path so this doesn't collide with other runs.
export RESIFLOW_RESULTS_VARIANT=opt_fuse_cpu8
export NIRD_RESULTS_VARIANT=opt_fuse_cpu8
export NIRD_BASELINE_DB_PATH=/scratch/akothaw/multimodal_hazard_data/opt_fuse_cpu8.duckdb

# Goal 15 validated fixes -- unchanged from baseline
export NIRD_LCP_DEST_CHUNK_SIZE=300
export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_DUCKDB_MEMORY_LIMIT=100GB
export NIRD_LOG_RSS_CHECKPOINTS=1
export NIRD_LCP_SORT_BY_DEST_COUNT=1
export NIRD_PATH_REALIZATION_STRATEGY=duckdb_chunked_compact
export NIRD_DUCKDB_TEMP_DIRECTORY=/scratch/akothaw/multimodal_hazard_data/duckdb_tmp_opt_fuse

# THE VARIABLE UNDER TEST -- everything else matches the cpu8 baseline.
export NIRD_DUCKDB_CHUNKED_FUSE_PASS1=1

export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

# Same chunk count (20) as the baseline -- only the fusion flag differs.
python /scratch/akothaw/multimodal_hazard_data/code/ResiFlow/scripts/1_network_flow_model_revision.py 20 $SLURM_CPUS_PER_TASK
