#!/bin/bash
#SBATCH --job-name=stage1_freight_only
#SBATCH --partition=normal
# DRAFT, NOT SUBMITTED. Stage 1 control: freight-only, full CONUS, NumCpu=1,
# audit logging on (ITER_AUDIT / INVARIANT lines, default-on in the
# feature/anaheim-assignment-diagnostics commits), unbounded iterations with
# the existing stagnation guard (stop rule unchanged).
#
# --time is NOT measured for this configuration. Only anchor: iteration 1 of
# the freight+passenger cpu8 scaling test took 83.5 min (job 9000424). Freight
# only is a smaller OD set, but NumCpu=1 vs 8 is unmeasured here (perf notes say
# NumCpu>1 does not help end-to-end). Worst case if every one of 59 iterations
# (CONUS tail seen earlier) cost 83.5 min = ~82 h; later iterations shrink, so
# 72 h is a guess with headroom, inside the 7-day cap. Revise after the first
# ITER_AUDIT iter_wall_s values appear.
#SBATCH --time=72:00:00
#SBATCH --cpus-per-task=1
#SBATCH --mem=128G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_stage1_freight_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_stage1_freight_%j.err

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json

# Freight only. Verify the .err contains "freight=... passenger=0" (or
# "Passenger OD not configured") before trusting the run.
export RESIFLOW_DISABLE_PASSENGER_OD=1
export NIRD_DISABLE_PASSENGER_OD=1

# Unbounded: leave RESIFLOW_MAX_FLOW_ITERATIONS unset. Stagnation guard default.
export RESIFLOW_RESULTS_VARIANT=stage1_freight_only_cpu1
export NIRD_RESULTS_VARIANT=stage1_freight_only_cpu1
export NIRD_BASELINE_DB_PATH=/scratch/akothaw/multimodal_hazard_data/stage1_freight_only_cpu1.duckdb

export NIRD_LCP_DEST_CHUNK_SIZE=1000
export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_DUCKDB_MEMORY_LIMIT=100GB
export NIRD_LOG_RSS_CHECKPOINTS=1
export NIRD_LCP_SORT_BY_DEST_COUNT=1

# Strategy: DECISION NEEDED. Past convergence runs used duckdb_chunked_compact
# (chosen to avoid a legacy_compact_sql OOM); perf notes lock streaming_arrays +
# NumCpu=1 + Patch 6 flags. Control matches the production lock below; Stage 2
# compares both.
export NIRD_PATH_REALIZATION_STRATEGY=streaming_arrays
export NIRD_OD_ID_AT_INSERT=1
export NIRD_POOL_MAX_TASKS_PER_CHILD=50
export NIRD_LCP_COLLECT_POOL_RESULTS=0

export NIRD_DUCKDB_TEMP_DIRECTORY=/scratch/akothaw/multimodal_hazard_data/duckdb_tmp_stage1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

python /scratch/akothaw/multimodal_hazard_data/code/ResiFlow/scripts/1_network_flow_model_revision.py 20 $SLURM_CPUS_PER_TASK
