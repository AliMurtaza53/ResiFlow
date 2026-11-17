"""Submit validated full gateway baselines and dependent Harvey recovery jobs."""
import argparse
import json
from pathlib import Path
import subprocess

DATA = Path("/scratch/akothaw/multimodal_hazard_data")
OPS = DATA / "stage2_scripts/connector_test2_gateway_full"
REF = DATA / "stage2_scripts/connector_endpoint_runs"
CS = DATA / "stage2_scripts/connector_test2_cs"
CONUS = DATA / "stage2_scripts/connector_test2_conus"
PREVIOUS = "harvey15_connector_endpoint_native"
OLD_CODE = DATA / "code/ResiFlow_connector_endpoint"
OLD_OD = DATA / "stage2_scripts/connector_test1_inputs/faf5_od_matrix_subset.pq"
TRIPS = {"harvey15": 754974.3022249371, "conus": 1510749.5566692087}


def replace_required(script, before, after):
    if before not in script:
        raise ValueError(f"Template does not contain {before!r}")
    return script.replace(before, after)


def submit(path, dependency=None):
    subprocess.run(["bash", "-n", path], check=True)
    command = ["sbatch", "--parsable"]
    if dependency:
        command += [f"--dependency=afterok:{dependency}", "--kill-on-invalid-dep=yes"]
    return subprocess.check_output([*command, path], text=True).split(";")[0].strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("code", type=Path)
    parser.add_argument("commit")
    args = parser.parse_args()
    commit = subprocess.check_output(["git", "-C", args.code, "rev-parse", "--short", "HEAD"],
                                     text=True).strip()
    if commit != args.commit or subprocess.check_output(["git", "-C", args.code, "status", "--porcelain"]):
        raise ValueError("Run checkout must be clean and pinned to the requested commit")
    templates = {(REF / "baseline_native.slurm"): "cte_native",
                 (REF / "recovery.slurm"): "cte_native_recovery"}
    control = {"harvey15": CS / "harvey15_cs_assignment_parent_mean.pq",
               "conus": CONUS / "inputs/mean.pq"}
    workloads = []
    manifest = OPS / "full_jobs.tsv"
    if manifest.exists():
        raise FileExistsError(manifest)
    for scope, trips in TRIPS.items():
        preflight = json.loads((OPS / scope / "preflight.json").read_text())
        if abs(preflight["trips_day"] / trips - 1) > 1e-9:
            raise ValueError(f"{scope} failed demand gate")
        if not .98 <= preflight["pilot_haul_mi"] / preflight["baseline_haul_mi"] <= 1.02:
            raise ValueError(f"{scope} failed haul gate")
        for arm in ("control", "gateway"):
            variant = f"{scope}_connector_test2g_{arm}"
            od = control[scope] if arm == "control" else OPS / scope / "harvey15_gateway_od.pq"
            if not od.is_file() or (DATA / "results" / variant).exists():
                raise ValueError(f"Missing OD or occupied outputs for {variant}")
            run = OPS / variant
            run.mkdir()
            for template, name in templates.items():
                script = template.read_text()
                script = replace_required(script, str(OLD_CODE), str(args.code))
                script = replace_required(script, PREVIOUS, variant)
                script = replace_required(script, name, f"{variant}_{template.stem}")
                if template.name == "baseline_native.slurm":
                    script = replace_required(script, str(OLD_OD), str(od))
                    script = replace_required(script, "682cf95", commit)
                    if "set -eo pipefail" not in script:
                        script = replace_required(script, "set -e", "set -eo pipefail")
                    suffix = f"""
profile_stage audit_paths python "$CODE/scripts/diagnostics/audit_faf_centroid_shortcuts.py" \
  "{DATA}/stage2_scripts/connector_test1_inputs/connector_crosswalk.csv" \
  "$NIRD_BASE_SCENARIO_OUT_DIR/odpfc_parts/*.pq" | tee "{run}/shortcut_audit.log"
grep -q "shortcuts=0, share=0.0" "{run}/shortcut_audit.log"
"""
                    if arm == "gateway":
                        suffix += f"""
profile_stage verify_gateway python "{OPS}/verify_faf_gateway_pilot.py" \
  "$RESIFLOW_AUDIT_DUMP_DIR/iteration_summary.parquet" "$NIRD_BASE_SCENARIO_OUT_DIR/edge_flows.gpq" \
  "{DATA}/results/{scope}_connector_test2g_control/edge_flows.gpq" \
  "{OPS}/{scope}/gateway_budgets.csv" "{run}/access_roads.csv" --expected-trips {trips}
"""
                    script = replace_required(script, "\nprofile_finish", suffix + "\nprofile_finish")
                    if scope == "conus":
                        script = replace_required(script, "#SBATCH --partition=normal", "#SBATCH --partition=bigmem")
                        script = replace_required(script, "#SBATCH --mem=150G", "#SBATCH --mem=600G")
                        script = replace_required(script, "MEMORY_LIMIT=100GB", "MEMORY_LIMIT=450GB")
                else:
                    script = replace_required(script, "$INPUT/faf5_od_matrix_subset.pq", str(od))
                    script = replace_required(script, str(REF), str(run))
                    if scope == "conus":
                        script = replace_required(script, "#SBATCH --mem=400G", "#SBATCH --mem=600G")
                        script = replace_required(script, "MEMORY_LIMIT=300GB", "MEMORY_LIMIT=450GB")
                path = run / template.name
                path.write_text(script)
                subprocess.run(["bash", "-n", path], check=True)
            workloads.append((scope, arm, run))
    jobs = {}
    with manifest.open("x") as file:
        for scope, arm, run in workloads:
            dependency = jobs.get((scope, "control")) if arm == "gateway" else None
            base = submit(run / "baseline_native.slurm", dependency)
            jobs[(scope, arm)] = base
            entry = f"{scope}\t{arm}\tbaseline\t{base}"
            print(entry, flush=True)
            print(entry, file=file, flush=True)
            recovery = submit(run / "recovery.slurm", base)
            entry = f"{scope}\t{arm}\trecovery\t{recovery}"
            print(entry, flush=True)
            print(entry, file=file, flush=True)


if __name__ == "__main__":
    main()
