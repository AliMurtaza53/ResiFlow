#!/usr/bin/env bash
# The HPMS->FAF5 LRS-transfer pilot's outputs were explicitly never
# committed (docs/HPMS_FAF_LRS_TRANSFER.md says so) and exist only on this
# one machine. This just gets them off a single point of failure -- it
# does NOT commit them to the main repo (they're large/local-only by the
# branch's own design). Copies to a dated folder under parameters/ staging
# so they ride along with whatever backup/sync already covers this repo
# tree, without bloating git history with large CSV/GeoJSON/HTML.
set -euo pipefail
cd "$(dirname "$0")/../.."

# Works from Git Bash (/c/...), WSL (/mnt/c/...), or native Windows paths.
SRC=""
for candidate in \
  "/mnt/c/Users/akothaw/Desktop/data/faf5_data/network_data/hpms_transfer" \
  "/c/Users/akothaw/Desktop/data/faf5_data/network_data/hpms_transfer" \
  "C:\Users\akothaw\Desktop\data\faf5_data\network_data\hpms_transfer"
do
  if [ -d "$candidate" ]; then
    SRC="$candidate"
    break
  fi
done
DEST="parameters/tables/_backup_hpms_lrs_transfer_$(date +%Y%m%d)"

if [ -z "$SRC" ] || [ ! -d "$SRC" ]; then
  echo "Source not found at $SRC -- nothing to back up (already moved/lost?)."
  exit 1
fi

mkdir -p "$DEST"
cp -v "$SRC"/* "$DEST"/
echo "Copied to $DEST (still untracked by git -- add a .gitignore entry if you don't want it committed, or 'git add' it if you do)."
