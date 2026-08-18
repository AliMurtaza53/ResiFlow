#!/bin/bash
#SBATCH --job-name=build_bridge_index
#SBATCH --partition=normal
# Downloads the full FHWA National Bridge Inventory (52 states/territories)
# and spatially joins it onto the real CONUS FAF5 network, fixing the bug
# where road_bridge defaults to 'no' for every link (see
# scripts/download_nbi_bridges.py and scripts/build_nbi_bridge_index.py
# docstrings for the full diagnosis and DAFNI-NIRD comparison).
#
# NOTE ON NETWORK ACCESS: many HPC clusters block outbound internet from
# compute nodes (login-node-only). If this job fails at the download step
# with a connection error, run just that step interactively from the login
# node instead:
#   python scripts/download_nbi_bridges.py --output $NBI_OUT
# then resubmit this job (it skips the download if $NBI_OUT already exists).
#
# --mem=64G: NBI is small (~620K structures, tens of MB as parquet); the
# spatial join is a geopandas sjoin_nearest against the real ~483K-edge FAF5
# network -- not CONUS-scale-DuckDB heavy, this is a one-time GIS join, not
# a repeated pipeline step.
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_build_bridge_index_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_build_bridge_index_%j.err

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json

REPO=/scratch/akothaw/multimodal_hazard_data/code/ResiFlow
DATA=/scratch/akothaw/multimodal_hazard_data
NBI_OUT=$DATA/inputs_raw/nbi_bridges_2024.parquet
# Under soge_clusters/, not directly under networks/ -- confirmed via a live
# `find` against Hopper's scratch (2026-08-17), not assumed.
FAF5_LINKS=$DATA/soge_clusters/networks/faf5/faf5_road_links.gpq
BRIDGE_INDEX_OUT=$DATA/soge_clusters/networks/faf5/faf5_bridge_index.parquet

if [ ! -f "$FAF5_LINKS" ]; then
  echo "ERROR: FAF5 road links not found at $FAF5_LINKS -- check the path before continuing." >&2
  exit 1
fi

if [ ! -f "$NBI_OUT" ]; then
  echo "Downloading NBI (52 states/territories)..."
  python "$REPO/scripts/download_nbi_bridges.py" --output "$NBI_OUT"
else
  echo "NBI already downloaded at $NBI_OUT, skipping download."
fi

python "$REPO/scripts/build_nbi_bridge_index.py" \
  --nbi "$NBI_OUT" \
  --road-links "$FAF5_LINKS" \
  --output "$BRIDGE_INDEX_OUT" \
  --max-distance 100

# The raw FAF5Network.gdb source used to originally build faf5_road_links.gpq
# could not be located (checked Hopper scratch and the local machine,
# 2026-08-17) -- reconversion via convert_faf5_links() isn't available, so
# patch the two affected columns (road_bridge, averageWidth) directly onto
# the existing converted file instead, via the same apply_bridge_index()
# logic. Writes to a NEW path; does not overwrite $FAF5_LINKS automatically.
PATCHED_LINKS=$DATA/soge_clusters/networks/faf5/faf5_road_links_bridge_patched.gpq
python "$REPO/scripts/patch_faf5_bridge_attributes.py" \
  --road-links "$FAF5_LINKS" \
  --bridge-index "$BRIDGE_INDEX_OUT" \
  --output "$PATCHED_LINKS"

echo ""
echo "Bridge index built and faf5_road_links patched (written to a NEW path,"
echo "not swapped in automatically). Follow the verify-then-swap instructions"
echo "the patch step just printed above before re-running Script 2-4 for any"
echo "hazard -- confirmed via grep that road_revised.py (Pass A's flow-"
echo "assignment code) never references road_bridge/averageWidth, so this is"
echo "independent of the Pass A/conus_nandu_v1 timeline and does NOT need to"
echo "happen before Pass A completes."
