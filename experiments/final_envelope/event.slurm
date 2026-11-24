#!/bin/bash
#SBATCH --partition=bigmem
#SBATCH --time=24:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=600G
# One envelope job: Stages 2-4 for one event on one demand case, off the matching frozen baseline.
#   CASE=freight|passenger|combined  EV=<scenario_param from hazards.final_envelope.json>  CODE_SHA=<sha of ResiFlow_final_<sha>>
#   sbatch --export=ALL,CASE=freight,EV=304,CODE_SHA=a9ce7b3 --job-name=finalA_freight_304 event.slurm
# Baseline must exist: results/finalA_<case>_baseline/edge_flows.gpq (final_baseline.slurm). Check the logs for
# "initial number of edges in the network: 487237" and "Initial isolated flows: 0.0" before trusting a run.
set -eo pipefail
: "${CASE:?}" "${EV:?}" "${CODE_SHA:?}"
DATA=/scratch/akothaw/multimodal_hazard_data
CODE=$DATA/code/ResiFlow_final_$CODE_SHA
FROZEN=/home/akothaw/frozen_inputs_networkA_20261123
BASE=$DATA/results/finalA_${CASE}_baseline
VARIANT=finalA_${CASE}_$EV
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird
export PYTHONPATH=$CODE/src:$PYTHONPATH
export PROJ_DATA=/scratch/akothaw/conda_envs/nird/lib/python3.10/site-packages/rasterio/proj_data PROJ_LIB=$PROJ_DATA
export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json NIRD_CONFIG_PATH=$RESIFLOW_CONFIG_PATH
export RESIFLOW_HAZARDS_MANIFEST=$CODE/parameters/hazards.final_envelope.json
export RESIFLOW_DEMAND_CASE=$CASE
export RESIFLOW_FAF5_OD_MATRIX_PATH=$FROZEN/freight_od_T29_gateway_conus.pq NIRD_FAF5_OD_MATRIX_PATH=$FROZEN/freight_od_T29_gateway_conus.pq
export RESIFLOW_FAF5_CONNECTOR_NETWORK=$FROZEN/faf5_road_links.gpq
if [ "$CASE" = freight ]; then export RESIFLOW_DISABLE_PASSENGER_OD=1 NIRD_DISABLE_PASSENGER_OD=1
else export RESIFLOW_PASSENGER_OD_PATH=$FROZEN/passenger_conus_split_od.pq NIRD_PASSENGER_OD_PATH=$FROZEN/passenger_conus_split_od.pq; fi
export RESIFLOW_RESULTS_VARIANT=$VARIANT NIRD_RESULTS_VARIANT=$VARIANT
export RESIFLOW_PARAM_OVERRIDES=$CODE/experiments/conus_multihazard/hopper/overrides/sourced_asset_costs.json
export NIRD_RECOVERY_DB_PATH=$DATA/recovery_dbs/$VARIANT.duckdb
export NIRD_DUCKDB_TEMP_DIRECTORY=$DATA/duckdb_tmp_$VARIANT
export NIRD_DUCKDB_MEMORY_LIMIT=${DUCK_GB:-450}GB NIRD_PATH_REALIZATION_STRATEGY=duckdb_chunked_compact
export NIRD_LCP_DEST_CHUNK_SIZE=1000 NIRD_FLOW_DB_BATCH_SIZE=50000 NIRD_LCP_SORT_BY_DEST_COUNT=1
export RESIFLOW_MAX_FLOW_ITERATIONS=15 NIRD_MAX_FLOW_ITERATIONS=15
export RESIFLOW_STAGE4_EXPORT_OD_PATHS=1 RESIFLOW_GIT_COMMIT=$CODE_SHA
mkdir -p "$NIRD_DUCKDB_TEMP_DIRECTORY" "$DATA/recovery_dbs"
test -s "$BASE/edge_flows.gpq"
[ -e "$DATA/results/base_scenario/$VARIANT" ] || ln -s "$BASE" "$DATA/results/base_scenario/$VARIANT"
source "$CODE/experiments/common/profile_stage.sh"
profile_init "$VARIANT"
profile_stage stage2_intersection python "$CODE/scripts/2_intersection_analysis.py" $EV 1
profile_stage stage3_damage python "$CODE/scripts/3_damage_analysis.py"
profile_stage stage3_postprocess python "$CODE/scripts/3_postprocess_damage.py"
profile_stage stage4_recovery python "$CODE/scripts/4_rerouting_and_recovery_scenario_loop.py" $EV 1 20 "$SLURM_CPUS_PER_TASK"
profile_finish
