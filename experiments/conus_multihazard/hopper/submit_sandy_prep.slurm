#!/bin/bash
#SBATCH --job-name=sandy_depths_prep
#SBATCH --partition=normal
# Mosaics the 4 Hurricane Sandy state-clipped depth grids (CT/NJ/NY/RI) into
# one aligned flood_sandy_northeast input -- see
# scripts/prepare_sandy_depths.py. Companion to submit_harvey_prep.slurm;
# Sandy's 4 source files total under 2GB on disk (vs Harvey's 84GB
# extracted), so no separate extraction step is needed here, just an rsync.
#
# PRE-FLIGHT: the 4 raw tifs (ct3m0214c.tif, nj3m0214c.tif, nys3m0214c.tif,
# ri3m0214c.tif) must already be under
# /scratch/akothaw/multimodal_hazard_data/inputs_raw/flood/ (rsync from
# local inputs/multihazard_raw/flood/).
#
# --mem=16G: build_sandy_mosaic() streams each source via reproject()+
# rasterio.band() (never a full src.read() -- confirmed locally 2026-09-10,
# NJ's raw array alone is ~14GB uncompressed but the destination array at
# 50m is only ~59M px / ~230MB per float64 accumulator). Generous margin
# over the ~1GB observed locally, not a measured cluster requirement.
#
# --time=01:00:00: local run took ~2 minutes; generous margin for a
# possibly slower/shared filesystem, not a measured cluster requirement.
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_sandy_prep_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_sandy_prep_%j.err
#SBATCH --exclude=hop059

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json

RAW=/scratch/akothaw/multimodal_hazard_data/inputs_raw/flood
REPO=/scratch/akothaw/multimodal_hazard_data/code/ResiFlow

python "$REPO/scripts/prepare_sandy_depths.py" \
  --raw-dir "$RAW" \
  --output /scratch/akothaw/multimodal_hazard_data/soge_clusters/inputs/multihazard_aligned/flood_sandy_northeast/event_1.tif \
  --resolution 50

echo "Prep complete. Verify output before submitting submit_sandy_305.slurm:"
echo "  ls -la /scratch/akothaw/multimodal_hazard_data/soge_clusters/inputs/multihazard_aligned/flood_sandy_northeast/"
