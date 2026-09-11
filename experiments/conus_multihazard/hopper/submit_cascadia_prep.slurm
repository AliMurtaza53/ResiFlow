#!/bin/bash
#SBATCH --job-name=cascadia_prep
#SBATCH --partition=normal
# Prepares the Cascadia M9 earthquake (404) and its co-seismic landslide
# (502) aligned inputs: PGA + SA(1.0) companion from the user's
# shake_result.hdf, n10 susceptibility realigned onto Cascadia's own grid,
# then the HAZUS Newmark PGD itself. See scripts/prepare_cascadia_pga.py's
# module docstring for the full 5-step chain this script runs.
#
# PRE-FLIGHT: confirmed via read-only SSH (2026-09-11) that Hopper's real
# raw-data convention for earthquake sources is inputs_raw/earthquake/<name>/
# (e.g. inputs_raw/earthquake/mineral_shakemap/pga_g.tif already exists there)
# -- NOT under soge_clusters/inputs/multihazard_raw/ (an earlier draft of this
# script incorrectly assumed that). Fixed to match. Two files must be rsynced
# there before this runs, neither present on Hopper yet (confirmed via find):
#   Cascadia9_shake_result.hdf -> inputs_raw/ (small, a few MB)
#   n10_conus.tif -> inputs_raw/landslide/n10_susc/ (the raw susceptibility
#     source -- also confirmed NOT present anywhere on Hopper's scratch,
#     unlike its ALREADY-aligned Mineral-grid counterpart,
#     landslide_susceptibility, which does exist)
#
# ALSO REQUIRED before this runs: soge_clusters/inputs/va_multihazard_aligned
# must be renamed to multihazard_aligned (confirmed via read-only SSH
# 2026-09-11 that it's still under the pre-de-VA-rename name on Hopper's
# actual filesystem, even though the code was renamed weeks ago -- the
# rename commit's own message flagged this exact gap: "the matching Hopper
# scratch directories still need the same mv, done by hand since I only have
# read-only SSH there"). Without this, every EXISTING real-data scenario
# (Harvey, Mineral, New Madrid, landslide/501, Jonas/Uri/Elliott/
# Snowmageddon) silently can't find its aligned raster under the new code.
#
# --mem=32G, --time=01:00:00: local run (2026-09-11) completed the full
# 5-step chain in well under 10 minutes despite each aligned raster being
# ~1 billion pixels (Cascadia's own-bounds footprint spans northern
# California to the Canadian border, so even at 50m it's a big grid -- 2.6GB
# per aligned file on disk). Generous margin over the local runtime for a
# possibly slower/shared cluster filesystem, not a measured cluster
# requirement.
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_cascadia_prep_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_cascadia_prep_%j.err
#SBATCH --exclude=hop059

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json

RAW=/scratch/akothaw/multimodal_hazard_data/inputs_raw
DATA=/scratch/akothaw/multimodal_hazard_data/soge_clusters
REPO=/scratch/akothaw/multimodal_hazard_data/code/ResiFlow

# 1. Extract PGA (ln(g) -> linear g) from the HDF, native ~2km EPSG:4326 grid.
python "$REPO/scripts/prepare_cascadia_pga.py" \
  --input "$RAW/Cascadia9_shake_result.hdf" \
  --output "$RAW/earthquake/cascadia_m9_scenario/pga_g.tif"

# 2. Extract SA(1.0) companion (bridge fragility needs it -- see script docstring).
python "$REPO/scripts/prepare_cascadia_pga.py" \
  --input "$RAW/Cascadia9_shake_result.hdf" \
  --imt "SA(1.0)" \
  --output "$RAW/earthquake/cascadia_m9_scenario/sa1p0_g.tif"

# 3. Align PGA to its own bounds at 50m/EPSG:9311 (zero overlap with the VA
#    reference grid, same reasoning as New Madrid's own-bounds alignment).
python "$REPO/scripts/align_hazard_rasters.py" \
  --input "$RAW/earthquake/cascadia_m9_scenario/pga_g.tif" \
  --own-bounds --resolution 50 \
  --output "$DATA/inputs/multihazard_aligned/earthquake_cascadia_m9_scenario/event_1.tif"

# 4. Align SA(1.0) onto PGA's SAME grid (--reference, not --own-bounds again).
python "$REPO/scripts/align_hazard_rasters.py" \
  --input "$RAW/earthquake/cascadia_m9_scenario/sa1p0_g.tif" \
  --reference "$DATA/inputs/multihazard_aligned/earthquake_cascadia_m9_scenario/event_1.tif" \
  --output "$DATA/inputs/multihazard_aligned/earthquake_cascadia_m9_scenario_sa1p0/event_1.tif"

# 5. Realign the raw n10 susceptibility raster onto Cascadia's PGA grid --
#    landslide and PGA must share one grid (compute_landslide_pgd.py enforces
#    this); Mineral's existing aligned susceptibility is on VA's grid, not
#    Cascadia's own-bounds one.
python "$REPO/scripts/align_hazard_rasters.py" \
  --input "$RAW/landslide/n10_susc/n10_conus.tif" \
  --reference "$DATA/inputs/multihazard_aligned/earthquake_cascadia_m9_scenario/event_1.tif" \
  --output "$DATA/inputs/multihazard_aligned/landslide_susceptibility_cascadia/event_1.tif"

# 6. Compute the co-seismic Newmark PGD (mm) -- same HAZUS method/params as
#    Mineral's (501), M=9.0 and --susceptibility-max-count=81 (n10's own
#    9x9 10m-subcell-per-90m-cell convention).
python "$REPO/scripts/compute_landslide_pgd.py" \
  --susceptibility "$DATA/inputs/multihazard_aligned/landslide_susceptibility_cascadia/event_1.tif" \
  --pga "$DATA/inputs/multihazard_aligned/earthquake_cascadia_m9_scenario/event_1.tif" \
  --output "$DATA/inputs/multihazard_aligned/landslide_cascadia_m9/event_1.tif" \
  --magnitude 9.0 --susceptibility-max-count 81

echo "Prep complete. Verify all 4 aligned outputs exist before submitting"
echo "submit_cascadia_404.slurm / submit_cascadia_landslide_502.slurm:"
echo "  ls -la $DATA/inputs/multihazard_aligned/earthquake_cascadia_m9_scenario/"
echo "  ls -la $DATA/inputs/multihazard_aligned/earthquake_cascadia_m9_scenario_sa1p0/"
echo "  ls -la $DATA/inputs/multihazard_aligned/landslide_cascadia_m9/"
