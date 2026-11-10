#!/usr/bin/env bash
# Run the real test suite against the real environment, working around a
# known Windows-local issue: writing an .xlsx via openpyxl/pandas in this
# conda env (pandas 3.0.3 + openpyxl 3.1.5) crashes the Python process with
# a native access violation (not a Python exception -- pytest can't catch
# or report it, it just kills the run). This is an environment problem, not
# a code bug introduced by any recent change. See TASKS below for the fix.
#
# Usage: bash scripts/cleanup/run_full_test_suite.sh
set -euo pipefail
cd "$(dirname "$0")/../.."

PYTHON="C:\Users\akothaw\AppData\Local\miniforge3\envs\nird\python.exe"

# These test files call fixtures that write .xlsx workbooks and will crash
# the whole pytest process on this machine until the openpyxl/pandas
# incompatibility (see TASKS.md / AGENTS.md) is fixed. Excluded here so the
# rest of the suite can actually finish and report real pass/fail.
XLSX_CRASHING_TESTS=(
  tests/test_phase0_summary_parity.py
  tests/test_disruption_flood_parity.py
  tests/test_hazards.py
  tests/test_sioux_falls_pipeline_disruptions.py
  tests/test_snow_pipeline_sioux_falls.py
  tests/test_toy_pipeline_disruptions.py
)

IGNORE_ARGS=()
for f in "${XLSX_CRASHING_TESTS[@]}"; do
  IGNORE_ARGS+=(--ignore="$f")
done

echo "Running full suite minus ${#XLSX_CRASHING_TESTS[@]} xlsx-writing test files (native crash workaround)..."
"$PYTHON" -m pytest tests/ -q --no-header "${IGNORE_ARGS[@]}" -rfE

echo
echo "NOT run above (crash on this machine until openpyxl/pandas fixed):"
printf '  %s\n' "${XLSX_CRASHING_TESTS[@]}"
echo "Run scripts/cleanup/try_fix_openpyxl_crash.sh to attempt a fix, then rerun one of them directly to confirm."
