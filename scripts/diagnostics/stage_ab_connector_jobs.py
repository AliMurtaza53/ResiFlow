"""Write, but do not submit, the preregistered six primary pilot jobs.

Run on Hopper after inspecting the preparation outputs. Each job checks coverage
again. Slurm dependencies are supplied at submission and saved in the manifest.
"""
from pathlib import Path
import argparse,json

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True)
    p.add_argument('--code',type=Path,required=True);p.add_argument('--revision',required=True)
    a=p.parse_args();r=a.root;ops=r/'stage2_scripts/ab_connector_pilot_20261118'
    manifest=[]
    for case,arm in [('freight','B'),('combined','A'),('combined','B')]:
        v=f'ab_connector_{case}_{arm}_20261118';d=ops/v;d.mkdir(exist_ok=True)
        network='A' if arm=='A' else 'B4';cap=15 if case=='freight' else 40
        common=f'''set -eo pipefail
DATA={r}
CODE={a.code}
OPS={ops}
INPUT=$OPS/inputs
VARIANT={v}
RUN=$OPS/$VARIANT
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird
unset RESIFLOW_VEHICLE_CLASS NIRD_VEHICLE_CLASS NIRD_LEGACY_FREEFLOW_BASELINE RESIFLOW_SAMPLE_OD_N NIRD_SAMPLE_OD_N
export RESIFLOW_INVARIANT_REL_TOL=1e-9 RESIFLOW_INVARIANT_RAISE=1
export RESIFLOW_EXCLUDE_INTRAZONAL_OD=1 NIRD_EXCLUDE_INTRAZONAL_OD=1
export PYTHONPATH=$CODE/src:$DATA/pytest_pkgs
export PROJ_DATA=/scratch/akothaw/conda_envs/nird/lib/python3.10/site-packages/rasterio/proj_data PROJ_LIB=/scratch/akothaw/conda_envs/nird/lib/python3.10/site-packages/rasterio/proj_data
export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$RESIFLOW_CONFIG_PATH
export RESIFLOW_DEMAND_CASE={case} NIRD_DEMAND_CASE={case}
export RESIFLOW_DISABLE_PASSENGER_OD={int(case=='freight')} NIRD_DISABLE_PASSENGER_OD={int(case=='freight')}
export RESIFLOW_PASSENGER_OD_PATH=$INPUT/passenger_fixed_od.pq NIRD_PASSENGER_OD_PATH=$INPUT/passenger_fixed_od.pq
export RESIFLOW_FAF5_OD_MATRIX_PATH=$DATA/stage2_scripts/connector_test2_gateway_full/conus/harvey15_gateway_od.pq
export NIRD_FAF5_OD_MATRIX_PATH=$RESIFLOW_FAF5_OD_MATRIX_PATH
export RESIFLOW_FAF5_CONNECTOR_NETWORK=$INPUT/network_{network}.gpq
export RESIFLOW_RESULTS_VARIANT=$VARIANT NIRD_RESULTS_VARIANT=$VARIANT
export RESIFLOW_PARAM_OVERRIDES=$CODE/experiments/conus_multihazard/hopper/overrides/sourced_asset_costs.json
export NIRD_PARAM_OVERRIDES=$RESIFLOW_PARAM_OVERRIDES
export RESIFLOW_MAX_FLOW_ITERATIONS={cap} NIRD_MAX_FLOW_ITERATIONS={cap}
export RESIFLOW_GIT_COMMIT={a.revision}
export NIRD_LCP_DEST_CHUNK_SIZE=1000 NIRD_FLOW_DB_BATCH_SIZE=50000 NIRD_LCP_SORT_BY_DEST_COUNT=1
export NIRD_DUCKDB_MEMORY_LIMIT=450GB NIRD_LOG_RSS_CHECKPOINTS=1
export NIRD_POOL_MAX_TASKS_PER_CHILD=50 NIRD_LCP_COLLECT_POOL_RESULTS=0
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export RESIFLOW_AUDIT_DUMP_LEVEL=binding RESIFLOW_LOG_CAPACITY_BLOCKED_EDGES=1
export RESIFLOW_HAZARD_TYPE=flood RESIFLOW_FLOOD_SUBTYPE=flood_harvey_houston RESIFLOW_SCENARIO_PARAM=304
python -c "import json; assert json.load(open('$INPUT/preflight.json'))['coverage_pass']"
cd "$CODE"
source "$CODE/experiments/common/profile_stage.sh"
profile_init "$VARIANT"
VERIFY=$OPS/tools/verify_ab_connector_pilot.py
AUDIT=$CODE/scripts/diagnostics/audit_faf_centroid_shortcuts.py
MAPPING=$INPUT/connectors_{network}.csv
'''
        baseline='''export NIRD_BASELINE_DB_PATH=$RUN/baseline.duckdb
export NIRD_DUCKDB_TEMP_DIRECTORY=$RUN/tmp_baseline
export NIRD_BASE_SCENARIO_OUT_DIR=$DATA/results/$VARIANT
export RESIFLOW_AUDIT_DUMP_DIR=$DATA/audit_dumps/${VARIANT}_baseline
export NIRD_PATH_REALIZATION_STRATEGY=streaming_arrays NIRD_OD_ID_AT_INSERT=1
export NIRD_BASELINE_PATH_OUTPUT_MODE=full_odpfc NIRD_ODPFC_OUTPUT_MODE=iteration_parquet NIRD_COMBINE_ODPFC_PARTS=0
mkdir -p "$NIRD_DUCKDB_TEMP_DIRECTORY"
test ! -e "$NIRD_BASE_SCENARIO_OUT_DIR/edge_flows.gpq"
profile_stage stage1_baseline python "$CODE/scripts/1_network_flow_model_revision.py" 20 "$SLURM_CPUS_PER_TASK"
profile_stage baseline_gate python "$VERIFY" --root "$DATA" --inputs "$INPUT" --variant "$VARIANT" --case CASE --stage baseline
profile_stage baseline_shortcuts python "$AUDIT" "$MAPPING" "$NIRD_BASE_SCENARIO_OUT_DIR/odpfc_parts/*.pq" | tee "$RUN/baseline_shortcuts.log"
grep -q 'shortcuts=0, share=0.0' "$RUN/baseline_shortcuts.log"
profile_stage path_index python "$CODE/scripts/build_odpfc_edge_index.py" --odpfc "$NIRD_BASE_SCENARIO_OUT_DIR/odpfc_parts" --output "$NIRD_BASE_SCENARIO_OUT_DIR/odpfc_edge_index" --memory-limit 250GB --threads "$SLURM_CPUS_PER_TASK" --temp-directory "$NIRD_DUCKDB_TEMP_DIRECTORY"
profile_finish
'''.replace('CASE',case)
        recovery='''export NIRD_RECOVERY_DB_PATH=$RUN/recovery.duckdb
export NIRD_DUCKDB_TEMP_DIRECTORY=$RUN/tmp_recovery
export RESIFLOW_AUDIT_DUMP_DIR=$DATA/audit_dumps/${VARIANT}_recovery
export NIRD_PATH_REALIZATION_STRATEGY=duckdb_chunked_compact
export RESIFLOW_STAGE4_EXPORT_OD_PATHS=1
mkdir -p "$NIRD_DUCKDB_TEMP_DIRECTORY" "$DATA/results/base_scenario"
test -s "$RUN/baseline_verified.json"
test ! -e "$DATA/results/base_scenario/$VARIANT"
ln -s "$DATA/results/$VARIANT" "$DATA/results/base_scenario/$VARIANT"
profile_stage stage2_intersection python "$CODE/scripts/2_intersection_analysis.py" 304 1
profile_stage hazard_gate python "$VERIFY" --root "$DATA" --inputs "$INPUT" --variant "$VARIANT" --case CASE --stage hazard
profile_stage stage3_damage python "$CODE/scripts/3_damage_analysis.py"
profile_stage stage3_postprocess python "$CODE/scripts/3_postprocess_damage.py"
profile_stage damage_gate python "$VERIFY" --root "$DATA" --inputs "$INPUT" --variant "$VARIANT" --case CASE --stage damage
profile_stage stage4_recovery python "$CODE/scripts/4_rerouting_and_recovery_scenario_loop.py" 304 1 20 "$SLURM_CPUS_PER_TASK"
profile_stage completion_gate python "$VERIFY" --root "$DATA" --inputs "$INPUT" --variant "$VARIANT" --case CASE --stage completion --log "$RUN/recovery_${SLURM_JOB_ID}.err"
OUT=$DATA/results/rerouting_analysis/$VARIANT/304/1
for day in 0 7 14 30 60 90; do
  for suffix in "" _baseline; do
    test -s "$OUT/odpfc_CASE_s1_day${day}${suffix}.pq"
    python "$AUDIT" "$MAPPING" "$OUT/odpfc_CASE_s1_day${day}${suffix}.pq"
  done
done | tee "$RUN/recovery_shortcuts.log"
test "$(grep -c 'shortcuts=0, share=0.0' "$RUN/recovery_shortcuts.log")" = 12
profile_finish
'''.replace('CASE',case)
        for stage,body in [('baseline',baseline),('recovery',recovery)]:
            header=f'''#!/bin/bash
#SBATCH --job-name={v}_{stage}
#SBATCH --partition=bigmem
#SBATCH --cpus-per-task=8
#SBATCH --mem=600G
#SBATCH --time=06:00:00
#SBATCH --output={d}/{stage}_%j.out
#SBATCH --error={d}/{stage}_%j.err
'''
            (d/f'{stage}.slurm').write_text(header+common+body)
        manifest.append(dict(variant=v,case=case,arm=arm,baseline_script=str(d/'baseline.slurm'),recovery_script=str(d/'recovery.slurm'),source_revision=a.revision,status='staged_not_submitted'))
    path=ops/'primary_manifest.json'
    if path.exists():raise FileExistsError(path)
    path.write_text(json.dumps(manifest,indent=2))
    print(path)
if __name__=='__main__':main()
