#!/bin/bash
#SBATCH --job-name=harvey_depths_prep
#SBATCH --partition=normal
# Hopper port of experiments/conus_multihazard/anvil/submit_harvey_depths.slurm --
# that version targets /anvil/scratch/ paths and needs an ACCESS allocation
# not yet available (credit exchange pending). scripts/prepare_harvey_depths.py
# itself is cluster-agnostic (just --input/--output paths), so only the SLURM
# wrapper needed porting.
#
# Runs scripts/prepare_harvey_depths.py against an EXTRACTED (unzipped) copy
# of Harvey_Depths_3m_Final.gdb -- confirmed (2026-08-03, see
# docs/CONUS_MULTIHAZARD_METHODOLOGY.md, "Resolved: Harvey wired in as its own
# case study") that reading it live from the 39GB zip is not tractable, even
# via a streaming reproject() that never materializes the full ~84GB array.
#
# PRE-FLIGHT: the raw zip must already be transferred to
# /scratch/akothaw/multimodal_hazard_data/inputs_raw/ (rsync from local, see
# the message this script was handed over with) and scratch quota must have
# room for the ~84GB extracted geodatabase on top of the 37GB zip.
#
# --mem=64G: prepare_harvey_depths.py's reproject() is streaming (rasterio.band()
# as source, confirmed never materializes more than the small decimated output
# array -- a few hundred MB at 50m over the Houston bbox, not the 84GB source).
# Matches the Anvil version's sizing; revisit only if this OOMs.
#
# --time=04:00:00: not a measured requirement (never run before on any
# cluster) -- generous guess matching the Anvil version.
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_harvey_prep_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_harvey_prep_%j.err
#SBATCH --exclude=hop059

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json

RAW=/scratch/akothaw/multimodal_hazard_data/inputs_raw
REPO=/scratch/akothaw/multimodal_hazard_data/code/ResiFlow

# Extract once -- ~84GB, check scratch headroom before this runs. Skips
# cleanly if already extracted from a prior attempt.
if [ ! -d "$RAW/Harvey_Depths_3m_Final.gdb" ]; then
  cd "$RAW"
  unzip -q Harvey_Depths_3m_Final.gdb.zip
fi

python "$REPO/scripts/prepare_harvey_depths.py" \
  --input "$RAW/Harvey_Depths_3m_Final.gdb" \
  --output /scratch/akothaw/multimodal_hazard_data/soge_clusters/inputs/multihazard_aligned/flood_harvey_houston/event_1.tif \
  --resolution 50

echo "Prep complete. Verify output before submitting submit_harvey_304.slurm:"
echo "  ls -la /scratch/akothaw/multimodal_hazard_data/soge_clusters/inputs/multihazard_aligned/flood_harvey_houston/"
