#!/bin/bash
#SBATCH --job-name=harvey15_e6_clear2m
#SBATCH --partition=bigmem
# E6 sensitivity on Harvey-15: stages 2, 3, 3-postprocess with a 2.0 m bridge deck clearance (override file bridge_clearance_2m_sourced.json).
# Writes to its OWN results variant (harvey15_e6_clear2m); the baseline is shared through a symlink and the primary outputs are not touched.
# Compare with the primary run (job 3704490): bridge flooded links 2,187, bridges with priced damage 1,235, bridge damage $330.9M, truck-closed bridges 1,718.
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=200G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_harvey15_e6_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_harvey15_e6_%j.err
#SBATCH --exclude=hop059
module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird
CODE=${CODE:-/scratch/akothaw/multimodal_hazard_data/code/ResiFlow_harvey}
set -e
DATA=/scratch/akothaw/multimodal_hazard_data
BASEVARIANT=harvey15_streaming_cpu8
VARIANT=harvey15_e6_clear2m
export PYTHONPATH=$CODE/src:$PYTHONPATH
export PROJ_DATA=/scratch/akothaw/conda_envs/nird/lib/python3.10/site-packages/rasterio/proj_data PROJ_LIB=$PROJ_DATA
export RESIFLOW_PARAM_OVERRIDES=$CODE/experiments/conus_multihazard/hopper/overrides/bridge_clearance_2m_sourced.json
export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_RESULTS_VARIANT=$VARIANT RESIFLOW_RESULTS_VARIANT=$VARIANT
export RESIFLOW_DISABLE_PASSENGER_OD=1 NIRD_DISABLE_PASSENGER_OD=1
export RESIFLOW_FAF5_OD_MATRIX_PATH=$DATA/subset_harvey15/faf5_od_matrix_subset.pq NIRD_FAF5_OD_MATRIX_PATH=$DATA/subset_harvey15/faf5_od_matrix_subset.pq
export NIRD_DUCKDB_MEMORY_LIMIT=150GB NIRD_DUCKDB_TEMP_DIRECTORY=$DATA/duckdb_tmp_harvey15_e6
export NIRD_PATH_REALIZATION_STRATEGY=duckdb_chunked_compact
export RESIFLOW_HAZARD_TYPE=flood RESIFLOW_FLOOD_SUBTYPE=flood_harvey_houston RESIFLOW_SCENARIO_PARAM=304
mkdir -p $NIRD_DUCKDB_TEMP_DIRECTORY
git -C $CODE log --oneline -1
grep -q bridge_deck_clearance_m $CODE/src/resiflow/disruption/flood.py || { echo "CODE lacks the clearance parameter: git pull --ff-only from a login node"; exit 3; }
[ -e $DATA/results/base_scenario/$VARIANT ] || ln -s $DATA/results/$BASEVARIANT $DATA/results/base_scenario/$VARIANT
source $CODE/experiments/common/profile_stage.sh
profile_init harvey15_e6_clear2m
profile_stage stage2_intersection python $CODE/scripts/2_intersection_analysis.py 304 1
profile_stage stage3_damage python $CODE/scripts/3_damage_analysis.py
profile_stage stage3_postprocess python $CODE/scripts/3_postprocess_damage.py
profile_finish
python - <<'PY'
import glob, pandas as pd
from resiflow import damage_aggregation as da
for f in glob.glob("/scratch/akothaw/multimodal_hazard_data/results/damage_analysis/harvey15_e6_clear2m/304/*with_damage_values.csv"):
    d = pd.read_csv(f, low_memory=False)
    e = da.edge_level_damage_musd(d).merge(d.drop_duplicates("e_id")[["e_id", "road_label"]], on="e_id")
    print(e.groupby("road_label").edge_direct_damage_mean_musd.agg(["count", "sum"]).round(3))
    print("TOTAL musd", round(da.total_direct_damage_musd(d), 3))
PY
