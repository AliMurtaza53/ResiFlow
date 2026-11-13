#!/bin/bash
#SBATCH --job-name=harvey_conus_baseline
#SBATCH --partition=bigmem
# Harvey on the FULL CONUS freight OD (corrected node numbering, 9,656,720 OD rows, FAF truck, passenger off): stage 1 baseline.
# Same settings as harvey15_streaming_cpu8 (streaming_arrays, 15 iterations, per-iteration path parts) so the two are comparable; only the OD differs.
# Resources are a GUESS (Harvey-15 used 150G for 1.85M OD rows; this has 5.2x the rows). Profiling is on: read stages.tsv before the next run.
# PRE-REQUISITE (not on Hopper yet): upload the corrected OD from the laptop to $DATA/inputs_corrected/faf5_od_matrix_conterminous.pq
#   (local: C:\Users\akothaw\Desktop\data\soge_clusters\census_datasets_conterminous\faf5_od_matrix_conterminous.pq, 86 MB, 2026-11-11).
#   Geography gate already run locally 2026-11-13: mean straight-line haul 193 mi vs FAF published 186 mi, 0 nodes missing from the network.
#SBATCH --time=5-00:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=600G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_harvey_conus_baseline_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_harvey_conus_baseline_%j.err
#SBATCH --exclude=hop059
module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird
CODE=${CODE:-/scratch/akothaw/multimodal_hazard_data/code/ResiFlow_harvey}
DATA=/scratch/akothaw/multimodal_hazard_data
OD=$DATA/inputs_corrected/faf5_od_matrix_conterminous.pq
VARIANT=harvey_conus_corrected
test -f $OD || { echo "MISSING corrected OD $OD (upload it first)"; exit 2; }
export PYTHONPATH=$CODE/src:$PYTHONPATH
export PROJ_DATA=/scratch/akothaw/conda_envs/nird/lib/python3.10/site-packages/rasterio/proj_data PROJ_LIB=$PROJ_DATA
export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$RESIFLOW_CONFIG_PATH
export RESIFLOW_DISABLE_PASSENGER_OD=1 NIRD_DISABLE_PASSENGER_OD=1
export RESIFLOW_FAF5_OD_MATRIX_PATH=$OD NIRD_FAF5_OD_MATRIX_PATH=$OD
export RESIFLOW_MAX_FLOW_ITERATIONS=15 NIRD_MAX_FLOW_ITERATIONS=15
export RESIFLOW_RESULTS_VARIANT=$VARIANT NIRD_RESULTS_VARIANT=$VARIANT
export NIRD_BASELINE_DB_PATH=$DATA/$VARIANT.duckdb
export NIRD_LCP_DEST_CHUNK_SIZE=1000 NIRD_FLOW_DB_BATCH_SIZE=50000 NIRD_DUCKDB_MEMORY_LIMIT=450GB NIRD_LOG_RSS_CHECKPOINTS=1 NIRD_LCP_SORT_BY_DEST_COUNT=1
export NIRD_PATH_REALIZATION_STRATEGY=streaming_arrays NIRD_OD_ID_AT_INSERT=1 NIRD_POOL_MAX_TASKS_PER_CHILD=50 NIRD_LCP_COLLECT_POOL_RESULTS=0
export RESIFLOW_AUDIT_DUMP_DIR=$DATA/audit_dumps/$VARIANT RESIFLOW_AUDIT_DUMP_LEVEL=binding
export RESIFLOW_GIT_COMMIT=$(git -C $CODE rev-parse HEAD) RESIFLOW_LOG_CAPACITY_BLOCKED_EDGES=1
export NIRD_DUCKDB_TEMP_DIRECTORY=$DATA/duckdb_tmp_$VARIANT
export NIRD_BASE_SCENARIO_OUT_DIR=$DATA/results/$VARIANT
export NIRD_BASELINE_PATH_OUTPUT_MODE=full_odpfc NIRD_ODPFC_OUTPUT_MODE=iteration_parquet NIRD_COMBINE_ODPFC_PARTS=0
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
mkdir -p $NIRD_DUCKDB_TEMP_DIRECTORY
git -C $CODE log --oneline -1
python -c "import resiflow; print('resiflow imported from:', resiflow.__file__)"
source $CODE/experiments/common/profile_stage.sh
profile_init harvey_conus_baseline
profile_stage stage1_baseline python $CODE/scripts/1_network_flow_model_revision.py 20 $SLURM_CPUS_PER_TASK
profile_finish
