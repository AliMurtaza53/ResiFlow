#!/bin/bash
#SBATCH --job-name=flood_conus_stages
#SBATCH --partition=bigmem
# A real flood on the finished full-CONUS freight baseline (variant harvey_conus_corrected; the baseline does not depend on the hazard).
# Usage: sbatch --export=ALL,VARIANT=<new variant>,SCEN=305,SUBTYPE=flood_sandy_northeast,OVERRIDES=<file>,STAGE4=1 this_script
# Results go to their own variant folders; the baseline is shared through a symlink. STAGE4=0 runs stages 2, 3 and 3-postprocess only.
# Stage 4 exports OD paths (RESIFLOW_STAGE4_EXPORT_OD_PATHS=1). Every stage is profiled. Passenger off (register F5).
#SBATCH --time=08:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=200G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_flood_conus_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_flood_conus_%j.err
#SBATCH --exclude=hop059
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird
CODE=${CODE:-/scratch/akothaw/multimodal_hazard_data/code/ResiFlow_harvey}
DATA=/scratch/akothaw/multimodal_hazard_data
: "${VARIANT:?}" "${SCEN:?}" "${SUBTYPE:?}" "${OVERRIDES:?}"
BASEVARIANT=${BASEVARIANT:-harvey_conus_corrected}
OD=$DATA/inputs_corrected/faf5_od_matrix_conterminous.pq
set -e
test -f $CODE/src/resiflow/rerouting_baseline.py || { echo "CODE lacks the baseline fix: git pull --ff-only from a login node"; exit 3; }
test -f $CODE/experiments/conus_multihazard/hopper/overrides/$OVERRIDES || { echo "missing override $OVERRIDES"; exit 3; }
export PYTHONPATH=$CODE/src:$PYTHONPATH
export PROJ_DATA=/scratch/akothaw/conda_envs/nird/lib/python3.10/site-packages/rasterio/proj_data PROJ_LIB=$PROJ_DATA
export RESIFLOW_PARAM_OVERRIDES=$CODE/experiments/conus_multihazard/hopper/overrides/$OVERRIDES
export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_RESULTS_VARIANT=$VARIANT RESIFLOW_RESULTS_VARIANT=$VARIANT
export RESIFLOW_DISABLE_PASSENGER_OD=1 NIRD_DISABLE_PASSENGER_OD=1
export RESIFLOW_FAF5_OD_MATRIX_PATH=$OD NIRD_FAF5_OD_MATRIX_PATH=$OD
export NIRD_DUCKDB_MEMORY_LIMIT=150GB NIRD_DUCKDB_TEMP_DIRECTORY=$DATA/duckdb_tmp_${VARIANT}
export NIRD_PATH_REALIZATION_STRATEGY=duckdb_chunked_compact NIRD_LCP_DEST_CHUNK_SIZE=1000 NIRD_FLOW_DB_BATCH_SIZE=50000 NIRD_LCP_SORT_BY_DEST_COUNT=1
export RESIFLOW_MAX_FLOW_ITERATIONS=15 NIRD_MAX_FLOW_ITERATIONS=15
export RESIFLOW_HAZARD_TYPE=flood RESIFLOW_FLOOD_SUBTYPE=$SUBTYPE RESIFLOW_SCENARIO_PARAM=$SCEN
export RESIFLOW_STAGE4_EXPORT_OD_PATHS=1
mkdir -p $DATA/recovery_dbs $NIRD_DUCKDB_TEMP_DIRECTORY
export NIRD_RECOVERY_DB_PATH=$DATA/recovery_dbs/${VARIANT}_recovery_${SCEN}_1.duckdb
[ -e $DATA/results/base_scenario/$VARIANT ] || ln -s $DATA/results/$BASEVARIANT $DATA/results/base_scenario/$VARIANT
echo "variant=$VARIANT scen=$SCEN subtype=$SUBTYPE overrides=$OVERRIDES stage4=${STAGE4:-1}"
source $CODE/experiments/common/profile_stage.sh
profile_init flood_conus_$VARIANT
profile_stage stage2_intersection python $CODE/scripts/2_intersection_analysis.py $SCEN 1
profile_stage stage3_damage python $CODE/scripts/3_damage_analysis.py
profile_stage stage3_postprocess python $CODE/scripts/3_postprocess_damage.py
python - <<PY
import glob, pandas as pd
from resiflow import damage_aggregation as da
for f in glob.glob("$DATA/results/damage_analysis/$VARIANT/$SCEN/*with_damage_values.csv"):
    d = pd.read_csv(f, low_memory=False)
    e = da.edge_level_damage_musd(d).merge(d.drop_duplicates("e_id")[["e_id", "road_label"]], on="e_id")
    print("links with damage rows:", d.e_id.nunique()); print(e.groupby("road_label").edge_direct_damage_mean_musd.agg(["count", "sum"]).round(3))
    print("TOTAL musd", round(da.total_direct_damage_musd(d), 3))
PY
if [ "${STAGE4:-1}" = "1" ]; then
  profile_stage stage4_rerouting_odpaths python $CODE/scripts/4_rerouting_and_recovery_scenario_loop.py $SCEN 1 20 $SLURM_CPUS_PER_TASK
fi
profile_finish
echo "== done"
