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
# Chunked by od_id range (bounded per-chunk memory, visible tqdm progress --
# not one opaque multi-hour query) and streamed straight to parquet via
# COPY (no fetchdf() materialization). Run this ONCE per baseline variant;
# after it exists, run submit_run_multihazard.slurm again and all 4 hazard
# events reuse it.
#SBATCH --time=08:00:00
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
