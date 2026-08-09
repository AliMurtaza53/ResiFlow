#!/bin/bash
#SBATCH --job-name=harvey_depths_prep
#SBATCH --partition=highmem
#SBATCH --account=<REPLACE_WITH_ACCESS_ALLOCATION>
# Runs scripts/prepare_harvey_depths.py against an EXTRACTED (unzipped) copy
# of Harvey_Depths_3m_Final.gdb -- confirmed locally (2026-08-03, see
# docs/VA_MULTIHAZARD_COMPARISON.md, "Resolved: Harvey wired in as its own
# case study") that reading it live from the 39GB zip is not tractable, even
# via a streaming reproject() that never materializes the full ~84GB array.
# Must unzip first (see the cp/unzip step below).
#
# --partition=highmem: 1,031GB RAM per node (RCAC docs, 2026-08-08) -- the
# reproject only needs to hold one decimated output array plus whatever
# GDAL buffers for reading source blocks, nowhere near this much, but this
# is a first run on unfamiliar infrastructure and generous headroom costs
# nothing but the (explicitly-not-a-concern-right-now) 4x SU multiplier.
# Drop to --partition=shared or --partition=wholenode (257GB) once this is
# timed once, if that's plenty.
#
# --time=04:00:00: not a measured requirement (never run on Anvil before) --
# generous guess. highmem's own cap is 48h if this needs more; check
# progress via the script's own print() timing output in the .out log
# before assuming a rerun needs more.
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=200G
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
  --output /anvil/scratch/$USER/multimodal_hazard_data/inputs/va_multihazard_aligned/flood_harvey_houston/event_1.tif \
  --resolution 50

# The aligned output above is the actual deliverable and small (tens-hundreds
# of MB at 50m over the Houston bbox, not the 84GB source) -- worth copying
# into /anvil/projects/<allocation>/ for permanence once confirmed good,
# since /anvil/scratch purges anything untouched for 30 days.
