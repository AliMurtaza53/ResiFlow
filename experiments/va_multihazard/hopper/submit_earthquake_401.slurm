#!/bin/bash
#SBATCH --job-name=va_earthquake_401
#SBATCH --partition=normal
# Script 3 -> 3_postprocess -> 4 for earthquake (401) against the real
# Mineral, VA ShakeMap PGA raster -- NOT the full 4-hazard orchestrator.
#
# Script 2 is deliberately SKIPPED here: it already completed successfully
# against the real ShakeMap raster in an interactive session on 2026-08-08
# (662.73s runtime, no "[EARTHQUAKE NO_MATCH]" warning -- confirmed it found
# the real hazard data this time, after an earlier attempt silently fell
# back to the synthetic toy source because the aligned raster had been
# written one directory level too shallow, missing the soge_clusters/
# prefix load_config() resolves to). That session's own 2h --time limit hit
# right after Script 2's completion message printed, before Script 3 could
# run, so this job picks up from there rather than repeating an already-
# confirmed-successful 11-minute step.
#
# --partition=normal, --mem=160G: matches the config the OLD NSHM-based
# earthquake run (95 damaged edges) completed on successfully. The real
# ShakeMap-based damaged-edge count for this baseline is not yet confirmed
# (Script 3's own log line for scenario=401 specifically wasn't captured
# before the interactive session was cut off), but ShakeMap is a single-
# event deterministic snapshot concentrated near the Mineral epicenter
# rather than winter_storm's storm-wide footprint, so starting here rather
# than jumping straight to bigmem is a reasonable bet, not a proven one --
# if this OOMs, submit_winter_storm_bigmem.slurm is the template to copy.
#
# --time=06:00:00: matches the original submit_run_multihazard.slurm
# default budget for this hazard.
#
# Note on 3_damage_analysis.py: it takes no scenario-specific args --
# confirmed by reading its source (2026-08-09) that it os.walk()s the
# ENTIRE disruption_analysis/<variant>/ tree and batch-processes every
# scenario's intersections_*.pq it finds in one pass (301, 401, 501, 601,
# whatever exists), not just the one this job's env vars target. Harmless
# (idempotent recompute of already-correct data for the other scenarios)
# but expect it to take longer than "just 401" would, and expect its log to
# print every scenario it walks past, not only 401.
#SBATCH --time=06:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=160G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_earthquake_401_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_earthquake_401_%j.err
#SBATCH --exclude=hop059

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_RESULTS_VARIANT=convergence_cpu8_bounded18
export RESIFLOW_RESULTS_VARIANT=convergence_cpu8_bounded18
export NIRD_DUCKDB_MEMORY_LIMIT=130GB
export NIRD_DUCKDB_TEMP_DIRECTORY=/scratch/akothaw/multimodal_hazard_data/duckdb_tmp_va_multihazard
export NIRD_PATH_REALIZATION_STRATEGY=duckdb_chunked_compact
export NIRD_LCP_DEST_CHUNK_SIZE=1000
export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_LCP_SORT_BY_DEST_COUNT=1
export RESIFLOW_HAZARD_TYPE=earthquake
export RESIFLOW_SCENARIO_PARAM=401

REPO=/scratch/akothaw/multimodal_hazard_data/code/ResiFlow
python $REPO/scripts/3_damage_analysis.py
python $REPO/scripts/3_postprocess_damage.py
python $REPO/scripts/4_rerouting_and_recovery_scenario_loop.py 401 1 20 $SLURM_CPUS_PER_TASK
