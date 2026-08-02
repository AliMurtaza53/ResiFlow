#!/bin/bash
#SBATCH --job-name=va_multihazard_run
#SBATCH --partition=normal
# Runs the (Pass-B-free) multi-hazard orchestrator: Script 2 (disruption,
# full CONUS road network x VA-sized raster) -> Script 3 + 3_postprocess
# (direct damage) -> Script 4 (rerouting cost, reads Pass A's own odpfc.pq
# via a DuckDB-filtered scan) for each of the 4 real hazard events. NOT
# login-node-safe -- Script 2 loads/intersects the full 483K-edge CONUS
# network, and Script 4 scans a ~386GB baseline odpfc file; both got
# SIGKILL'd on hopper1's login node (2026-07-30) with no Python traceback,
# the classic OOM-on-shared-node signature already documented in
# docs/ORC_HOPPER_SETUP.md.
#
# --mem=160G / NIRD_DUCKDB_MEMORY_LIMIT=130GB (30GB headroom): raised from
# 128G/100GB after a real OOM on the earthquake event (401, 95 damaged
# edges) -- the index-lookup query's SELECT DISTINCT od_id dedup scales with
# how many OD pairs match, and 95 edges matches far more paths than a
# single-edge flood closure does, so it needs a bigger hash structure than
# the 28GB of prior headroom allowed. Confirmed via `scontrol show node` +
# `sinfo` (2026-08-02) that normal-partition nodes have 180GB physical RAM
# (RealMemory=180000MB), not 128GB -- the original 128G/100GB pairing was an
# arbitrary carry-over from Pass A's config, not a real ceiling for this
# node type; there was real headroom being left unused.
#
# --time=06:00:00: a 3h budget was hit mid-query (not OOM, not crashed --
# load_odpfc_source's original correlated EXISTS(SELECT...FROM UNNEST...)
# query just didn't finish in time against the real ~386GB odpfc.pq).
# Rewritten to a CROSS JOIN UNNEST + JOIN (a vectorizable semi-join DuckDB
# can actually parallelize, same primitive load_path_index_disrupted_
# candidates already used) -- should be much faster, but doubling the
# budget here as a margin since this exact query hasn't been timed yet at
# real CONUS scale.
#SBATCH --time=06:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=160G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_run_multihazard_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_run_multihazard_%j.err
# hop059 excluded: two consecutive jobs (9224623, 9224625, 2026-08-02) both
# failed there in <40s with a broken site module tree (Lmod errors on
# hosts/hopper and ohpc modulefiles -- nothing this script references),
# before Python ever started. Confirmed via `sacct --format=NodeList` that
# both ran on hop059. Node-local issue, not this job's environment/code.
#SBATCH --exclude=hop059

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
# Overrides the orchestrator's own 100GB default (base_env.setdefault(...)
# only applies when unset) -- see the --mem comment above for why.
export NIRD_DUCKDB_MEMORY_LIMIT=130GB

python /scratch/akothaw/multimodal_hazard_data/code/ResiFlow/scripts/run_conus_va_multihazard.py \
  --hazards-manifest ~/multimodal_hazard_project/hazards.json \
  --results-variant convergence_cpu8_bounded18 \
  --num-chunks 20 --num-cpu $SLURM_CPUS_PER_TASK
