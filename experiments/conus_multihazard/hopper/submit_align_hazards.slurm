#!/bin/bash
#SBATCH --job-name=hazard_align
#SBATCH --partition=normal
# Lightweight rasterio reprojection/resampling work, not the CONUS assignment
# compute -- a modest allocation is plenty. Raw inputs (~2.3GB) must be
# transferred to Hopper first (scp; see docs/CONUS_MULTIHAZARD_METHODOLOGY.md).
# This mirrors the run already done locally (align_hazard_rasters.py has no
# real compute requirement) -- use this only to reproduce results on Hopper's
# filesystem, e.g. before the CONUS orchestrator run.
#SBATCH --time=00:30:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_align_hazards_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_align_hazards_%j.err

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json

RAW=/scratch/akothaw/multimodal_hazard_data/multihazard_raw
OUT=/scratch/akothaw/multimodal_hazard_data/soge_clusters/inputs/multihazard_aligned
SCRIPT_DIR=/scratch/akothaw/multimodal_hazard_data/code/ResiFlow/scripts
SCRIPT=$SCRIPT_DIR/align_hazard_rasters.py
# Common grid for the VA-extent comparison set (flood_surface/earthquake/
# winter_storm event_1, all originally scoped to the same 141-node VA bbox).
# align_hazard_rasters.py no longer has an implicit default reference grid
# (it used to silently fall back to this same raster when --reference was
# omitted, which meant this exact choice was invisible in this script) --
# --reference is now passed explicitly so the grid this comparison set
# shares is visible here rather than hidden in align_hazard_rasters.py.
REFERENCE=/scratch/akothaw/multimodal_hazard_data/inputs/test_141node_50m/va_hazard_class50_141node_base.tif

# --max-valid 195 (feet, before unit-scale): the raw "clean" tile still has a
# handful of residual pixels sitting right at the 200ft masking cutoff
# (found by inspecting neighborhoods -- isolated values surrounded by nodata
# gaps, unlike the legitimate smooth 100-115ft cluster elsewhere in the
# raster). Confirmed locally: masks exactly 16 pixels out of ~2.7M valid.
python "$SCRIPT" \
  --input "$RAW/flood/va_dcr_depth_01pct/Depth_01pct_va141_approx100m_clean.tif" \
  --output "$OUT/flood_surface/event_1.tif" \
  --reference "$REFERENCE" \
  --unit-scale 0.3048 \
  --max-valid 195

# Already PGA in g -- no unit conversion. Contour-rasterized workaround, not
# the official gridded NSHM output -- see multihazard_raw/README.md.
# Confirmed value range locally: 0 - 0.185g (plausible 10%-in-50yr for VA).
python "$SCRIPT" \
  --input "$RAW/earthquake/nshm2023_pga/PGA_10PctIn50Yrs_BC_va141_approx1km.tif" \
  --output "$OUT/earthquake/event_1.tif" \
  --reference "$REFERENCE"

python "$SCRIPT" \
  --input "$RAW/winter_storm/snodas_jan2016/SNODAS_snowdepth_m_20160123_va141.tif" \
  --output "$OUT/winter_storm/event_1.tif" \
  --reference "$REFERENCE" \
  --unit-scale 1000.0   # meters -> mm (winter_storm fragility's ice_key_mm expects mm)

# Landslide susceptibility (n10): NOT pre-classified into HAZUS's None/I-X
# categories. Its own metadata states the value is "number of susceptible
# 10-m cells within each 90-m cell after down-sampling" (0-81), a continuous
# count, not an ordinal category -- confirmed locally (full histogram, not
# just a truncated head). Use --nearest since it's still a discrete count,
# not something to blend across cell boundaries. Must share the same grid
# as earthquake/event_1.tif above ($REFERENCE) since compute_landslide_pgd.py
# combines the two pixel-for-pixel.
python "$SCRIPT" \
  --input "$RAW/landslide/n10_susc/n10_conus.tif" \
  --output "$OUT/landslide_susceptibility/event_1.tif" \
  --reference "$REFERENCE" \
  --nearest

# Derive the landslide PGD raster (mm displacement) from susceptibility + PGA
# via HAZUS's Newmark method (src/resiflow/hazards/landslide_pgd.py):
#  --susceptibility-max-count 81: equal-width-bins n10's 0-81 count into
#    None/I-X (see bin_fractional_susceptibility_to_class's docstring for why
#    this is a documented modeling choice, not a physical crosswalk).
#  --magnitude 5.8: the 2011 Mineral, VA earthquake -- the largest recorded
#    Central Virginia Seismic Zone event, used as the real historical analog
#    since the NSHM PGA raster is a hazard-curve value with no magnitude of
#    its own. Confirmed locally: output range ~0.1-107mm nonzero (21% of
#    cells), within fragility/landslide_categorical.py's 25-300/15-200mm
#    thresholds.
python "$SCRIPT_DIR/compute_landslide_pgd.py" \
  --susceptibility "$OUT/landslide_susceptibility/event_1.tif" \
  --pga "$OUT/earthquake/event_1.tif" \
  --output "$OUT/landslide/event_1.tif" \
  --susceptibility-max-count 81 \
  --magnitude 5.8

echo "Alignment + landslide PGD complete. Aligned rasters under: $OUT"
