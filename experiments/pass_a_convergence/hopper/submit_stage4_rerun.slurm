#!/bin/bash
#SBATCH --job-name=stage4_rerun
#SBATCH --partition=bigmem
# Stage 4 ONLY for a finished Harvey variant, with OD path export on. Stage 2 and 3 outputs are reused.
# Usage: sbatch --export=ALL,VARIANT=<variant>,OD=<od parquet>,ARCHIVE_SUFFIX=<suffix> this_script
# The existing rerouting_analysis/<variant> folder and the per-variant recovery db are ARCHIVED (renamed with ARCHIVE_SUFFIX), not deleted.
# Needs the Script 4 baseline-demand fix (resiflow/rerouting_baseline.py); the job refuses to run on a checkout without it.
#SBATCH --time=06:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=200G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_stage4_rerun_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_stage4_rerun_%j.err
#SBATCH --exclude=hop059
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird
CODE=${CODE:-/scratch/akothaw/multimodal_hazard_data/code/ResiFlow_harvey}
DATA=/scratch/akothaw/multimodal_hazard_data
: "${VARIANT:?set VARIANT}" "${OD:?set OD}" "${ARCHIVE_SUFFIX:?set ARCHIVE_SUFFIX}"
set -e
test -f $CODE/src/resiflow/rerouting_baseline.py || { echo "CODE lacks the baseline fix: git pull --ff-only from a login node"; exit 3; }
export PYTHONPATH=$CODE/src:$PYTHONPATH
export PROJ_DATA=/scratch/akothaw/conda_envs/nird/lib/python3.10/site-packages/rasterio/proj_data PROJ_LIB=$PROJ_DATA
export RESIFLOW_PARAM_OVERRIDES=$CODE/experiments/conus_multihazard/hopper/overrides/sourced_asset_costs.json
export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_RESULTS_VARIANT=$VARIANT RESIFLOW_RESULTS_VARIANT=$VARIANT
export RESIFLOW_DISABLE_PASSENGER_OD=1 NIRD_DISABLE_PASSENGER_OD=1
export RESIFLOW_FAF5_OD_MATRIX_PATH=$OD NIRD_FAF5_OD_MATRIX_PATH=$OD
export NIRD_DUCKDB_MEMORY_LIMIT=150GB NIRD_DUCKDB_TEMP_DIRECTORY=$DATA/duckdb_tmp_${VARIANT}_stage4rerun
export NIRD_PATH_REALIZATION_STRATEGY=duckdb_chunked_compact NIRD_LCP_DEST_CHUNK_SIZE=1000 NIRD_FLOW_DB_BATCH_SIZE=50000 NIRD_LCP_SORT_BY_DEST_COUNT=1
export RESIFLOW_MAX_FLOW_ITERATIONS=15 NIRD_MAX_FLOW_ITERATIONS=15
export RESIFLOW_HAZARD_TYPE=flood RESIFLOW_FLOOD_SUBTYPE=flood_harvey_houston RESIFLOW_SCENARIO_PARAM=304
export RESIFLOW_STAGE4_EXPORT_OD_PATHS=1
mkdir -p $DATA/recovery_dbs $NIRD_DUCKDB_TEMP_DIRECTORY
export NIRD_RECOVERY_DB_PATH=$DATA/recovery_dbs/${VARIANT}_recovery_304_1.duckdb
R=$DATA/results/rerouting_analysis/$VARIANT
[ -d "$R" ] && [ ! -e "${R}${ARCHIVE_SUFFIX}" ] && mv "$R" "${R}${ARCHIVE_SUFFIX}"
test ! -d "$R" || { echo "$R still exists (archive name taken?)"; exit 4; }
test -d $DATA/results/base_scenario/$VARIANT || { echo "missing base_scenario symlink"; exit 2; }
source $CODE/experiments/common/profile_stage.sh
profile_init stage4_rerun_$VARIANT
profile_stage stage4_rerouting_odpaths python $CODE/scripts/4_rerouting_and_recovery_scenario_loop.py 304 1 20 $SLURM_CPUS_PER_TASK
profile_finish
ls -la $R/304/1 | grep -c odpfc
