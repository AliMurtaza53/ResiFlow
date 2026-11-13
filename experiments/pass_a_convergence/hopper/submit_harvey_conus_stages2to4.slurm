#!/bin/bash
#SBATCH --job-name=harvey_conus_s2to4
#SBATCH --partition=bigmem
# Harvey full-CONUS stages 2 -> 3 -> 3 postprocess -> 4 on the baseline from submit_harvey_conus_baseline.slurm (variant harvey_conus_corrected).
# Switches ON: sourced asset costs (T24/T30/Rostami), masked metre Harvey raster, geodesic length check (automatic in stage 2),
# bridge/tunnel once-per-link aggregation, per-directory Script 3 pricing, stage 4 OD path export (RESIFLOW_STAGE4_EXPORT_OD_PATHS=1),
# per-stage profiling. Passenger OFF (F5, provisional). Submit with --dependency=afterok:<baseline job id>.
#SBATCH --time=3-00:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=600G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_harvey_conus_s2to4_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_harvey_conus_s2to4_%j.err
#SBATCH --exclude=hop059
module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird
CODE=${CODE:-/scratch/akothaw/multimodal_hazard_data/code/ResiFlow_harvey}
set -e
DATA=/scratch/akothaw/multimodal_hazard_data
OD=$DATA/inputs_corrected/faf5_od_matrix_conterminous.pq
VARIANT=harvey_conus_corrected
BASE=$DATA/results/$VARIANT
export PYTHONPATH=$CODE/src:$PYTHONPATH
export PROJ_DATA=/scratch/akothaw/conda_envs/nird/lib/python3.10/site-packages/rasterio/proj_data PROJ_LIB=$PROJ_DATA
export RESIFLOW_PARAM_OVERRIDES=$CODE/experiments/conus_multihazard/hopper/overrides/sourced_asset_costs.json
export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_RESULTS_VARIANT=$VARIANT RESIFLOW_RESULTS_VARIANT=$VARIANT
export RESIFLOW_DISABLE_PASSENGER_OD=1 NIRD_DISABLE_PASSENGER_OD=1
export RESIFLOW_FAF5_OD_MATRIX_PATH=$OD NIRD_FAF5_OD_MATRIX_PATH=$OD
export NIRD_DUCKDB_MEMORY_LIMIT=450GB NIRD_DUCKDB_TEMP_DIRECTORY=$DATA/duckdb_tmp_${VARIANT}_s2to4
export NIRD_PATH_REALIZATION_STRATEGY=duckdb_chunked_compact NIRD_LCP_DEST_CHUNK_SIZE=1000 NIRD_FLOW_DB_BATCH_SIZE=50000 NIRD_LCP_SORT_BY_DEST_COUNT=1
export RESIFLOW_MAX_FLOW_ITERATIONS=15 NIRD_MAX_FLOW_ITERATIONS=15
export RESIFLOW_HAZARD_TYPE=flood RESIFLOW_FLOOD_SUBTYPE=flood_harvey_houston RESIFLOW_SCENARIO_PARAM=304
export RESIFLOW_STAGE4_EXPORT_OD_PATHS=1
mkdir -p $NIRD_DUCKDB_TEMP_DIRECTORY
git -C $CODE log --oneline -1 2>/dev/null || echo "(no git on compute node)"
grep -q RESIFLOW_STAGE4_EXPORT_OD_PATHS $CODE/scripts/4_rerouting_and_recovery_scenario_loop.py || { echo "CODE lacks the export switch: git pull --ff-only from a login node"; exit 3; }
test -f $BASE/edge_flows.gpq && test -d $BASE/odpfc_parts || { echo "baseline outputs missing in $BASE"; exit 2; }
[ -e $DATA/results/base_scenario/$VARIANT ] || ln -s $BASE $DATA/results/base_scenario/$VARIANT
source $CODE/experiments/common/profile_stage.sh
profile_init harvey_conus_s2to4
profile_stage edge_index python $CODE/scripts/build_odpfc_edge_index.py --odpfc $BASE/odpfc_parts --output $BASE/odpfc_edge_index --memory-limit 450GB --temp-directory $NIRD_DUCKDB_TEMP_DIRECTORY --threads $SLURM_CPUS_PER_TASK
profile_stage stage2_intersection python $CODE/scripts/2_intersection_analysis.py 304 1
profile_stage stage3_damage python $CODE/scripts/3_damage_analysis.py
profile_stage stage3_postprocess python $CODE/scripts/3_postprocess_damage.py
profile_stage stage4_rerouting_odpaths python $CODE/scripts/4_rerouting_and_recovery_scenario_loop.py 304 1 20 $SLURM_CPUS_PER_TASK
profile_finish
echo "== OD path files"; ls -la $DATA/results/rerouting_analysis/$VARIANT/304/1 | grep -i odpfc || echo "NO odpfc FILES WRITTEN"
echo "== done"
