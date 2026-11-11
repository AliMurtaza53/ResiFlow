#!/bin/bash
#SBATCH --job-name=dump_streaming_cpu8
#SBATCH --partition=normal
# Assignment-dump probe: streaming_arrays, NumCpu=8, freight-only, full CONUS, EXACTLY 2 iterations, audit dump ON (level binding).
# Purpose (dump phase 1, commit 173e3d3 + column fix): (1) validate that the dump changes NO numbers at CONUS scale: delivered,
# isolated and remain flow must match the Stage 1/2 control to every printed digit (Lesson 2); (2) measure real dump size and
# overhead (spec target: < 5% of iter_wall_s); (3) check the edge attribute columns (state, county, road name) resolve on CONUS.
# Runs from a SEPARATE checkout (code/ResiFlow_dump) so the live jobs' checkouts are untouched.
# --time=12:00:00 is a ceiling: the same config without the dump took 2h51m (streaming) / 3h15m (chunked) for 2 iterations.
# --mem=175G: Stage 2 peaks were 114-134 GB of 128 GB; 175G is the largest request that fits the 180000 MB nodes.
#SBATCH --time=12:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=175G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_dump_streaming_cpu8_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_dump_streaming_cpu8_%j.err

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

# The conda env has an EDITABLE install of resiflow pointing at the shared
# checkout (.../code/ResiFlow/src), which does not have the audit logging. Run
# from a separate checkout of feature/anaheim-assignment-diagnostics and put its
# src first on PYTHONPATH so it wins over the editable-install path.
CODE=/scratch/akothaw/multimodal_hazard_data/code/ResiFlow_dump
export PYTHONPATH=$CODE/src:$PYTHONPATH

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json

# Freight only. Verify the .err contains "freight=... passenger=0" (or
# "Passenger OD not configured") before trusting the run.
export RESIFLOW_DISABLE_PASSENGER_OD=1
export NIRD_DISABLE_PASSENGER_OD=1

# Exactly 2 iterations (probe), so the result is comparable with Stage 1's first two iterations.
export RESIFLOW_MAX_FLOW_ITERATIONS=2
export NIRD_MAX_FLOW_ITERATIONS=2
export RESIFLOW_RESULTS_VARIANT=dump_streaming_cpu8
export NIRD_RESULTS_VARIANT=dump_streaming_cpu8
export NIRD_BASELINE_DB_PATH=/scratch/akothaw/multimodal_hazard_data/dump_streaming_cpu8.duckdb

export NIRD_LCP_DEST_CHUNK_SIZE=1000
export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_DUCKDB_MEMORY_LIMIT=100GB
export NIRD_LOG_RSS_CHECKPOINTS=1
export NIRD_LCP_SORT_BY_DEST_COUNT=1
export NIRD_PATH_REALIZATION_STRATEGY=streaming_arrays
export NIRD_OD_ID_AT_INSERT=1
export NIRD_POOL_MAX_TASKS_PER_CHILD=50
export NIRD_LCP_COLLECT_POOL_RESULTS=0

export RESIFLOW_AUDIT_DUMP_DIR=/scratch/akothaw/multimodal_hazard_data/audit_dumps/dump_streaming_cpu8
export RESIFLOW_AUDIT_DUMP_LEVEL=binding
export RESIFLOW_GIT_COMMIT=$(git -C $CODE rev-parse HEAD)
export RESIFLOW_LOG_CAPACITY_BLOCKED_EDGES=1
export NIRD_DUCKDB_TEMP_DIRECTORY=/scratch/akothaw/multimodal_hazard_data/duckdb_tmp_dump_streaming_cpu8
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

# Log which resiflow actually got imported (must be under $CODE, not the shared checkout).
python -c "import resiflow; print('resiflow imported from:', resiflow.__file__)"

python $CODE/scripts/1_network_flow_model_revision.py 20 $SLURM_CPUS_PER_TASK
