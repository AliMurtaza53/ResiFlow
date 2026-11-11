#!/bin/bash
#SBATCH --job-name=stage1b_unbounded_streaming_cpu8
#SBATCH --partition=normal
# Stage 1b: the Stage 1 control (freight-only, full CONUS, unbounded, existing stagnation guard) re-run with
# streaming_arrays at NumCpu=8. Stage 2 showed this cell is numerically identical to the Stage 1 control through
# iteration 2 (delivered, isolated and remain flow match to every printed digit) and about 3x faster per iteration
# (iteration 1: 5,942 s vs 15,759 s; iteration 2: 4,281 s vs 13,228 s). Stage 1 (job 3666243, chunked, NumCpu=1) keeps
# running as the slow reference. NEW here: RESIFLOW_LOG_CAPACITY_BLOCKED_EDGES=1 names the edges that saturate each iteration.
# --mem=175G: the Stage 2 streaming NumCpu=8 probe peaked at 114.6 GB of a 128 GB request (the chunked one hit 134 GB), and 175G is
# the largest request that fits the 180000 MB nodes. NIRD_DUCKDB_MEMORY_LIMIT stays 100GB.
# --time=7-00:00:00 is the partition ceiling (unbounded run; ~1.6 h/iteration measured at 2 iterations, tail length unknown).
#SBATCH --time=7-00:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=175G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_stage1b_unbounded_streaming_cpu8_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_stage1b_unbounded_streaming_cpu8_%j.err

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

# The conda env has an EDITABLE install of resiflow pointing at the shared
# checkout (.../code/ResiFlow/src), which does not have the audit logging. Run
# from a separate checkout of feature/anaheim-assignment-diagnostics and put its
# src first on PYTHONPATH so it wins over the editable-install path.
CODE=/scratch/akothaw/multimodal_hazard_data/code/ResiFlow_stage1
export PYTHONPATH=$CODE/src:$PYTHONPATH

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json

# Freight only. Verify the .err contains "freight=... passenger=0" (or
# "Passenger OD not configured") before trusting the run.
export RESIFLOW_DISABLE_PASSENGER_OD=1
export NIRD_DISABLE_PASSENGER_OD=1

# Unbounded: leave RESIFLOW_MAX_FLOW_ITERATIONS unset. Stagnation guard default.
export RESIFLOW_RESULTS_VARIANT=stage1b_unbounded_streaming_cpu8
export NIRD_RESULTS_VARIANT=stage1b_unbounded_streaming_cpu8
export NIRD_BASELINE_DB_PATH=/scratch/akothaw/multimodal_hazard_data/stage1b_unbounded_streaming_cpu8.duckdb

export NIRD_LCP_DEST_CHUNK_SIZE=1000
export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_DUCKDB_MEMORY_LIMIT=100GB
export NIRD_LOG_RSS_CHECKPOINTS=1
export NIRD_LCP_SORT_BY_DEST_COUNT=1
export NIRD_PATH_REALIZATION_STRATEGY=streaming_arrays
export NIRD_OD_ID_AT_INSERT=1
export NIRD_POOL_MAX_TASKS_PER_CHILD=50
export NIRD_LCP_COLLECT_POOL_RESULTS=0
# Name the edges that saturate each iteration (top 25 per iteration, with road, tier, lanes, capacity).
export RESIFLOW_LOG_CAPACITY_BLOCKED_EDGES=1

export NIRD_DUCKDB_TEMP_DIRECTORY=/scratch/akothaw/multimodal_hazard_data/duckdb_tmp_stage1b_unbounded_streaming_cpu8
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

# Log which resiflow actually got imported (must be under $CODE, not the shared checkout).
python -c "import resiflow; print('resiflow imported from:', resiflow.__file__)"

python $CODE/scripts/1_network_flow_model_revision.py 20 $SLURM_CPUS_PER_TASK
