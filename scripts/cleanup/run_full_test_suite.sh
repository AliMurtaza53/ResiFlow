#!/usr/bin/env bash
# RESOLVED 2026-11-10: the openpyxl/pandas native-crash issue this script
# used to work around is gone -- the two test fixtures that wrote .xlsx
# (tests/sioux_falls_fixtures.py, tests/toy_pipeline_fixtures.py) and the
# one real script that did (scripts/testbed/run_multifactor_sensitivity_sioux_falls.py)
# were all converted to write CSV instead (a directory of per-sheet CSVs
# for the multi-sheet damage_cost_road_flood table), matching every other
# parameter table in this project. scripts/3_damage_analysis.py's loader
# (now via resiflow.tables.read_damage_ratio_table /
# damage_cost_sheet_names / read_damage_cost_sheet) prefers CSV and falls
# back to legacy .xlsx for any real data not yet converted -- reading an
# existing .xlsx never crashed, only creating a new one did, so nothing
# about real production data changed.
#
# This script is now just a plain full-suite runner; kept for convenience.
#
# Usage: bash scripts/cleanup/run_full_test_suite.sh
set -euo pipefail
cd "$(dirname "$0")/../.."

for candidate in \
  "/mnt/c/Users/akothaw/AppData/Local/miniforge3/envs/nird/python.exe" \
  "/c/Users/akothaw/AppData/Local/miniforge3/envs/nird/python.exe" \
  "C:\Users\akothaw\AppData\Local\miniforge3\envs\nird\python.exe"
do
  if [ -e "$candidate" ]; then
    PYTHON="$candidate"
    break
  fi
done
if [ -z "${PYTHON:-}" ]; then
  echo "Could not find the nird env's python.exe from this shell. Edit the" >&2
  echo "candidate list at the top of this script to match your path." >&2
  exit 1
fi
echo "Using: $PYTHON"

"$PYTHON" -m pytest tests/ -q --no-header -rfE
