#!/bin/bash
#SBATCH --job-name=harvey15_streaming_cpu8
#SBATCH --partition=normal
# Harvey-15 subset: freight-only, FULL CONUS network, OD restricted to pairs with both ends in the 15 states
# TX LA UT OK CA FL OH IL GA AR PA NY MS MI IN (1,359 counties, 889,998 trucks/day, 1,846,328 OD rows).
# 15 iterations, audit dump level binding, per-iteration path parts (odpfc_parts) and final edge_flows.gpq for GIS.
# Code = code/ResiFlow_dump (c665170), the checkout already validated at CONUS scale. Branch: feature/anaheim-assignment-diagnostics.
#SBATCH --time=24:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=150G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_harvey15_streaming_cpu8_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_harvey15_streaming_cpu8_%j.err

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

# 15 iterations on the subset OD.
export RESIFLOW_MAX_FLOW_ITERATIONS=15
export NIRD_MAX_FLOW_ITERATIONS=15
export RESIFLOW_RESULTS_VARIANT=harvey15_streaming_cpu8
export NIRD_RESULTS_VARIANT=harvey15_streaming_cpu8
export NIRD_BASELINE_DB_PATH=/scratch/akothaw/multimodal_hazard_data/harvey15_streaming_cpu8.duckdb

export NIRD_LCP_DEST_CHUNK_SIZE=1000
export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_DUCKDB_MEMORY_LIMIT=100GB
export NIRD_LOG_RSS_CHECKPOINTS=1
export NIRD_LCP_SORT_BY_DEST_COUNT=1
export NIRD_PATH_REALIZATION_STRATEGY=streaming_arrays
export NIRD_OD_ID_AT_INSERT=1
export NIRD_POOL_MAX_TASKS_PER_CHILD=50
export NIRD_LCP_COLLECT_POOL_RESULTS=0

export RESIFLOW_AUDIT_DUMP_DIR=/scratch/akothaw/multimodal_hazard_data/audit_dumps/harvey15_streaming_cpu8
export RESIFLOW_AUDIT_DUMP_LEVEL=binding
export RESIFLOW_GIT_COMMIT=$(git -C $CODE rev-parse HEAD)
export RESIFLOW_LOG_CAPACITY_BLOCKED_EDGES=1
export NIRD_DUCKDB_TEMP_DIRECTORY=/scratch/akothaw/multimodal_hazard_data/duckdb_tmp_harvey15_streaming_cpu8
export RESIFLOW_FAF5_OD_MATRIX_PATH=/scratch/akothaw/multimodal_hazard_data/subset_harvey15/faf5_od_matrix_subset.pq
export NIRD_FAF5_OD_MATRIX_PATH=$RESIFLOW_FAF5_OD_MATRIX_PATH
export NIRD_BASE_SCENARIO_OUT_DIR=/scratch/akothaw/multimodal_hazard_data/results/harvey15_streaming_cpu8
export NIRD_BASELINE_PATH_OUTPUT_MODE=full_odpfc
export NIRD_ODPFC_OUTPUT_MODE=iteration_parquet
export NIRD_COMBINE_ODPFC_PARTS=0
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

# Log which resiflow actually got imported (must be under $CODE, not the shared checkout).
python -c "import resiflow; print('resiflow imported from:', resiflow.__file__)"

python $CODE/scripts/1_network_flow_model_revision.py 20 $SLURM_CPUS_PER_TASK
