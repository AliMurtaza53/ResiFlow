#!/bin/bash
#SBATCH --job-name=anvil_scale_cpu128
#SBATCH --account=civ260045
#SBATCH --partition=shared
# CPU-scaling benchmark (Pass A / Script 1), Anvil counterpart to Hopper's
# experiments/pass_a_convergence/hopper/submit_cpu16.slurm -- same
# methodology (1 flow-assignment iteration, num_of_chunk=20 held constant
# across CPU counts) so the two clusters' timings are directly comparable.
# Anvil nodes are single-socket 128-core AMD EPYC (2 sockets x 64 cores,
# see `sinfo -N -l`), 257400MB RAM -- a materially different CPU
# architecture from Hopper's nodes, which is the whole point of this
# benchmark: get a real hardware-vs-hardware data point, not just a
# core-count one, comparable to NIRD's published "8h baseline @ 50 CPUs"
# spec (no hardware details given in their docs -- see docs/PROJECT_LOG.md
# for the review that flagged this gap).
#
# streaming_arrays (not duckdb_chunked_compact, which Hopper's older
# scale-test scripts still use): confirmed this session via a real A/B test
# on Hopper (earthquake/403, Script 4) to be 22.4% faster with identical
# dollar output -- see submit_earthquake_403_strategy_streaming_arrays.slurm
# and docs/PROJECT_LOG.md. Using the corrected default here rather than
# reproducing the now-known-worse strategy just for cross-cluster parity.
#
# Base CONUS network/OD inputs (~4.2GB: faf5_road_links.gpq, the OD
# matrices under census_datasets/, parameters/) were relayed directly from
# Hopper's scratch since the 66GB solved Pass A baseline itself was not
# needed -- only the raw inputs Script 1 builds from scratch.
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=128
#SBATCH --mem=245G
#SBATCH --output=/home/x-akothawala/multimodal_hazard_project/logs_anvil_cpu128_%j.out
#SBATCH --error=/home/x-akothawala/multimodal_hazard_project/logs_anvil_cpu128_%j.err

module purge
module load anaconda/2024.02-py311
source activate /anvil/scratch/x-akothawala/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_anvil.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_anvil.json

# One iteration only -- this is a scaling comparison test, not a convergence run.
export RESIFLOW_MAX_FLOW_ITERATIONS=1
export NIRD_MAX_FLOW_ITERATIONS=1

export RESIFLOW_RESULTS_VARIANT=anvil_scale_test_cpu128
export NIRD_RESULTS_VARIANT=anvil_scale_test_cpu128
export NIRD_BASELINE_DB_PATH=/anvil/scratch/x-akothawala/multimodal_hazard_data/anvil_scale_test_cpu128.duckdb

export NIRD_LCP_DEST_CHUNK_SIZE=1000
export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_DUCKDB_MEMORY_LIMIT=190GB
export NIRD_LOG_RSS_CHECKPOINTS=1
export NIRD_LCP_SORT_BY_DEST_COUNT=1
export NIRD_PATH_REALIZATION_STRATEGY=streaming_arrays
export NIRD_DUCKDB_TEMP_DIRECTORY=/anvil/scratch/x-akothawala/multimodal_hazard_data/duckdb_tmp_cpu128
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

REPO=/anvil/scratch/x-akothawala/multimodal_hazard_data/code/ResiFlow
python $REPO/scripts/1_network_flow_model_revision.py 20 $SLURM_CPUS_PER_TASK
