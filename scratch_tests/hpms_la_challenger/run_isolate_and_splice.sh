#!/bin/bash
set -euo pipefail
ROOT=/scratch/akothaw/multimodal_hazard_data/scratch_tests/hpms_la_challenger
SRC=/scratch/akothaw/multimodal_hazard_data/soge_clusters
DST=$ROOT/isolated_base
PY=/scratch/akothaw/conda_envs/nird/bin/python
export PATH="$(dirname "$PY"):$PATH"

echo "=== isolating cp -al ==="
date
rm -rf "$DST"
cp -al "$SRC" "$DST"
echo "=== break hardlinks on network files ==="
ls -la "$DST/networks/faf5/faf5_road_links.gpq" "$DST/networks/faf5/faf5_road_nodes.gpq"
rm -f "$DST/networks/faf5/faf5_road_links.gpq" "$DST/networks/faf5/faf5_road_nodes.gpq"
echo "=== shared original still present ==="
ls -la "$SRC/networks/faf5/faf5_road_links.gpq" "$SRC/networks/faf5/faf5_road_nodes.gpq"
date
du -sh "$DST" || true

echo "=== splice ==="
cd "$ROOT"
"$PY" splice_hpms_la_network.py
echo "=== cheap checks ==="
"$PY" verify_hpms_la_cheap_checks.py
echo "=== DONE isolate+splice+checks ==="
date
