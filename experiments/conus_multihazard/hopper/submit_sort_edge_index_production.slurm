#!/bin/bash
#SBATCH --job-name=sort_edge_index_prod
#SBATCH --partition=bigmem
# Sorts the REAL convergence_cpu8_bounded18 odpfc_edge_index (92.3B rows,
# ~386GB) by (e_id, od_id) -- see scripts/sort_odpfc_edge_index.py's
# docstring for why, and docs/CONUS_MULTIHAZARD_METHODOLOGY.md for the
# landslide-query evidence (7 damaged edges, 89 minutes, 755GB) that
# motivated this. Verified correct AND effective at toy scale (2026-08-09,
# local: 49.8x fewer rows scanned, identical query results; see also
# submit_verify_edge_index_sort.slurm for the Hopper-side re-check) --
# DO NOT run this until that verification job has actually completed
# successfully. This is the expensive one.
#
# PRE-FLIGHT CHECKS -- do these before submitting, not after:
#   1. Confirm bigmem's real max walltime: `sinfo -p bigmem -o "%P %l"`.
#      --time below is a GUESS, not a measured requirement (this exact
#      operation -- an external sort of 92.3B rows -- has never been timed).
#      If bigmem's actual cap is less than what's set here, lower it to
#      match rather than have the job rejected at submission.
#   2. Confirm scratch has enough free space for an external sort's
#      intermediate sorted runs -- typically needs on the order of 2-3x the
#      input size (~386GB) in temp space on top of the final ~386GB sorted
#      output, so budget ~1.5TB free: `df -h /scratch/akothaw`.
#
# --mem=900G: an external sort's peak memory need is about how many sorted
# runs it merges concurrently, not the full dataset size, so this may be
# more than strictly necessary -- but given the earlier 755GB peak from a
# DIFFERENT (join/dedup, not sort) operation on much less data, staying on
# bigmem for this first real attempt is the defensible choice until we have
# actual measured data on this specific operation's memory profile.
#
# Writes to a NEW directory (odpfc_edge_index_sorted), not in-place --
# verify row counts and a spot-check query against it before swapping it in
# for the live odpfc_edge_index/ (rename old -> _unsorted_backup, rename
# new -> odpfc_edge_index). No code changes needed in
# 4_rerouting_and_recovery_scenario_loop.py either way -- it only cares that
# odpfc_edge_index/part_*.pq exists with (od_id, e_id) columns.
#SBATCH --time=7-00:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=900G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_sort_edge_index_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_sort_edge_index_%j.err
#SBATCH --exclude=hop059

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json

BASELINE=/scratch/akothaw/multimodal_hazard_data/results/base_scenario/convergence_cpu8_bounded18

python /scratch/akothaw/multimodal_hazard_data/code/ResiFlow/scripts/sort_odpfc_edge_index.py \
  --input "$BASELINE/odpfc_edge_index" \
  --output "$BASELINE/odpfc_edge_index_sorted" \
  --memory-limit 800GB \
  --temp-directory /scratch/akothaw/multimodal_hazard_data/duckdb_tmp_edge_sort \
  --threads $SLURM_CPUS_PER_TASK

echo "Sort complete. Verify row counts match before swapping in:"
echo "  duckdb -c \"SELECT COUNT(*) FROM read_parquet('$BASELINE/odpfc_edge_index/part_*.pq')\""
echo "  duckdb -c \"SELECT COUNT(*) FROM read_parquet('$BASELINE/odpfc_edge_index_sorted/part_*.pq')\""
echo "Once confirmed equal, swap in manually (not done automatically by this job):"
echo "  mv $BASELINE/odpfc_edge_index $BASELINE/odpfc_edge_index_unsorted_backup"
echo "  mv $BASELINE/odpfc_edge_index_sorted $BASELINE/odpfc_edge_index"
