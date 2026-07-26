#!/bin/bash
#SBATCH --job-name=va_hazard_align
#SBATCH --partition=normal
# Lightweight rasterio reprojection/resampling work, not the CONUS assignment
# compute -- a modest allocation is plenty. Raw inputs (~2.3GB) must be
# transferred to Hopper first (scp; see docs/VA_MULTIHAZARD_COMPARISON.md).
#SBATCH --time=00:30:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_align_hazards_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_align_hazards_%j.err

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json

RAW=/scratch/akothaw/multimodal_hazard_data/va_multihazard_raw
OUT=/scratch/akothaw/multimodal_hazard_data/soge_clusters/inputs/va_multihazard_aligned
SCRIPT=/scratch/akothaw/multimodal_hazard_data/code/ResiFlow/scripts/align_hazard_rasters.py

python "$SCRIPT" \
  --input "$RAW/flood/va_dcr_depth_01pct/Depth_01pct_va141_approx100m_clean.tif" \
  --output "$OUT/flood_surface/event_1.tif" \
  --unit-scale 0.3048   # feet -> meters (VA DCR depth grid is in feet)

python "$SCRIPT" \
  --input "$RAW/earthquake/nshm2023_pga/PGA_10PctIn50Yrs_BC_va141_approx1km.tif" \
  --output "$OUT/earthquake/event_1.tif"
  # already PGA in g -- no unit conversion. Contour-rasterized workaround,
  # not the official gridded NSHM output -- see va_multihazard_raw/README.md.

python "$SCRIPT" \
  --input "$RAW/winter_storm/snodas_jan2016/SNODAS_snowdepth_m_20160123_va141.tif" \
  --output "$OUT/winter_storm/event_1.tif"
  # already snow depth in meters -- no unit conversion.

# Landslide: n10 susceptibility model output. Defaulting to bilinear
# (continuous susceptibility score); check this job's log for value_range --
# if it looks like discrete integer classes rather than a continuous score,
# rerun this one line with --nearest instead.
python "$SCRIPT" \
  --input "$RAW/landslide/n10_susc/n10_conus.tif" \
  --output "$OUT/landslide/event_1.tif"

echo "Alignment complete. Aligned rasters under: $OUT"
