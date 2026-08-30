#!/bin/bash
#SBATCH --job-name=landslide_501
#SBATCH --partition=bigmem
# Full Script 2 -> 3 -> 3_postprocess -> 4 sequence for landslide (501) --
# NOT the full 4-hazard orchestrator. Confirmed on Hopper (2026-08-08) that
# NOTHING exists yet for this scenario under convergence_cpu8_bounded18
# (no disruption_analysis, damage_analysis, or rerouting_analysis output at
# all) -- Script 2 has never run for scenario_param=501 against this
# baseline, unlike flood/earthquake/winter_storm which all have at least
# partial history. This does the whole thing from scratch in one job rather
# than needlessly re-running the other 3 hazards through the full
# orchestrator.
#
# --partition=bigmem, defensively: landslide's damaged-edge count for this
# baseline is genuinely UNKNOWN (never run before) -- HAZUS PGD-derived
# susceptibility covers a meaningful fraction of western VA's mountainous
# terrain, so this could plausibly land anywhere between flood's ~1 edge
# and winter_storm's 11,556. Given the normal partition's ~180GB ceiling
# cost three separate rounds of debugging for winter_storm (see
# docs/CONUS_MULTIHAZARD_METHODOLOGY.md, "Resolved: Stage 2 row explosion for
# widespread hazards"), running this on bigmem from the start avoids
# repeating that even though load_odpfc_source's narrow-then-widen fix now
# applies automatically regardless of hazard.
#
# --time=24:00:00: same margin as submit_winter_storm_bigmem.slurm -- not a
# measured requirement for this specific hazard, just generous headroom;
# bigmem allows up to 7 days if this proves insufficient.
#SBATCH --time=24:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=900G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_landslide_501_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_landslide_501_%j.err
#SBATCH --exclude=hop059

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_RESULTS_VARIANT=convergence_cpu8_bounded18
export RESIFLOW_RESULTS_VARIANT=convergence_cpu8_bounded18
export NIRD_DUCKDB_MEMORY_LIMIT=800GB
export NIRD_DUCKDB_TEMP_DIRECTORY=/scratch/akothaw/multimodal_hazard_data/duckdb_tmp_multihazard
export NIRD_PATH_REALIZATION_STRATEGY=duckdb_chunked_compact
export NIRD_LCP_DEST_CHUNK_SIZE=1000
export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_LCP_SORT_BY_DEST_COUNT=1
export RESIFLOW_HAZARD_TYPE=landslide
export RESIFLOW_SCENARIO_PARAM=501

REPO=/scratch/akothaw/multimodal_hazard_data/code/ResiFlow
python $REPO/scripts/2_intersection_analysis.py 501 1
python $REPO/scripts/3_damage_analysis.py
python $REPO/scripts/3_postprocess_damage.py
python $REPO/scripts/4_rerouting_and_recovery_scenario_loop.py 501 1 20 $SLURM_CPUS_PER_TASK
