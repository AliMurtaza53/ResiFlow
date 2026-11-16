#!/bin/bash
# Submit from a Hopper login node after staging the scripts and reference CSVs.
set -euo pipefail
DATA=/scratch/akothaw/multimodal_hazard_data
OPS=$DATA/stage2_scripts/connector_test2_conus
CODE=$DATA/code/ResiFlow_connector_endpoint
test "$(git -C "$CODE" rev-parse --short HEAD)" = 682cf95
test -z "$(git -C "$CODE" status --porcelain)"
jobs_file=${1:-$OPS/jobs.tsv}
test ! -e "$jobs_file"
PYTHON=/scratch/akothaw/conda_envs/nird/bin/python
cat > "$OPS/prep.slurm" <<'PREP'
#!/bin/bash
#SBATCH --job-name=ct2_conus_prep
#SBATCH --partition=normal
#SBATCH --time=00:30:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_ct2_conus_prep_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_ct2_conus_prep_%j.err
set -eo pipefail
DATA=/scratch/akothaw/multimodal_hazard_data
OPS=$DATA/stage2_scripts/connector_test2_conus
CODE=$DATA/code/ResiFlow_connector_endpoint
ENV=/scratch/akothaw/conda_envs/nird
export PATH="$ENV/bin:$PATH"
export PROJ_DATA=$ENV/lib/python3.10/site-packages/rasterio/proj_data
export PROJ_LIB=$PROJ_DATA
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
source "$CODE/experiments/common/profile_stage.sh"
profile_init ct2_conus_prep
profile_stage prepare "$ENV/bin/python" "$OPS/prepare_faf_conus_subcounty_od.py" \
  "$DATA/inputs_corrected/faf5_od_matrix_conterminous.pq" \
  "$CODE/parameters/crosswalks/county_node_crosswalk_conterminous.csv" \
  "$DATA/stage2_scripts/connector_test1_inputs/connector_crosswalk.csv" \
  "$DATA/soge_clusters/networks/faf5/faf5_road_nodes.gpq" "$OPS" "$OPS/inputs"
profile_finish
PREP
bash -n "$OPS/prep.slurm"

"$PYTHON" - "$OPS" "$DATA" <<'PY'
from pathlib import Path
import subprocess
import sys

ops, data = map(Path, sys.argv[1:])
template = (data / "stage2_scripts/connector_endpoint_runs/baseline_native.slurm").read_text()
for arm in ("parent_only", "zero", "mean"):
    name = "ct2_conus_" + arm
    variant = "conus_connector_test2_" + arm
    for path in (data / "results" / variant, data / "audit_dumps" / variant,
                 data / (variant + ".duckdb")):
        if path.exists():
            raise FileExistsError(path)
    script = template.replace("cte_native", name).replace("harvey15_connector_endpoint_native", variant)
    script = script.replace("#SBATCH --partition=normal", "#SBATCH --partition=bigmem")
    script = script.replace("#SBATCH --mem=150G", "#SBATCH --mem=600G")
    script = script.replace("NIRD_DUCKDB_MEMORY_LIMIT=100GB", "NIRD_DUCKDB_MEMORY_LIMIT=450GB")
    script = script.replace("MAX_FLOW_ITERATIONS=15", "MAX_FLOW_ITERATIONS=1")
    script = script.replace("set -e", "set -eo pipefail", 1)
    script = script.replace(str(data / "stage2_scripts/connector_test1_inputs/faf5_od_matrix_subset.pq"),
                            str(ops / f"inputs/{arm}.pq"))
    script = script.replace("profile_finish", f"""profile_stage verify_first_pass python "{ops}/verify_faf_conus_first_pass.py" \
  "$RESIFLOW_AUDIT_DUMP_DIR/iteration_summary.parquet" "$NIRD_BASE_SCENARIO_OUT_DIR/edge_flows.gpq" \
  "{ops}/inputs/{arm}_intended.csv"
profile_stage audit_shortcuts python "$CODE/scripts/diagnostics/audit_faf_centroid_shortcuts.py" \
  "{data}/stage2_scripts/connector_test1_inputs/connector_crosswalk.csv" \
  "$NIRD_BASE_SCENARIO_OUT_DIR/odpfc_parts/*.pq" | tee "$NIRD_BASE_SCENARIO_OUT_DIR/shortcut_audit.log"
grep -q "shortcuts=0, share=0.0" "$NIRD_BASE_SCENARIO_OUT_DIR/shortcut_audit.log"
profile_finish""")
    if f"{ops}/inputs/{arm}.pq" not in script or "NIRD_MAX_FLOW_ITERATIONS=1\n" not in script:
        raise ValueError("Unexpected template")
    path = ops / f"{arm}.slurm"
    path.write_text(script)
    subprocess.run(["bash", "-n", path], check=True)
PY

prep=$(sbatch --parsable "$OPS/prep.slurm")
printf 'prep\t%s\n' "$prep" | tee "$jobs_file"
for arm in parent_only zero mean; do
  job=$(sbatch --parsable --dependency="afterok:$prep" --kill-on-invalid-dep=yes "$OPS/$arm.slurm")
  printf '%s\t%s\n' "$arm" "$job" | tee -a "$jobs_file"
done
