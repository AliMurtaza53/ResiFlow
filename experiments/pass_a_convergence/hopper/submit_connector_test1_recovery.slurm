#!/bin/bash
#SBATCH --job-name=ct1_native_recovery
#SBATCH --partition=bigmem
#SBATCH --time=24:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=400G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_ct1_native_recovery_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_ct1_native_recovery_%j.err

set -eo pipefail
DATA=/scratch/akothaw/multimodal_hazard_data
CODE=$DATA/code/ResiFlow_connector_test1
INPUT=$DATA/stage2_scripts/connector_test1_inputs
VARIANT=harvey15_connector_test1_native
BASE=$DATA/results/$VARIANT
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird
export PYTHONPATH=$CODE/src:$PYTHONPATH
export PROJ_DATA=/scratch/akothaw/conda_envs/nird/lib/python3.10/site-packages/rasterio/proj_data
export PROJ_LIB=$PROJ_DATA
export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$RESIFLOW_CONFIG_PATH
export RESIFLOW_RESULTS_VARIANT=$VARIANT NIRD_RESULTS_VARIANT=$VARIANT
export RESIFLOW_DISABLE_PASSENGER_OD=1 NIRD_DISABLE_PASSENGER_OD=1
export RESIFLOW_FAF5_OD_MATRIX_PATH=$INPUT/faf5_od_matrix_subset.pq
export NIRD_FAF5_OD_MATRIX_PATH=$RESIFLOW_FAF5_OD_MATRIX_PATH
export RESIFLOW_FAF5_CONNECTOR_NETWORK=$INPUT/faf5_road_links.gpq
export RESIFLOW_PARAM_OVERRIDES=$CODE/experiments/conus_multihazard/hopper/overrides/sourced_asset_costs.json
export NIRD_RECOVERY_DB_PATH=$INPUT/recovery.duckdb
export NIRD_DUCKDB_TEMP_DIRECTORY=$DATA/duckdb_tmp_ct1_native_recovery
export NIRD_DUCKDB_MEMORY_LIMIT=300GB NIRD_PATH_REALIZATION_STRATEGY=duckdb_chunked_compact
export NIRD_LCP_DEST_CHUNK_SIZE=1000 NIRD_FLOW_DB_BATCH_SIZE=50000 NIRD_LCP_SORT_BY_DEST_COUNT=1
export RESIFLOW_MAX_FLOW_ITERATIONS=15 NIRD_MAX_FLOW_ITERATIONS=15
export RESIFLOW_HAZARD_TYPE=flood RESIFLOW_FLOOD_SUBTYPE=flood_harvey_houston RESIFLOW_SCENARIO_PARAM=304
export RESIFLOW_STAGE4_EXPORT_OD_PATHS=1
mkdir -p "$NIRD_DUCKDB_TEMP_DIRECTORY"
test -s "$BASE/edge_flows.gpq"
source "$CODE/experiments/common/profile_stage.sh"
profile_init "$VARIANT"
audit="$CODE/scripts/diagnostics/audit_faf_centroid_shortcuts.py"
mapping="$INPUT/connector_crosswalk.csv"
profile_stage baseline_audit python "$audit" "$mapping" "$BASE/odpfc_parts/*.pq" | tee "$INPUT/baseline_shortcuts.log"
if grep -q 'escalate=True' "$INPUT/baseline_shortcuts.log"; then exit 42; fi
[ -e "$DATA/results/base_scenario/$VARIANT" ] || ln -s "$BASE" "$DATA/results/base_scenario/$VARIANT"
profile_stage edge_index python "$CODE/scripts/build_odpfc_edge_index.py" --odpfc "$BASE/odpfc_parts" --output "$BASE/odpfc_edge_index" --memory-limit 250GB --temp-directory "$NIRD_DUCKDB_TEMP_DIRECTORY" --threads "$SLURM_CPUS_PER_TASK"
profile_stage stage2_intersection python "$CODE/scripts/2_intersection_analysis.py" 304 1
profile_stage stage3_damage python "$CODE/scripts/3_damage_analysis.py"
profile_stage stage3_postprocess python "$CODE/scripts/3_postprocess_damage.py"
profile_stage stage4_recovery python "$CODE/scripts/4_rerouting_and_recovery_scenario_loop.py" 304 1 20 "$SLURM_CPUS_PER_TASK"
out="$DATA/results/rerouting_analysis/$VARIANT/304/1"
for day in 0 7 14 30 60 90; do
  for suffix in "" _baseline; do
    test -s "$out/odpfc_freight_s1_day${day}${suffix}.pq"
    python "$audit" "$mapping" "$out/odpfc_freight_s1_day${day}${suffix}.pq"
  done
done | tee "$INPUT/recovery_shortcuts.log"
profile_finish
if grep -q 'escalate=True' "$INPUT/recovery_shortcuts.log"; then exit 42; fi
