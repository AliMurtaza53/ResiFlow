#!/bin/bash
#SBATCH --job-name=cascadia_landslide_prep
#SBATCH --partition=normal
# Continuation of submit_cascadia_prep_dumpcode.slurm. That run finished both Cascadia earthquake layers (PGA, SA(1.0s)) and then
# ran out of memory at 32G aligning the national susceptibility raster onto the 2.6 GB Cascadia grid. Same two commands, more memory.
#SBATCH --time=03:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=160G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_cascadia_landslide_prep_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_cascadia_landslide_prep_%j.err
#SBATCH --exclude=hop059

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird
# The Nov 2026 env rebuild mixes conda PROJ 9.6.2 (proj.db layout 1.5) with pip rasterio/pyogrio that need layout >= 1.6.
# Point PROJ at rasterio's bundled db (layout 1.6; also satisfies conda pyproj).
export PROJ_DATA=/scratch/akothaw/conda_envs/nird/lib/python3.10/site-packages/rasterio/proj_data
export PROJ_LIB=$PROJ_DATA
set -e

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json

RAW=/scratch/akothaw/multimodal_hazard_data/inputs_raw
DATA=/scratch/akothaw/multimodal_hazard_data/soge_clusters
REPO=/scratch/akothaw/multimodal_hazard_data/code/ResiFlow_dump
export PYTHONPATH=$REPO/src:$PYTHONPATH

python "$REPO/scripts/align_hazard_rasters.py" \
  --input "$RAW/landslide/n10_susc/n10_conus.tif" \
  --reference "$DATA/inputs/multihazard_aligned/earthquake_cascadia_m9_scenario/event_1.tif" \
  --output "$DATA/inputs/multihazard_aligned/landslide_susceptibility_cascadia/event_1.tif"

python "$REPO/scripts/compute_landslide_pgd.py" \
  --susceptibility "$DATA/inputs/multihazard_aligned/landslide_susceptibility_cascadia/event_1.tif" \
  --pga "$DATA/inputs/multihazard_aligned/earthquake_cascadia_m9_scenario/event_1.tif" \
  --output "$DATA/inputs/multihazard_aligned/landslide_cascadia_m9/event_1.tif" \
  --magnitude 9.0 --susceptibility-max-count 81
echo "Landslide prep complete"
