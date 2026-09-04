#!/bin/bash
#SBATCH --job-name=hazard_scale_cpu8
#SBATCH --partition=normal
# 01:30:00 was sized for the old scaling-test reference point (pool dispatch
# + od_id assignment + aggregation only). This run also writes full_odpfc
# output, and the 2026-07-19 attempt got CANCELLED DUE TO TIME LIMIT with
# no OOM -- pool dispatch (~18min) + od_id assignment (~4min) + chunked
# pass 1 (~45-50min) + pass 2 (~8min) already consumed the whole 90min
# budget before the full_odpfc INSERT (9.68M rows) got any time at all.
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_cpu8_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_cpu8_%j.err

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json

# One iteration only -- this is a scaling comparison test, not a convergence run.
export RESIFLOW_MAX_FLOW_ITERATIONS=1
export NIRD_MAX_FLOW_ITERATIONS=1

# Distinct output/db path so this doesn't collide with the other cpu-count run.
export RESIFLOW_RESULTS_VARIANT=scale_test_cpu8
export NIRD_RESULTS_VARIANT=scale_test_cpu8
export NIRD_BASELINE_DB_PATH=/scratch/akothaw/multimodal_hazard_data/scale_test_cpu8.duckdb

# Goal 15 validated fixes -- keep these regardless of core count
# LCP_DEST_CHUNK_SIZE raised 300->1000 (2026-07-23, job 9049761): fewer
# per-origin task splits means igraph rebuilds each origin's Dijkstra tree
# fewer times (get_shortest_paths rebuilds the tree per call regardless of
# destination-batch size) -- cut LCP pool dispatch 17.93min->13.86min
# (-22.7%) for negligible extra memory (25.71GB vs ~24GB at that phase).
# 0 (fully disabled) was tested and OOM-killed by the kernel at this OD
# scale (job 9049760) -- 1000 is validated-safe, do not go further without
# retesting. See docs/ORC_HOPPER_SETUP.md section 7.
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
export NIRD_DUCKDB_TEMP_DIRECTORY=/scratch/akothaw/multimodal_hazard_data/duckdb_tmp_cpu8
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

python /scratch/akothaw/multimodal_hazard_data/code/ResiFlow/scripts/1_network_flow_model_revision.py 20 $SLURM_CPUS_PER_TASK
