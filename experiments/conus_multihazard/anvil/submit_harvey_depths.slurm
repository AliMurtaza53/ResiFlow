#!/bin/bash
#SBATCH --job-name=harvey_depths_prep
#SBATCH --partition=shared
#SBATCH --account=<REPLACE_WITH_ACCESS_ALLOCATION>
# Runs scripts/prepare_harvey_depths.py against an EXTRACTED (unzipped) copy
# of Harvey_Depths_3m_Final.gdb -- confirmed locally (2026-08-03, see
# docs/CONUS_MULTIHAZARD_METHODOLOGY.md, "Resolved: Harvey wired in as its own
# case study") that reading it live from the 39GB zip is not tractable, even
# via a streaming reproject() that never materializes the full ~84GB array.
# Must unzip first (see the cp/unzip step below).
#
# --partition=shared, not highmem: verified via RCAC docs (2026-08-08) that
# highmem is NODE-EXCLUSIVE -- bills for the full 128 cores regardless of
# --cpus-per-task, at a 4x multiplier (512 SU/hour). shared bills only for
# the cores/memory fraction actually requested, no node-exclusive penalty.
# prepare_harvey_depths.py's reproject() is streaming (rasterio.band() as
# source, confirmed locally it never materializes more than the small
# decimated output array -- a few hundred MB at 50m over the Houston bbox,
# not the 84GB source), so the 1TB highmem nodes buy nothing here that
# --mem=64G on shared doesn't already cover. Revisit only if this OOMs.
#
# --time=04:00:00: not a measured requirement (never run on Anvil before) --
# generous guess; shared allows up to 96h if this needs more.
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --output=/anvil/scratch/%u/multimodal_hazard_project/logs_harvey_depths_%j.out
#SBATCH --error=/anvil/scratch/%u/multimodal_hazard_project/logs_harvey_depths_%j.err

module purge
module load conda
# Unverified on Anvil (first run, no access to test directly) -- RCAC's
# conda module is documented to make `conda activate` work directly in a
# batch script, unlike Hopper's raw miniforge install which needed
# `source .../activate <env>` instead. If this line fails/no-ops silently
# (env vars like $CONDA_PREFIX not set afterward), that's the first thing
# to check.
conda activate /anvil/scratch/$USER/conda_envs/nird

export RESIFLOW_CONFIG_PATH=/anvil/scratch/$USER/multimodal_hazard_project/config_anvil.json
export NIRD_CONFIG_PATH=/anvil/scratch/$USER/multimodal_hazard_project/config_anvil.json

RAW=/anvil/scratch/$USER/multimodal_hazard_data/inputs_raw
REPO=/anvil/scratch/$USER/multimodal_hazard_data/code/ResiFlow

# Extract once -- ~84GB, check `myquota`/scratch headroom before this runs.
# Skips cleanly if already extracted from a prior attempt.
if [ ! -d "$RAW/Harvey_Depths_3m_Final.gdb" ]; then
  cd "$RAW"
  unzip -q Harvey_Depths_3m_Final.gdb.zip
fi

python "$REPO/scripts/prepare_harvey_depths.py" \
  --input "$RAW/Harvey_Depths_3m_Final.gdb" \
  --output /anvil/scratch/$USER/multimodal_hazard_data/inputs/multihazard_aligned/flood_harvey_houston/event_1.tif \
  --resolution 50

# The aligned output above is the actual deliverable and small (tens-hundreds
# of MB at 50m over the Houston bbox, not the 84GB source) -- worth copying
# into /anvil/projects/<allocation>/ for permanence once confirmed good,
# since /anvil/scratch purges anything untouched for 30 days.
