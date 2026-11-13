#!/bin/bash
# Per-stage profiling for Hopper/Anvil jobs. Standing rule: every CONUS or semi-CONUS run is profiled.
#
# In a slurm script:
#   source /path/to/code/experiments/common/profile_stage.sh
#   profile_init <run_name>                 # creates $PROFILE_DIR, writes the job header
#   profile_stage <label> <command ...>     # runs the command, appends one row to stages.tsv, keeps the exit code
#   profile_finish                          # appends the sacct summary for this job
# Summarise afterwards: python scripts/diagnostics/summarize_hopper_profiles.py [profile_root]
#
# stages.tsv columns: label, start, end, wall_s, max_rss_gb, user_s, sys_s, cpu_pct, cpus, cpu_eff, duckdb_tmp_gb, exit
#   cpu_eff = (user+sys) / (wall x allocated cpus): 1.0 means every allocated core was busy the whole time.

PROFILE_ROOT=${PROFILE_ROOT:-$HOME/multimodal_hazard_project/profiles}

profile_init() {
  local name=${1:-job}
  PROFILE_DIR=$PROFILE_ROOT/${name}_${SLURM_JOB_ID:-local}
  mkdir -p "$PROFILE_DIR"
  {
    echo "name=$name"
    echo "job_id=${SLURM_JOB_ID:-none}"
    echo "node=$(hostname)"
    echo "cpus=${SLURM_CPUS_PER_TASK:-1}"
    echo "mem_request=${SLURM_MEM_PER_NODE:-unknown}"
    echo "started=$(date -Is)"
    echo "git_commit=$(git -C "${CODE:-.}" rev-parse --short HEAD 2>/dev/null)"
    echo "env_overrides=${RESIFLOW_PARAM_OVERRIDES:-}"
    echo "strategy=${NIRD_PATH_REALIZATION_STRATEGY:-}"
  } > "$PROFILE_DIR/header.txt"
  printf 'label\tstart\tend\twall_s\tmax_rss_gb\tuser_s\tsys_s\tcpu_pct\tcpus\tcpu_eff\tduckdb_tmp_gb\texit\n' > "$PROFILE_DIR/stages.tsv"
  export PROFILE_DIR
}

profile_stage() {
  local label=$1; shift
  local tf; tf=$(mktemp)
  local t0; t0=$(date -Is)
  if [ -x /usr/bin/time ]; then
    /usr/bin/time -f "%e %M %U %S %P %x" -o "$tf" "$@"
  else  # compute nodes without GNU time (Hopper, 2026-11-13): python fallback writes the same fields
    python "$(dirname "${BASH_SOURCE[0]}")/time_wrap.py" "$tf" "$@"
  fi
  local rc=$?
  local t1; t1=$(date -Is)
  # /usr/bin/time writes its line last; a failing command may add a "Command exited" line first
  read -r wall maxrss_kb user sys cpu_pct _x < <(tail -n 1 "$tf")
  rm -f "$tf"
  local cpus=${SLURM_CPUS_PER_TASK:-1}
  local eff; eff=$(awk -v u="$user" -v s="$sys" -v w="$wall" -v c="$cpus" 'BEGIN{ if (w>0 && c>0) printf "%.2f", (u+s)/(w*c); else print "NA" }')
  local rss_gb; rss_gb=$(awk -v k="$maxrss_kb" 'BEGIN{printf "%.1f", k/1048576}')
  local tmp_gb="NA"
  if [ -n "${NIRD_DUCKDB_TEMP_DIRECTORY:-}" ] && [ -d "$NIRD_DUCKDB_TEMP_DIRECTORY" ]; then
    tmp_gb=$(du -sk "$NIRD_DUCKDB_TEMP_DIRECTORY" 2>/dev/null | awk '{printf "%.1f", $1/1048576}')
  fi
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$label" "$t0" "$t1" "$wall" "$rss_gb" "$user" "$sys" "$cpu_pct" "$cpus" "$eff" "$tmp_gb" "$rc" >> "$PROFILE_DIR/stages.tsv"
  return $rc
}

profile_finish() {
  [ -n "${PROFILE_DIR:-}" ] || return 0
  echo "finished=$(date -Is)" >> "$PROFILE_DIR/header.txt"
  sacct -j "${SLURM_JOB_ID:-0}" -P -o JobID,Elapsed,TotalCPU,AllocCPUS,ReqMem,MaxRSS,AveRSS,MaxDiskRead,MaxDiskWrite,NodeList > "$PROFILE_DIR/sacct.psv" 2>/dev/null || true
  echo "profile written to $PROFILE_DIR"
}
