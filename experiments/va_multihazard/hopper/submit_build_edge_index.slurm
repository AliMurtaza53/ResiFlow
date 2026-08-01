#!/bin/bash
#SBATCH --job-name=va_odpfc_edge_index
#SBATCH --partition=normal
# One-time build of the (e_id, od_id) index against the CONUS Pass A
# baseline's odpfc.pq, so Script 4's per-hazard-event candidate lookup
# (load_odpfc_source) stops re-exploding the full ~9.68M-row path table
# from scratch for every hazard event. Root cause + full history in
# scripts/build_odpfc_edge_index.py's docstring and
# docs/VA_MULTIHAZARD_COMPARISON.md.
#
# A single streaming pass (project + explode + COPY, no chunking -- an
# earlier od_id-range-chunked version backfired: the WHERE filter didn't
# push down through CROSS JOIN UNNEST, so every chunk re-exploded the WHOLE
# table, 346x the real cost. This version pays the explode cost exactly
# once, but has no per-chunk progress output -- to check it's actually
# moving (not hung), watch the output file grow:
#   watch -n 30 'ls -la $BASELINE/odpfc_edge_index/part_000000000000.pq'
# Run this ONCE per baseline variant; after it exists, run
# submit_run_multihazard.slurm again and all 4 hazard events reuse it.
#
# Time budget generous (16h) since we don't yet have a clean measurement of
# this single-pass query's real duration -- the closest data point is the
# earlier CROSS JOIN UNNEST + JOIN attempt (95 damaged edges), which ran 6h+
# without finishing; a plain explode with no join/filter writes strictly
# more output than that attempt would have, so budget accordingly rather
# than assume faster.
#SBATCH --time=16:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_edge_index_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_edge_index_%j.err

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json

BASELINE=/scratch/akothaw/multimodal_hazard_data/results/base_scenario/convergence_cpu8_bounded18

python /scratch/akothaw/multimodal_hazard_data/code/ResiFlow/scripts/build_odpfc_edge_index.py \
  --odpfc "$BASELINE/odpfc.pq" \
  --output "$BASELINE/odpfc_edge_index" \
  --memory-limit 100GB \
  --temp-directory /scratch/akothaw/multimodal_hazard_data/duckdb_tmp_edge_index \
  --threads $SLURM_CPUS_PER_TASK
