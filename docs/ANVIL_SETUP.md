# Running ResiFlow on Purdue Anvil (ACCESS)

Companion to `docs/ORC_HOPPER_SETUP.md` -- same structure, Anvil-specific
facts. **This is a living document, same convention as the Hopper guide:**
add entries as you hit them, don't wait for a "clean" writeup. Sections
marked **[VERIFIED]** come from real completed jobs in
`experiments/conus_multihazard/anvil/*.slurm` and `docs/PROJECT_LOG.md`.
Sections marked **[TO FILL IN]** are gaps -- nobody has documented that step
yet; fill in as you go through it for real, same way the Hopper guide grew.

---

## 0. What's already confirmed working

- Account/allocation: `civ260045` (ACCESS allocation ID, used as `--account`
  on every job below).
- ACCESS username convention: `x-akothawala` (ACCESS usernames are prefixed
  `x-`, not the plain GMU NetID Hopper uses).
- Real completed jobs exist: cpu16/32/64/128 CPU-scaling benchmarks, a
  py-spy profiling run, a GC-disable A/B test -- all under
  `experiments/conus_multihazard/anvil/`. **[VERIFIED]**
- `civ260045` has run Script 1 (Pass A / network flow model) end-to-end at
  CONUS scale successfully (job 20240812, cpu16, COMPLETED, 5049.9s total).
  **[VERIFIED]**

## 1. Getting an account **[TO FILL IN]**

Anvil is provisioned through NSF ACCESS, not a GMU-specific process -- this
is a materially different account-request flow from Hopper's, and nobody
has written up the actual steps taken to get `civ260045` provisioned.
Fill in here once you've done it for a second person:
- Which ACCESS "Allocations" portal steps were used
  (allocations.access-ci.org)?
- Was this a request against an existing PI allocation (`civ260045`, add a
  user) or a fresh allocation request?
- How long did provisioning take?
- Connect via `ssh x-<username>@anvil.rcac.purdue.edu` (ACCESS usernames
  are `x-` prefixed -- confirm this is consistent for new users too).

## 2. Storage layout

| Mount | Quota | Purge policy | Use for |
|---|---|---|---|
| `/home/x-$USER` | small, backed up (exact quota **[TO FILL IN]** -- check `myquota`) | none | conda base install, small config files, SLURM logs |
| `/anvil/scratch/x-$USER` | large (exact quota **[TO FILL IN]** -- check `myquota`) | **files untouched 30+ days are deleted** (shorter than Hopper's 90-day window) | code checkout, conda envs, data bundles, DuckDB files |
| `/anvil/projects/<allocation>/` | allocation-shared, not purged | permanent storage | small, final deliverables worth keeping past the 30-day scratch window (e.g. an aligned hazard raster, not raw source data) **[VERIFIED mentioned, not yet exercised]** |

Run `myquota` after first login to get exact numbers -- don't assume
Hopper's figures carry over.

### Data bundle layout

Same logical layout as Hopper (`docs/ORC_HOPPER_SETUP.md` SS2), rooted under
`/anvil/scratch/x-$USER/multimodal_hazard_data/` instead of
`/scratch/$USER/multimodal_hazard_data/`. **[VERIFIED]** the base CONUS
inputs (~4.2GB: `faf5_road_links.gpq`, OD matrices under `census_datasets/`,
`parameters/`) were relayed directly from Hopper's scratch rather than
re-derived -- the 30-day scratch purge means this bundle needs to either be
copied to `/anvil/projects/` for anything long-lived, or be cheap enough to
re-relay from Hopper on demand.

## 3. Environment setup

**[VERIFIED, partially]** -- the conda env at
`/anvil/scratch/x-akothawala/conda_envs/nird` exists and every completed job
above activates it successfully, but the exact creation command sequence
was never captured in the repo. The steps below mirror Hopper's env
(`docs/ORC_HOPPER_SETUP.md` SS3) adapted to Anvil's module system --
**[TO FILL IN]**: run this for real and correct anything that doesn't match.

```bash
module purge
module load anaconda/2024.02-py311      # confirmed to exist and work -- see SS3.1 below

# Unlike Hopper (raw miniforge install, needs `source .../activate <prefix>`),
# Anvil's anaconda module is expected to make `conda create`/`source activate`
# work directly in a batch script. Confirmed for `source activate` (every
# completed job above uses it); `conda create` itself not yet verified here.
conda create -p /anvil/scratch/x-akothawala/conda_envs/nird python=3.10 -y
source activate /anvil/scratch/x-akothawala/conda_envs/nird

conda install -c conda-forge igraph duckdb geopandas rasterio shapely pyproj scipy networkx pyarrow -y

mkdir -p /anvil/scratch/x-akothawala/multimodal_hazard_data/code
cd /anvil/scratch/x-akothawala/multimodal_hazard_data/code
git clone --branch <branch-name> https://github.com/AliMurtaza53/ResiFlow.git
cd ResiFlow

pip install -e . --no-deps
pip install nismod-snail psutil openpyxl snkit tqdm

python -c "import resiflow, igraph, duckdb, geopandas, rasterio, psutil, snkit, tqdm; print('ok')"
```

### 3.1 Module notes **[VERIFIED]**

- `module load anaconda/2024.02-py311` + `source activate <prefix>` is the
  pattern used by every completed job (`submit_cpu16/32/64_scale_test.slurm`,
  the gc-disable test, the py-spy profile run).
- An earlier, untested script (`submit_harvey_depths.slurm`, first-ever
  Anvil run, never confirmed) used `module load conda` + `conda activate`
  instead -- **do not copy that pattern**; it was an unverified guess, and
  the `anaconda/2024.02-py311` + `source activate` combination is the one
  with actual completed-job evidence behind it.

## 4. Config file

Create `$HOME/multimodal_hazard_project/config_anvil.json`:
```json
{
  "paths": {
    "soge_clusters": "/anvil/scratch/x-$USER/multimodal_hazard_data/soge_clusters",
    "base_path": "/anvil/scratch/x-$USER/multimodal_hazard_data/soge_clusters",
    "output_path": "/anvil/scratch/x-$USER/multimodal_hazard_data/results"
  }
}
```
(Substitute your actual `x-` username -- SLURM scripts don't expand `$USER`
inside a JSON file, same caveat as Hopper's guide.)

**Note the path split:** SLURM output/error logs go to `$HOME/multimodal_
hazard_project/logs_*.out/err` (small, backed up, matches Hopper's
convention) while the config file lives in the same `$HOME` directory but
all actual data/code/envs live under `/anvil/scratch/`. One early script
(`submit_harvey_depths.slurm`) put logs under `/anvil/scratch/%u/...`
instead -- the later, validated scripts all standardized on `$HOME`; use
`$HOME` going forward for consistency with Hopper.

## 5. SLURM partitions **[VERIFIED, partial]**

| Partition | Billing | Notes |
|---|---|---|
| `shared` | bills only for the cores/memory fraction actually requested | **default choice** -- every completed job above uses this |
| `highmem` | **node-exclusive** -- bills for the full 128 cores regardless of `--cpus-per-task`, at a **4x SU multiplier** (512 SU/hour) | Avoid unless a job genuinely needs >220G in one process; `shared` already covers everything run so far. Confirmed via RCAC docs, 2026-08-08. |

Anvil nodes: **2 sockets x 64 cores = 128 cores/node, AMD EPYC, 257400MB RAM**
per node (`sinfo -N -l`) -- materially different architecture from Hopper's
nodes, which is why cross-cluster CPU-scaling comparisons use identical
methodology (same `num_of_chunk`, same iteration count) rather than assuming
timings transfer.

**[TO FILL IN]**: time limits per partition (Hopper's `normal` caps at 7
days -- confirm Anvil `shared`'s cap via `sinfo` or RCAC docs before
planning a long convergence run).

## 6. THE critical gotcha: `--mem` silently inflates your CPU allocation

**[VERIFIED -- this cost 3 wasted/mislabeled jobs before being found.]**

On Anvil's `shared` partition, a generous `--mem` request can cause SLURM to
grant (and `$SLURM_CPUS_PER_TASK` to report) **more CPUs than
`--cpus-per-task` asked for**. The original cpu16/32/64 scaling attempts
(jobs 20240471, 20240487+20240693, 20240488) silently ran **65/122/119
workers** instead of 16/32/64 -- confirmed via `grep "Pool construction"` in
the job logs -- which is why they OOM'd or produced mislabeled results
despite generous memory headroom.

**Fix, and now the standing convention for every Anvil script:** pass the
intended worker count as a **literal hardcoded CLI argument** to the Python
script, never `$SLURM_CPUS_PER_TASK`:
```bash
# WRONG on Anvil's shared partition:
python scripts/1_network_flow_model_revision.py 20 $SLURM_CPUS_PER_TASK

# RIGHT:
python scripts/1_network_flow_model_revision.py 20 16   # literal 16, matches --cpus-per-task=16
```
Any new Anvil script should follow this pattern. If you see worker counts in
a log that don't match what you requested, this is almost certainly why --
check `grep "Pool construction" logs_*.err` first.

## 7. SLURM script template

Based on the validated `submit_cpu16_scale_test.slurm` (job 20240812,
COMPLETED):

```bash
#!/bin/bash
#SBATCH --job-name=<descriptive_name>
#SBATCH --account=civ260045
#SBATCH --partition=shared
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=16
#SBATCH --mem=120G
#SBATCH --output=/home/x-akothawala/multimodal_hazard_project/logs_%j.out
#SBATCH --error=/home/x-akothawala/multimodal_hazard_project/logs_%j.err

module purge
module load anaconda/2024.02-py311
source activate /anvil/scratch/x-akothawala/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_anvil.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_anvil.json

export RESIFLOW_RESULTS_VARIANT=<unique_variant_name>
export NIRD_RESULTS_VARIANT=<unique_variant_name>
export NIRD_BASELINE_DB_PATH=/anvil/scratch/x-akothawala/multimodal_hazard_data/<unique_variant_name>.duckdb

# Current validated defaults (2026-08-30) -- streaming_arrays supersedes the
# duckdb_chunked_compact strategy Hopper's older scripts still reference;
# confirmed 22.4% faster with identical dollar output.
export NIRD_LCP_DEST_CHUNK_SIZE=1000
export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_DUCKDB_MEMORY_LIMIT=90GB          # scale with --mem and core count, see Hopper guide SS "how to set"
export NIRD_LOG_RSS_CHECKPOINTS=1
export NIRD_LCP_SORT_BY_DEST_COUNT=1
export NIRD_PATH_REALIZATION_STRATEGY=streaming_arrays
export NIRD_DUCKDB_TEMP_DIRECTORY=/anvil/scratch/x-akothawala/multimodal_hazard_data/duckdb_tmp_<unique_name>
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

# LITERAL worker count, not $SLURM_CPUS_PER_TASK -- see SS6 above.
REPO=/anvil/scratch/x-akothawala/multimodal_hazard_data/code/ResiFlow
python $REPO/scripts/1_network_flow_model_revision.py 20 16
```

`NIRD_DUCKDB_TEMP_DIRECTORY` is set explicitly on every Anvil script seen so
far -- **[TO FILL IN]**: confirm whether this is strictly required on Anvil
(vs. Hopper, where the guide doesn't set it) or just defensive practice
carried over; if required, note why (e.g. default tmp not scratch-backed).

## 8. Known-good reference jobs (for comparison)

| Job ID | Config | Result |
|---|---|---|
| 20240812 | cpu16, `streaming_arrays` | COMPLETED, 5049.9s total |
| 20240809 / cpu64_v2 | cpu64 | pass 1 alone: 60.6min |
| 20243490 | cpu16, `streaming_arrays` | COMPLETED, 1336.4s total, 695.8s LCP dispatch |
| 20244142 | cpu16, full-run py-spy profile | found `gc_collect_main` as the largest LCP-dispatch hotspot |

CPU-scaling was found **weak/non-monotonic**: 16=740s, 32=757s, 64=701s for
the LCP-dispatch phase specifically -- not yet fully explained (see
`docs/PROJECT_LOG.md`'s "Performance findings"), likely multiprocessing
pool/pickle/IPC overhead rather than genuine compute scaling. Don't assume
more cores = proportionally faster on this cluster without checking phase
timings the way the reference jobs above do.

## 9. Sync and verify before every submission

Same discipline as Hopper (`docs/ORC_HOPPER_SETUP.md` SS8) -- Anvil has its
own separate clone under `/anvil/scratch/x-$USER/multimodal_hazard_data/code/
ResiFlow`. Push locally, `git pull` on Anvil, `git log -1 --stat` to confirm,
`cat` the actual SLURM script about to run before every `sbatch`.

## 10. Known issues and fixes

| Symptom | Cause | Fix |
|---|---|---|
| Worker count in logs doesn't match `--cpus-per-task` | `--mem` on `shared` inflates the granted CPU allocation | Pass the worker count as a literal CLI arg, never `$SLURM_CPUS_PER_TASK` (see SS6) |
| `ModuleNotFoundError: No module named 'resiflow'` | Package not installed into the active env | `pip install -e . --no-deps` from the repo root (same as Hopper) |
| Job OOMs despite generous `--mem` | Likely the same inflated-CPU-allocation issue -- more workers than intended means more DuckDB parallel buffers than `NIRD_DUCKDB_MEMORY_LIMIT` was sized for | Fix the worker count first (SS6), then re-tune memory if still needed |
| *(add entries here as you hit them)* | | |

## 11. Open items for whoever runs this next

- [ ] Document the actual ACCESS account-request process (SS1).
- [ ] Confirm exact `/home` and `/anvil/scratch` quotas via `myquota` (SS2).
- [ ] Confirm the `conda create` step works as written under
      `anaconda/2024.02-py311` (SS3) -- it's inferred from Hopper's
      pattern, not yet independently verified on Anvil.
- [ ] Confirm `shared` partition's time-limit cap (SS5).
- [ ] Determine whether `NIRD_DUCKDB_TEMP_DIRECTORY` is required or
      defensive-only on Anvil (SS7).
- [ ] Once the LCP-dispatch non-monotonic-scaling question (SS8) has an
      answer, record it here.
