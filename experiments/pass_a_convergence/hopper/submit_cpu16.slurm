#!/bin/bash
#SBATCH --job-name=hazard_scale_cpu16
#SBATCH --partition=normal
# UNTESTED core count -- 128G/100GB DuckDB limit is what cpu8 proved out
# (peaked 99.20GB combined). At 16 threads, PRAGMA threads=16 gives DuckDB
# more parallel hash/sort buffers per chunk, so the *transient* per-chunk
# peak could run higher than cpu8's, even though final table size (9.68M
# rows, unchanged) is not core-count-dependent. Padding both --mem and the
# DuckDB limit as a margin of safety rather than assuming linear cpu8->16
# scaling in either direction.
#
# Verified against `sinfo -o "%P %c %m"` (2026-07-21): `normal` has 48+-core
# nodes with 180000 MB RAM, so 16 cores fits easily. --mem=170G rather than
# 176G because SLURM's G suffix is GiB (176G = 180224 MiB), which exceeds
# the node's 180000 MiB total and would never schedule; 170G = 174080 MiB
# leaves ~5.9GB headroom for SLURM/OS overhead.
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=16
#SBATCH --mem=170G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_cpu16_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_cpu16_%j.err

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json

# One iteration only -- this is a scaling comparison test, not a convergence run.
export RESIFLOW_MAX_FLOW_ITERATIONS=1
export NIRD_MAX_FLOW_ITERATIONS=1

# Distinct output/db path so this doesn't collide with the other cpu-count run.
export RESIFLOW_RESULTS_VARIANT=scale_test_cpu16
export NIRD_RESULTS_VARIANT=scale_test_cpu16
export NIRD_BASELINE_DB_PATH=/scratch/akothaw/multimodal_hazard_data/scale_test_cpu16.duckdb

# Goal 15 validated fixes -- keep these regardless of core count
# 1000 validated at cpu8 2026-07-23 (job 9049761): -22.7% LCP dispatch
# time for negligible memory cost. Mechanism (fewer per-origin Dijkstra
# tree rebuilds) is core-count-independent, not retested at cpu16 directly.
# See docs/ORC_HOPPER_SETUP.md section 7.
export NIRD_LCP_DEST_CHUNK_SIZE=1000
export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_DUCKDB_MEMORY_LIMIT=140GB
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
export NIRD_DUCKDB_TEMP_DIRECTORY=/scratch/akothaw/multimodal_hazard_data/duckdb_tmp_cpu16
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

python /scratch/akothaw/multimodal_hazard_data/code/ResiFlow/scripts/1_network_flow_model_revision.py 20 $SLURM_CPUS_PER_TASK
