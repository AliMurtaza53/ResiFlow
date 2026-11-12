#!/bin/bash
#SBATCH --job-name=harvey15_stages2to4
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
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_harvey15_stages2to4_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_harvey15_stages2to4_%j.err
#SBATCH --exclude=hop059
set -e
module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

CODE=/scratch/akothaw/multimodal_hazard_data/code/ResiFlow_dump
export PYTHONPATH=$CODE/src:$PYTHONPATH
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
echo "== baseline check"; ls -la $BASE | head -20
test -f $BASE/edge_flows.gpq || { echo "MISSING $BASE/edge_flows.gpq"; exit 2; }
test -d $BASE/odpfc_parts || { echo "MISSING $BASE/odpfc_parts"; exit 2; }
[ -e $DATA/results/base_scenario/$VARIANT ] || ln -s $BASE $DATA/results/base_scenario/$VARIANT
echo "baseline parts: $(ls $BASE/odpfc_parts | wc -l); symlink: $(readlink $DATA/results/base_scenario/$VARIANT)"

echo "== edge/od index"
python $CODE/scripts/build_odpfc_edge_index.py --odpfc $BASE/odpfc_parts --output $BASE/odpfc_edge_index \
  --memory-limit 250GB --temp-directory $NIRD_DUCKDB_TEMP_DIRECTORY --threads $SLURM_CPUS_PER_TASK

echo "== stage 2 intersection"; python $CODE/scripts/2_intersection_analysis.py 304 1
echo "== stage 3 damage";       python $CODE/scripts/3_damage_analysis.py
echo "== stage 3 postprocess";  python $CODE/scripts/3_postprocess_damage.py
echo "== stage 4 rerouting";    python $CODE/scripts/4_rerouting_and_recovery_scenario_loop.py 304 1 20 $SLURM_CPUS_PER_TASK
echo "== done"
