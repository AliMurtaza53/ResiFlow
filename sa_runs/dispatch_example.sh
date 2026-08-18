#!/usr/bin/env bash
# Minimal Morris-run dispatcher: one pipeline run per manifest row, injected
# via RESIFLOW_PARAM_OVERRIDES, rerunning only the stages the changed factor
# touches (stage partition comes from manifest.csv's min_stage column).
#
# Generate the design first:
#   python scripts/6_morris_screening.py generate --trajectories 40 --optimal-trajectories 10
#
# Then dispatch (adapt PYTHON/stage commands to your cluster):
set -euo pipefail

PYTHON=${PYTHON:-python}
SA_DIR=${SA_DIR:-sa_runs}

# Determinism preconditions: truncation env vars MUST be unset for production
# SA runs (they cut the assignment short and contaminate elementary effects).
for var in RESIFLOW_MAX_FLOW_ITERATIONS RESIFLOW_SAMPLE_OD_N; do
  if [ -n "${!var:-}" ]; then
    echo "ERROR: $var is set; unset it for production SA runs." >&2
    exit 1
  fi
done

# manifest.csv columns: run_id,trajectory,changed_factor,changed_group,min_stage,<factor values...>
tail -n +2 "$SA_DIR/manifest.csv" | while IFS=, read -r run_id trajectory changed_factor changed_group min_stage _rest; do
  overrides="$SA_DIR/$run_id/overrides.json"
  echo "=== $run_id (changed=$changed_group, min_stage=$min_stage) ==="
  export RESIFLOW_PARAM_OVERRIDES="$overrides"

  # Stage partition: rerun only min_stage and downstream, reusing cached
  # upstream outputs. P < 1 < 2 < 3 < 4.
  case "$min_stage" in
    P)
      $PYTHON scripts/convert_faf5_network.py                     # network rebuild
      ;&                                    # fall through to every later stage
    1)
      $PYTHON scripts/1_network_flow_model_revision.py
      ;&
    2)
      $PYTHON scripts/2_intersection_analysis.py
      ;&
    3)
      $PYTHON scripts/3_damage_analysis.py
      ;&
    4)
      $PYTHON scripts/4_rerouting_and_recovery_scenario_loop.py 30 1 10 4
      ;;
  esac

  unset RESIFLOW_PARAM_OVERRIDES
  # Collect the four output components for this run into results.csv
  # (run_id,direct_damage,rerouting_freight,rerouting_passenger,isolation);
  # see scripts/visualizations/viz_data_loaders.build_multihazard_summary_table
  # for where each component lives on disk.
done

echo "All runs dispatched. Analyze with:"
echo "  $PYTHON scripts/6_morris_screening.py analyze --out-dir $SA_DIR"
