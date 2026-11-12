#!/bin/bash
#SBATCH --job-name=harvey15_stages2to4_v2
#SBATCH --partition=bigmem
# Harvey-15, stages after the baseline: edge/od index -> 2 intersection -> 3 damage -> 3 postprocess -> 4 rerouting+recovery.
# Submitted with --dependency=afterok:<baseline job 3689251>, so it starts only if the baseline (15 iterations) exits 0.
# Baseline outputs live in results/harvey15_streaming_cpu8; the scripts read results/base_scenario/<variant>, so that path is a symlink.
# Same flood hazard as experiments/conus_multihazard/hopper/submit_harvey_304.slurm (304, flood_harvey_houston, raster already
# prepared on Hopper: inputs/multihazard_aligned/flood_harvey_houston/event_1.tif). Same OD subset as the baseline (stage 4 reloads demand).
# bigmem 400G (harvey_304 asked 900G for the full-CONUS baseline; this baseline has ~half the demand and 15 iterations). 24 h ceiling.
#SBATCH --time=24:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=400G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_harvey15_stages2to4_v2_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_harvey15_stages2to4_v2_%j.err
#SBATCH --exclude=hop059
module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

CODE=/scratch/akothaw/multimodal_hazard_data/code/ResiFlow_harvey   # branch tip with the bridge/tunnel aggregation fix
set -e
export PYTHONPATH=$CODE/src:$PYTHONPATH
# Nov 2026 env rebuild: conda PROJ db (layout 1.5) vs pip rasterio/pyogrio (needs >= 1.6); use rasterio's bundled db.
export PROJ_DATA=/scratch/akothaw/conda_envs/nird/lib/python3.10/site-packages/rasterio/proj_data
export PROJ_LIB=$PROJ_DATA
# Flood damage priced with the sourced costs (T24 CP25 roads, T30 bridges, Rostami tunnels).
export RESIFLOW_PARAM_OVERRIDES=$CODE/experiments/conus_multihazard/hopper/overrides/sourced_asset_costs.json
DATA=/scratch/akothaw/multimodal_hazard_data
VARIANT=harvey15_streaming_cpu8

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_RESULTS_VARIANT=$VARIANT
export RESIFLOW_RESULTS_VARIANT=$VARIANT
export RESIFLOW_DISABLE_PASSENGER_OD=1
export NIRD_DISABLE_PASSENGER_OD=1
export RESIFLOW_FAF5_OD_MATRIX_PATH=$DATA/subset_harvey15/faf5_od_matrix_subset.pq
export NIRD_FAF5_OD_MATRIX_PATH=$RESIFLOW_FAF5_OD_MATRIX_PATH
export NIRD_DUCKDB_MEMORY_LIMIT=300GB
export NIRD_DUCKDB_TEMP_DIRECTORY=$DATA/duckdb_tmp_harvey15_stages2to4
export NIRD_PATH_REALIZATION_STRATEGY=duckdb_chunked_compact
export NIRD_LCP_DEST_CHUNK_SIZE=1000
export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_LCP_SORT_BY_DEST_COUNT=1
export RESIFLOW_MAX_FLOW_ITERATIONS=15
export NIRD_MAX_FLOW_ITERATIONS=15
export RESIFLOW_HAZARD_TYPE=flood
export RESIFLOW_FLOOD_SUBTYPE=flood_harvey_houston
export RESIFLOW_SCENARIO_PARAM=304
mkdir -p $NIRD_DUCKDB_TEMP_DIRECTORY

python -c "import resiflow; print('resiflow imported from:', resiflow.__file__)"

BASE=$DATA/results/$VARIANT
echo "== archive the invalid first-run outputs (flood depths in feet read as metres, bridge double counting, PROJ-broken CRS)"
for st in damage_analysis disruption_analysis rerouting_analysis; do
  src=$DATA/results/$st/$VARIANT
  [ -d "$src" ] && [ ! -e "${src}_INVALID_feet_double_count" ] && mv "$src" "${src}_INVALID_feet_double_count"
done
[ -e $DATA/soge_clusters/dbs/recovery_304_1.duckdb ] && [ ! -e $DATA/soge_clusters/dbs/recovery_304_1.INVALID.duckdb ] && mv $DATA/soge_clusters/dbs/recovery_304_1.duckdb $DATA/soge_clusters/dbs/recovery_304_1.INVALID.duckdb
echo "== baseline check"; ls -la $BASE | head -20
test -f $BASE/edge_flows.gpq || { echo "MISSING $BASE/edge_flows.gpq"; exit 2; }
test -d $BASE/odpfc_parts || { echo "MISSING $BASE/odpfc_parts"; exit 2; }
[ -e $DATA/results/base_scenario/$VARIANT ] || ln -s $BASE $DATA/results/base_scenario/$VARIANT
echo "baseline parts: $(ls $BASE/odpfc_parts | wc -l); symlink: $(readlink $DATA/results/base_scenario/$VARIANT)"

echo "== edge/od index (skipped if already built)"
[ -d $BASE/odpfc_edge_index ] && ls $BASE/odpfc_edge_index | head -2 || python $CODE/scripts/build_odpfc_edge_index.py --odpfc $BASE/odpfc_parts --output $BASE/odpfc_edge_index \
  --memory-limit 250GB --temp-directory $NIRD_DUCKDB_TEMP_DIRECTORY --threads $SLURM_CPUS_PER_TASK

echo "== stage 2 intersection"; python $CODE/scripts/2_intersection_analysis.py 304 1
echo "== stage 3 damage";       python $CODE/scripts/3_damage_analysis.py
echo "== stage 3 postprocess";  python $CODE/scripts/3_postprocess_damage.py
echo "== corrected damage totals (each bridge/tunnel counted once, roads summed)"
python - <<'PY'
import glob, pandas as pd
from resiflow import damage_aggregation as da
for f in glob.glob("/scratch/akothaw/multimodal_hazard_data/results/damage_analysis/harvey15_streaming_cpu8/304/*with_damage_values.csv"):
    d = pd.read_csv(f, low_memory=False)
    print(f.split("/")[-1], "| rows", len(d), "| links", d.e_id.nunique())
    e = da.edge_level_damage_musd(d).merge(d.drop_duplicates("e_id")[["e_id", "road_label"]], on="e_id")
    print(e.groupby("road_label").edge_direct_damage_mean_musd.agg(["count", "sum"]).round(3))
    print("TOTAL musd", round(da.total_direct_damage_musd(d), 3))
PY
echo "== stage 4 rerouting";    python $CODE/scripts/4_rerouting_and_recovery_scenario_loop.py 304 1 20 $SLURM_CPUS_PER_TASK
echo "== done"
