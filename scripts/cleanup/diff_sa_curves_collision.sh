#!/usr/bin/env bash
# RESOLVED 2026-11-10 -- see the finding written directly below, this
# script is kept only in case someone needs to re-verify later.
#
# The two versions of src/resiflow/sa/ are NOT duplicate/parallel work --
# they are genuinely different designs:
#
#   main's version:   mix_damage_curves(curve_a, curve_b, weight_a) on raw
#                      (depth, damage) point-pair tuples. Generic, abstract.
#                      ZERO callers anywhere in the repo except its own
#                      package __init__.py re-export. Dead code.
#
#   feature/hpms-la-challenger's version: mix_damage_curves(df, theta) /
#                      scale_depth_axis(df, lam) on this project's actual
#                      damage-ratio DataFrame schema (C1..C6, intensity
#                      columns). ACTIVELY CALLED from
#                      scripts/3_damage_analysis.py (lines 938, 941) as
#                      real Morris-SA perturbation seams, and referenced
#                      from src/resiflow/fragility/flood_operational.py.
#                      Covered by 9 passing tests (test_morris_screening.py,
#                      test_sa_curves.py).
#
# Verdict: keep the feature-branch version, discard main's. When main and
# the feature branch are eventually reconciled, resolve this conflict by
# taking "theirs" (the feature branch) for all three files
# (src/resiflow/sa/__init__.py, src/resiflow/sa/curves.py,
# tests/test_sa_curves.py), not a merge of the two.
set -euo pipefail
cd "$(dirname "$0")/../.."

for path in src/resiflow/sa/__init__.py src/resiflow/sa/curves.py tests/test_sa_curves.py; do
  echo "=== callers of symbols in $path, on main ==="
  git grep -n "mix_damage_curves\|scale_depth_axis\|speed_depth" main -- '*.py' | grep -v "sa/curves.py:\|test_sa_curves.py:" || echo "  (none)"
done
