#!/bin/bash
#SBATCH --job-name=build_bridge_index
#SBATCH --partition=normal
# Loads the National Bridge Inventory from the official NTAD file
# geodatabase (see scripts/load_ntad_bridge_gdb.py's docstring for why this
# is preferred over scripts/download_nbi_bridges.py's per-state scraping --
# already-decoded coordinates, more current, single versioned/citable
# source) and spatially joins it onto the real CONUS FAF5 network, fixing
# the bug where road_bridge defaults to 'no' for every link (see
# scripts/build_nbi_bridge_index.py's docstring for the full diagnosis and
# DAFNI-NIRD comparison).
#
# REPLACES an earlier build (job 9399933, 2026-08-17): that run predates
# the deck_width_m=0 fix (0 is NBI's "not recorded" convention, not a real
# zero-width bridge -- 14.3% of structures carry it; left unfixed, it
# silently zeroed out those links' entire bridge damage cost instead of
# falling back to the lanes-based estimate). If you already swapped that
# build's output in, THIS RE-PATCHES AGAINST THE BACKUP
# (faf5_road_links.gpq.pre_bridge_fix_backup), not the currently-live file
# -- patching against the already-patched file would leave the previously-
# zeroed links stuck at 0 forever (their original lanes-based averageWidth
# was already overwritten and can't be recovered from the live file alone).
#
# PRE-FLIGHT: transfer the GDB zip from your local Downloads to Hopper
# first (this job does not download it) --
#   scp "NTAD_National_Bridge_Inventory_*.zip" \
#     akothaw@hopper.orc.gmu.edu:/scratch/akothaw/multimodal_hazard_data/inputs_raw/
#
# --mem=64G: NBI is small (~625K structures, tens of MB as parquet); the
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
NTAD_ZIP=$(ls $DATA/inputs_raw/NTAD_National_Bridge_Inventory_*.zip 2>/dev/null | head -1)
NTAD_EXTRACT_DIR=$DATA/inputs_raw/ntad_nbi_extracted
NBI_OUT=$DATA/inputs_raw/nbi_bridges_ntad.parquet
FAF5_LINKS_BASE=$DATA/soge_clusters/networks/faf5/faf5_road_links.gpq
# Patch against the pristine backup, not the currently-live file -- see the
# header comment above for why this matters if a prior (pre-deck-width-fix)
# build was already swapped in.
FAF5_LINKS_SOURCE=$FAF5_LINKS_BASE.pre_bridge_fix_backup
if [ ! -f "$FAF5_LINKS_SOURCE" ]; then
  echo "No pre_bridge_fix_backup found -- assuming this is the first build, patching against the live file."
  FAF5_LINKS_SOURCE=$FAF5_LINKS_BASE
fi
BRIDGE_INDEX_OUT=$DATA/soge_clusters/networks/faf5/faf5_bridge_index.parquet

if [ ! -f "$FAF5_LINKS_SOURCE" ]; then
  echo "ERROR: FAF5 road links not found at $FAF5_LINKS_SOURCE -- check the path before continuing." >&2
  exit 1
fi

if [ ! -f "$NBI_OUT" ]; then
  if [ -z "$NTAD_ZIP" ]; then
    echo "ERROR: no NTAD_National_Bridge_Inventory_*.zip found under $DATA/inputs_raw/ -- transfer it from your Downloads first (see header comment)." >&2
    exit 1
  fi
  echo "Extracting $NTAD_ZIP..."
  mkdir -p "$NTAD_EXTRACT_DIR"
  unzip -o -q "$NTAD_ZIP" -d "$NTAD_EXTRACT_DIR"
  GDB_DIR=$(find "$NTAD_EXTRACT_DIR" -maxdepth 1 -name "*.gdb" | head -1)
  echo "Loading NBI from $GDB_DIR..."
  python "$REPO/scripts/load_ntad_bridge_gdb.py" --gdb "$GDB_DIR" --output "$NBI_OUT"
else
  echo "NBI already loaded at $NBI_OUT, skipping."
fi

python "$REPO/scripts/build_nbi_bridge_index.py" \
  --nbi "$NBI_OUT" \
  --road-links "$FAF5_LINKS_SOURCE" \
  --output "$BRIDGE_INDEX_OUT" \
  --max-distance 100

PATCHED_LINKS=$DATA/soge_clusters/networks/faf5/faf5_road_links_bridge_patched.gpq
python "$REPO/scripts/patch_faf5_bridge_attributes.py" \
  --road-links "$FAF5_LINKS_SOURCE" \
  --bridge-index "$BRIDGE_INDEX_OUT" \
  --output "$PATCHED_LINKS"

echo ""
echo "Bridge index built and faf5_road_links patched (written to a NEW path,"
echo "not swapped in automatically). Follow the verify-then-swap instructions"
echo "the patch step just printed above -- this correctly replaces whatever"
echo "is currently live, including a prior pre-deck-width-fix build, since"
echo "the patch source above was the pristine backup, not the live file."
echo "Independent of the Pass A/conus_nandu_v1 timeline either way (confirmed"
echo "via grep that road_revised.py never references road_bridge/averageWidth)."
