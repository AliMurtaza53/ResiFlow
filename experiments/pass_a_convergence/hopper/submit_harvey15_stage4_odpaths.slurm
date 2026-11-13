#!/bin/bash
#SBATCH --job-name=harvey15_stage4_odpaths
#SBATCH --partition=bigmem
# Harvey-15, stage 4 ONLY, with OD path export on (RESIFLOW_STAGE4_EXPORT_OD_PATHS=1), so the rerouted OD paths can be joined to the network.
# Stage 2 and 3 outputs of job 3704490 are reused as is. The earlier stage 4 outputs and recovery db are ARCHIVED (renamed), not deleted.
# Expected ~40 min (stage 4 took 36m35s, 17.7 GiB without path export). FIRST TEST of the export switch: if the export fails, read
# the .err for the first error and report it; do not edit code on Hopper.
#SBATCH --time=06:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=200G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_harvey15_stage4_odpaths_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_harvey15_stage4_odpaths_%j.err
#SBATCH --exclude=hop059
module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird
CODE=${CODE:-/scratch/akothaw/multimodal_hazard_data/code/ResiFlow_harvey}   # must be at the commit that has the export switch (check git log below)
set -e
export PYTHONPATH=$CODE/src:$PYTHONPATH
export PROJ_DATA=/scratch/akothaw/conda_envs/nird/lib/python3.10/site-packages/rasterio/proj_data
export PROJ_LIB=$PROJ_DATA
export RESIFLOW_PARAM_OVERRIDES=$CODE/experiments/conus_multihazard/hopper/overrides/sourced_asset_costs.json
DATA=/scratch/akothaw/multimodal_hazard_data
VARIANT=harvey15_streaming_cpu8
export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$RESIFLOW_CONFIG_PATH
export NIRD_RESULTS_VARIANT=$VARIANT RESIFLOW_RESULTS_VARIANT=$VARIANT
export RESIFLOW_DISABLE_PASSENGER_OD=1 NIRD_DISABLE_PASSENGER_OD=1
export RESIFLOW_FAF5_OD_MATRIX_PATH=$DATA/subset_harvey15/faf5_od_matrix_subset.pq
export NIRD_FAF5_OD_MATRIX_PATH=$RESIFLOW_FAF5_OD_MATRIX_PATH
export NIRD_DUCKDB_MEMORY_LIMIT=150GB NIRD_DUCKDB_TEMP_DIRECTORY=$DATA/duckdb_tmp_harvey15_stage4_odpaths
export NIRD_PATH_REALIZATION_STRATEGY=duckdb_chunked_compact NIRD_LCP_DEST_CHUNK_SIZE=1000 NIRD_FLOW_DB_BATCH_SIZE=50000 NIRD_LCP_SORT_BY_DEST_COUNT=1
export RESIFLOW_MAX_FLOW_ITERATIONS=15 NIRD_MAX_FLOW_ITERATIONS=15
export RESIFLOW_HAZARD_TYPE=flood RESIFLOW_FLOOD_SUBTYPE=flood_harvey_houston RESIFLOW_SCENARIO_PARAM=304
export RESIFLOW_STAGE4_EXPORT_OD_PATHS=1
mkdir -p $NIRD_DUCKDB_TEMP_DIRECTORY
git -C $CODE log --oneline -1 2>/dev/null || echo "(no git on compute node)"
grep -q RESIFLOW_STAGE4_EXPORT_OD_PATHS $CODE/scripts/4_rerouting_and_recovery_scenario_loop.py || { echo "CODE checkout lacks the export switch: git pull --ff-only from a login node first"; exit 3; }
source $CODE/experiments/common/profile_stage.sh
profile_init harvey15_stage4_odpaths
R=$DATA/results/rerouting_analysis/$VARIANT
[ -d "$R" ] && [ ! -e "${R}_v2_nopaths" ] && mv "$R" "${R}_v2_nopaths"
DB=$DATA/soge_clusters/dbs/recovery_304_1.duckdb
[ -e "$DB" ] && [ ! -e "$DATA/soge_clusters/dbs/recovery_304_1.v2_nopaths.duckdb" ] && mv "$DB" "$DATA/soge_clusters/dbs/recovery_304_1.v2_nopaths.duckdb"
test -d $DATA/results/base_scenario/$VARIANT || { echo "missing base_scenario symlink"; exit 2; }
profile_stage stage4_rerouting_odpaths python $CODE/scripts/4_rerouting_and_recovery_scenario_loop.py 304 1 20 $SLURM_CPUS_PER_TASK
profile_finish
echo "== OD path files"; ls -la $R/304/1 | grep -i odpfc || echo "NO odpfc FILES WRITTEN"
echo "== done"
