#!/bin/bash
#SBATCH --job-name=hazard_convergence_cpu8
#SBATCH --partition=normal
# This is a REAL convergence run, not a single-iteration scaling test --
# RESIFLOW_MAX_FLOW_ITERATIONS is left unset (defaults to 0 = unbounded),
# so the loop runs until NIRD_STAGNANT_ITERATIONS (default 3) consecutive
# iterations make negligible progress, or demand is fully assigned.
#
# Time budget is a rough estimate, not a measured number: iteration 1 in
# the cpu8 scaling test (2026-07-21, job 9000424) took 83.5min end-to-end
# and assigned 53.9% of demand. If later iterations cost roughly the same
# (remain_od does shrink each iteration, so this is likely pessimistic)
# and convergence needs on the order of 10-15 iterations, that's
# ~14-21 hours. Budgeting 30h for headroom; `normal`'s 7-day cap is the
# real ceiling if this needs re-requesting. Watch the .err log's
# "Pass A convergence: remain_fraction=..." lines to see actual progress
# and adjust for a resubmit if needed.
#SBATCH --time=30:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_cpu8_conv_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_cpu8_conv_%j.err

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json

# Intentionally NOT setting RESIFLOW_MAX_FLOW_ITERATIONS / NIRD_MAX_FLOW_ITERATIONS
# here -- unset defaults to 0 (unbounded), letting the stagnant-iterations
# check (NIRD_STAGNANT_ITERATIONS, default 3) be the real stopping condition.
# Uncomment to hard-cap as a safety net if a run needs to be bounded:
# export RESIFLOW_MAX_FLOW_ITERATIONS=20
# export NIRD_MAX_FLOW_ITERATIONS=20

# Distinct output/db path -- separate from the scale_test_cpu* artifacts,
# this is a different kind of run (real convergence, not a timing test).
export RESIFLOW_RESULTS_VARIANT=convergence_cpu8
export NIRD_RESULTS_VARIANT=convergence_cpu8
export NIRD_BASELINE_DB_PATH=/scratch/akothaw/multimodal_hazard_data/convergence_cpu8.duckdb

# Goal 15 validated fixes -- keep these regardless of core count
# 1000 validated 2026-07-23 (job 9049761): -22.7% LCP dispatch time for
# negligible memory cost. See docs/ORC_HOPPER_SETUP.md section 7.
export NIRD_LCP_DEST_CHUNK_SIZE=1000
export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_DUCKDB_MEMORY_LIMIT=100GB
export NIRD_LOG_RSS_CHECKPOINTS=1
export NIRD_LCP_SORT_BY_DEST_COUNT=1

# Root cause of the cpu8 OOM at 90GB: the default itter_path strategy
# (legacy_compact_sql) runs the path-explode CROSS JOIN UNNEST as ONE
# unchunked DuckDB query over the full ~9.68M-row OD table -- the
# NIRD_LCP_DEST_CHUNK_SIZE chunking only applies to the earlier LCP
# dispatch phase, not this aggregation. duckdb_chunked_compact actually
# splits this join into num_of_chunk (script arg, currently 20) row
# batches, bounding DuckDB's peak pinned working set per chunk instead
# of the whole table.
export NIRD_PATH_REALIZATION_STRATEGY=duckdb_chunked_compact

# Explicit spill target so temp-directory behavior isn't left to DuckDB's
# default-next-to-db-file assumption; /scratch has no size quota (see
# docs/ORC_HOPPER_SETUP.md).
export NIRD_DUCKDB_TEMP_DIRECTORY=/scratch/akothaw/multimodal_hazard_data/duckdb_tmp_cpu8_conv
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

python /scratch/akothaw/multimodal_hazard_data/code/ResiFlow/scripts/1_network_flow_model_revision.py 20 $SLURM_CPUS_PER_TASK
