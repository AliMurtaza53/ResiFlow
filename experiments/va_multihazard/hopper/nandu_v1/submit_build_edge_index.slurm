#!/bin/bash
#SBATCH --job-name=nandu_odpfc_edge_index
#SBATCH --partition=normal
# One-time build of the (e_id, od_id) index against the conus_nandu_v1 Pass A
# baseline's odpfc.pq -- same fix as
# experiments/va_multihazard/hopper/submit_build_edge_index.slurm (built for
# convergence_cpu8_bounded18), just never run for this newer baseline.
#
# Root cause confirmed 2026-08-20: landslide_501 (job 9415266), winter_storm_601
# (9415269), and harvey_304 (9415270) all SEGFAULTED at the identical point --
# "No prebuilt edge/od_id index at .../conus_nandu_v1/odpfc_edge_index --
# falling back to a direct UNNEST explode" immediately followed by a crash,
# not just slowness. flood_301 (9415264) and earthquake_401 (9415265) were
# still running when this was found and are very likely to hit the same wall.
# See scripts/build_odpfc_edge_index.py's docstring for the full history of
# why the direct-UNNEST fallback is both slow (6h+ unfinished on a 95-edge
# hazard, previously) and, evidently, capable of crashing outright at
# conus_nandu_v1's scale.
#
# Run this ONCE, then resubmit whichever of the 5 nandu_v1 hazard jobs
# crashed or hasn't been (re)run yet against a clean baseline.
#SBATCH --time=16:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_nandu_edge_index_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_nandu_edge_index_%j.err
#SBATCH --exclude=hop059

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json

BASELINE=/scratch/akothaw/multimodal_hazard_data/results/base_scenario/conus_nandu_v1

python /scratch/akothaw/multimodal_hazard_data/code/ResiFlow/scripts/build_odpfc_edge_index.py \
  --odpfc "$BASELINE/odpfc.pq" \
  --output "$BASELINE/odpfc_edge_index" \
  --memory-limit 100GB \
  --temp-directory /scratch/akothaw/multimodal_hazard_data/duckdb_tmp_edge_index_nandu \
  --threads $SLURM_CPUS_PER_TASK
