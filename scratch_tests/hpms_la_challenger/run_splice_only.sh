#!/bin/bash
set -euo pipefail
ROOT=/scratch/akothaw/multimodal_hazard_data/scratch_tests/hpms_la_challenger
DST=$ROOT/isolated_base
PY=/scratch/akothaw/conda_envs/nird/bin/python

# Ensure target gpqs are absent (hardlink safety) before rewrite
rm -f "$DST/networks/faf5/faf5_road_links.gpq" "$DST/networks/faf5/faf5_road_nodes.gpq"
ls "$DST/networks/faf5/" | head
echo "=== splice ==="
date
cd "$ROOT"
"$PY" splice_hpms_la_network.py
echo "=== cheap checks ==="
"$PY" verify_hpms_la_cheap_checks.py
echo "=== DONE ==="
date
