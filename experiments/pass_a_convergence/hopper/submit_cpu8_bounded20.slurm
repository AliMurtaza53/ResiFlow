#!/bin/bash
#SBATCH --job-name=hazard_convergence_cpu8_bounded20
#SBATCH --partition=normal
# Modest step up from the working convergence_cpu8_bounded18 baseline --
# RESIFLOW_MAX_FLOW_ITERATIONS=20 instead of 18. NOT the eventual unbounded
# convergence run (that's planned for Anvil once credit exchange clears) --
# this is a smaller, well-understood follow-up test, using the SAME proven
# config as submit_cpu8_bounded18.slurm with only the things that need to
# change actually changed. Confirmed by reading that script: the "18" that
# bounds iterations comes from RESIFLOW_MAX_FLOW_ITERATIONS/
# NIRD_MAX_FLOW_ITERATIONS env vars -- the "20" in that script's final
# command line is an UNRELATED num_chunks argument that happened to
# coincidentally also be 20; left unchanged here since there's no reason to
# touch it.
#
# Deliberately a NEW, separate results_variant (convergence_cpu8_bounded20),
# not a replacement of convergence_cpu8_bounded18 -- the current 4-hazard
# advisor-review comparison is being built from bounded18 right now and
# stays untouched and available throughout this run. Also uses its own
# NIRD_BASELINE_DB_PATH and NIRD_DUCKDB_TEMP_DIRECTORY (distinct from
# bounded18's) to avoid any stale-state collision between the two runs.
#
# Time budget: bounded18 used 30h for 18 iterations (83.5 min/iter estimate
# x 18 + headroom). Scaling proportionally for 20 iterations (~33.3h) and
# rounding up for margin. remain_od shrinks each iteration in practice, so
# this is likely pessimistic, same as the original estimate was.
#
# --mem=160G / NIRD_DUCKDB_MEMORY_LIMIT=130GB, up from bounded18's
# 128G/100GB: that pairing was set before this session confirmed (via
# `scontrol`/`sinfo`, investigating a later earthquake OOM) that Hopper's
# normal-partition nodes actually have 180GB physical RAM, not 128GB -- real
# unused headroom, same correction already applied to the per-hazard Script
# 4 jobs. Pass A's own memory profile shouldn't change materially between
# iteration 18 and 20 (continuing the same convergence trajectory), so this
# is margin, not a response to any observed problem.
#SBATCH --time=36:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=160G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_cpu8_bounded20_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_cpu8_bounded20_%j.err

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json

export RESIFLOW_MAX_FLOW_ITERATIONS=20
export NIRD_MAX_FLOW_ITERATIONS=20

# New, separate variant -- convergence_cpu8_bounded18 is untouched.
export RESIFLOW_RESULTS_VARIANT=convergence_cpu8_bounded20
export NIRD_RESULTS_VARIANT=convergence_cpu8_bounded20
export NIRD_BASELINE_DB_PATH=/scratch/akothaw/multimodal_hazard_data/convergence_cpu8_bounded20.duckdb

# Goal 15 validated fixes -- same as bounded18, keep regardless of core count
export NIRD_LCP_DEST_CHUNK_SIZE=1000
export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_DUCKDB_MEMORY_LIMIT=130GB
export NIRD_LOG_RSS_CHECKPOINTS=1
export NIRD_LCP_SORT_BY_DEST_COUNT=1
export NIRD_PATH_REALIZATION_STRATEGY=duckdb_chunked_compact

export NIRD_DUCKDB_TEMP_DIRECTORY=/scratch/akothaw/multimodal_hazard_data/duckdb_tmp_cpu8_bounded20
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

python /scratch/akothaw/multimodal_hazard_data/code/ResiFlow/scripts/1_network_flow_model_revision.py 20 $SLURM_CPUS_PER_TASK
