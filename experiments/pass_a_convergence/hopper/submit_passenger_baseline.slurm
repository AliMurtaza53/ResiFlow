#!/bin/bash
#SBATCH --job-name=pax_baseline
#SBATCH --partition=normal
# Passenger-ONLY baseline (stage 1) on the corrected county OD, fully profiled. Parameterised so one script covers the whole matrix:
#   sbatch --job-name=pax_h15_base --export=ALL,NAME=pax_h15_base,OD=passenger_harvey15_od.pq experiments/pass_a_convergence/hopper/submit_passenger_baseline.slurm
# Variables (defaults in brackets):
#   NAME        results variant and profile name (required)
#   OD          file under $DATA/inputs_passenger/ (required): passenger_{conus,harvey15}[_split]_od.pq, vehicle trips, built by scripts/diagnostics/prepare_passenger_od_variants.py
#   ITERS [15]  max assignment iterations (freight baselines used 15)
#   PATHMODE [full_odpfc]  NIRD_BASELINE_PATH_OUTPUT_MODE; "none" skips path export (tests what path writing costs)
#   CHUNK [1000]  NIRD_LCP_DEST_CHUNK_SIZE
#   DUCKMEM [100GB]  NIRD_DUCKDB_MEMORY_LIMIT (use ~75% of --mem)
# Set partition, --mem, --cpus-per-task, --time on the sbatch command line (script defaults: Harvey-15 sized).
# The assignment code labels the demand "freight=" in its log; for these runs that column is the passenger vehicle OD (freight is not loaded).
#SBATCH --time=24:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=150G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_%x_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_%x_%j.err
#SBATCH --exclude=hop059
module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird
CODE=${CODE:-/scratch/akothaw/multimodal_hazard_data/code/ResiFlow_harvey}
DATA=/scratch/akothaw/multimodal_hazard_data
: "${NAME:?set NAME}" "${OD:?set OD}"
ITERS=${ITERS:-15}; PATHMODE=${PATHMODE:-full_odpfc}; CHUNK=${CHUNK:-1000}; DUCKMEM=${DUCKMEM:-100GB}
ODFILE=$DATA/inputs_passenger/$OD
test -f $ODFILE || { echo "MISSING $ODFILE"; exit 2; }
VARIANT=$NAME
export PYTHONPATH=$CODE/src:$PYTHONPATH
export PROJ_DATA=/scratch/akothaw/conda_envs/nird/lib/python3.10/site-packages/rasterio/proj_data PROJ_LIB=$PROJ_DATA
export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$RESIFLOW_CONFIG_PATH
export RESIFLOW_DISABLE_PASSENGER_OD=1 NIRD_DISABLE_PASSENGER_OD=1
export RESIFLOW_FAF5_OD_MATRIX_PATH=$ODFILE NIRD_FAF5_OD_MATRIX_PATH=$ODFILE
export RESIFLOW_MAX_FLOW_ITERATIONS=$ITERS NIRD_MAX_FLOW_ITERATIONS=$ITERS
export RESIFLOW_RESULTS_VARIANT=$VARIANT NIRD_RESULTS_VARIANT=$VARIANT
export NIRD_BASELINE_DB_PATH=$DATA/$VARIANT.duckdb
export NIRD_LCP_DEST_CHUNK_SIZE=$CHUNK NIRD_FLOW_DB_BATCH_SIZE=50000 NIRD_DUCKDB_MEMORY_LIMIT=$DUCKMEM NIRD_LOG_RSS_CHECKPOINTS=1 NIRD_LCP_SORT_BY_DEST_COUNT=1
export NIRD_PATH_REALIZATION_STRATEGY=streaming_arrays NIRD_OD_ID_AT_INSERT=1 NIRD_POOL_MAX_TASKS_PER_CHILD=50 NIRD_LCP_COLLECT_POOL_RESULTS=0
export RESIFLOW_AUDIT_DUMP_DIR=$DATA/audit_dumps/$VARIANT RESIFLOW_AUDIT_DUMP_LEVEL=binding
export RESIFLOW_GIT_COMMIT=$(git -C $CODE rev-parse HEAD 2>/dev/null || echo unknown) RESIFLOW_LOG_CAPACITY_BLOCKED_EDGES=1
export NIRD_DUCKDB_TEMP_DIRECTORY=$DATA/duckdb_tmp_$VARIANT
export NIRD_BASE_SCENARIO_OUT_DIR=$DATA/results/$VARIANT
export NIRD_BASELINE_PATH_OUTPUT_MODE=$PATHMODE
if [ "$PATHMODE" = "full_odpfc" ]; then export NIRD_ODPFC_OUTPUT_MODE=iteration_parquet NIRD_COMBINE_ODPFC_PARTS=0; fi
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
mkdir -p $NIRD_DUCKDB_TEMP_DIRECTORY
echo "NAME=$NAME OD=$OD ITERS=$ITERS PATHMODE=$PATHMODE CHUNK=$CHUNK DUCKMEM=$DUCKMEM cpus=$SLURM_CPUS_PER_TASK node=$SLURMD_NODENAME"
git -C $CODE log --oneline -1 2>/dev/null || echo "(no git on compute node)"
python -c "import resiflow; print('resiflow imported from:', resiflow.__file__)"
source $CODE/experiments/common/profile_stage.sh
profile_init $NAME
profile_stage stage1_baseline python $CODE/scripts/1_network_flow_model_revision.py 20 $SLURM_CPUS_PER_TASK
profile_finish
