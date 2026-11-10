#!/usr/bin/env bash
# Diagnose/attempt a fix for the native access-violation crash when pandas
# writes an .xlsx via openpyxl in the `nird` conda env. Confirmed repro:
#   python -c "import pandas as pd; pd.DataFrame({'a':[1]}).to_excel('x.xlsx')"
# crashes with "Windows fatal exception: access violation" inside
# openpyxl's workbook._setup_styles -> copy.copy on this machine, with
# pandas 3.0.3 + openpyxl 3.1.5. pandas 3.0 is a very recent major version;
# this smells like an openpyxl/pandas ABI mismatch rather than a ResiFlow
# bug (every test that fails this way fails in the Excel-writing fixture
# code, never in anything this project wrote).
#
# This script tries the cheapest fix first (reinstall openpyxl clean) and
# reports whether each step clears the repro. It does NOT change pandas --
# downgrading pandas is a bigger decision (affects the whole pipeline) and
# is left for a human to decide if step 1 doesn't work.
#
# UPDATE 2026-11-10 (superseded): a reinstall cleared this script's simple
# one-row repro but not the real crash in the actual test fixtures, which
# write multiple sheets with styling this repro doesn't exercise. Rather
# than keep chasing the openpyxl/pandas incompatibility itself, the three
# call sites that wrote new .xlsx files (tests/sioux_falls_fixtures.py,
# tests/toy_pipeline_fixtures.py, scripts/testbed/run_multifactor_sensitivity_sioux_falls.py)
# were converted to write CSV instead -- see resiflow.tables's
# read_damage_ratio_table/damage_cost_sheet_names/read_damage_cost_sheet
# and scripts/3_damage_analysis.py's loader, which prefers CSV and falls
# back to legacy .xlsx. Full suite now passes clean (466 passed, 3
# skipped, 0 failed) with no crash and no exclusions needed. This script
# is kept only in case the underlying openpyxl/pandas bug matters again
# for some other reason (e.g. reading someone else's real .xlsx that
# genuinely needs re-saving).
set -euo pipefail

# Works from Git Bash (/c/...), WSL (/mnt/c/...), or native Windows paths --
# pick whichever of these actually exists on this shell.
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

repro() {
  "$PYTHON" -c "
import pandas as pd, tempfile, os
p = os.path.join(tempfile.gettempdir(), 'resiflow_openpyxl_repro.xlsx')
pd.DataFrame({'a':[1]}).to_excel(p)
print('OK: xlsx write succeeded')
" 2>&1
}

echo "=== baseline repro ==="
repro || true

echo
echo "=== step 1: clean reinstall of openpyxl ==="
"$PYTHON" -m pip uninstall -y openpyxl
"$PYTHON" -m pip install --no-cache-dir openpyxl
repro && { echo "FIXED by reinstalling openpyxl."; exit 0; } || true

echo
echo "=== step 2: try the latest openpyxl release explicitly ==="
"$PYTHON" -m pip install --no-cache-dir --upgrade openpyxl
repro && { echo "FIXED by upgrading openpyxl."; exit 0; } || true

echo
echo "Neither step fixed it. Next option (not automated here -- bigger call):"
echo "  pin pandas to <3.0 in environment.yml/pyproject.toml and recreate the env,"
echo "  since pandas 3.0 is very new and openpyxl 3.1.5 predates it."
echo "Report back to the user with these results rather than guessing further."
