#!/bin/bash
#SBATCH --partition=bigmem
#SBATCH --time=24:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=600G
# usage: CASE=freight|passenger|combined sbatch --job-name=finalA_<case>_baseline final_baseline.slurm
set -eo pipefail
module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird
: "${CASE:?set CASE}"
DATA=/scratch/akothaw/multimodal_hazard_data
CODE=$DATA/code/ResiFlow_final_a9ce7b3
FROZEN=/home/akothaw/frozen_inputs_networkA_20261123
VARIANT=finalA_${CASE}_baseline
export PYTHONPATH=$CODE/src:$PYTHONPATH
export PROJ_DATA=/scratch/akothaw/conda_envs/nird/lib/python3.10/site-packages/rasterio/proj_data PROJ_LIB=$PROJ_DATA
export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json NIRD_CONFIG_PATH=$RESIFLOW_CONFIG_PATH
export RESIFLOW_DEMAND_CASE=$CASE
export RESIFLOW_FAF5_OD_MATRIX_PATH=$FROZEN/freight_od_T29_gateway_conus.pq NIRD_FAF5_OD_MATRIX_PATH=$FROZEN/freight_od_T29_gateway_conus.pq
export RESIFLOW_FAF5_CONNECTOR_NETWORK=$FROZEN/faf5_road_links.gpq
if [ "$CASE" = freight ]; then export RESIFLOW_DISABLE_PASSENGER_OD=1 NIRD_DISABLE_PASSENGER_OD=1; else export RESIFLOW_PASSENGER_OD_PATH=$FROZEN/passenger_conus_split_od.pq NIRD_PASSENGER_OD_PATH=$FROZEN/passenger_conus_split_od.pq; fi
export RESIFLOW_MAX_FLOW_ITERATIONS=15 NIRD_MAX_FLOW_ITERATIONS=15
export RESIFLOW_RESULTS_VARIANT=$VARIANT NIRD_RESULTS_VARIANT=$VARIANT
export NIRD_BASELINE_DB_PATH=$DATA/$VARIANT.duckdb
export NIRD_LCP_DEST_CHUNK_SIZE=1000 NIRD_FLOW_DB_BATCH_SIZE=50000 NIRD_DUCKDB_MEMORY_LIMIT=450GB NIRD_LOG_RSS_CHECKPOINTS=1 NIRD_LCP_SORT_BY_DEST_COUNT=1
export NIRD_PATH_REALIZATION_STRATEGY=streaming_arrays NIRD_OD_ID_AT_INSERT=1 NIRD_POOL_MAX_TASKS_PER_CHILD=50 NIRD_LCP_COLLECT_POOL_RESULTS=0
export RESIFLOW_AUDIT_DUMP_DIR=$DATA/audit_dumps/$VARIANT RESIFLOW_AUDIT_DUMP_LEVEL=binding
export RESIFLOW_GIT_COMMIT=a9ce7b3 RESIFLOW_LOG_CAPACITY_BLOCKED_EDGES=1
export NIRD_DUCKDB_TEMP_DIRECTORY=$DATA/duckdb_tmp_$VARIANT NIRD_BASE_SCENARIO_OUT_DIR=$DATA/results/$VARIANT
export NIRD_BASELINE_PATH_OUTPUT_MODE=full_odpfc NIRD_ODPFC_OUTPUT_MODE=iteration_parquet NIRD_COMBINE_ODPFC_PARTS=0
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
mkdir -p $NIRD_DUCKDB_TEMP_DIRECTORY
echo "CASE=$CASE variant=$VARIANT node=$SLURMD_NODENAME"
python -c "import resiflow; print(\"resiflow imported from:\", resiflow.__file__)"
source $CODE/experiments/common/profile_stage.sh
profile_init $VARIANT
profile_stage stage1_baseline python $CODE/scripts/1_network_flow_model_revision.py 20 $SLURM_CPUS_PER_TASK
profile_finish
