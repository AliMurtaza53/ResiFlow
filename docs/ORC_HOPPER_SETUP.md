# Running ResiFlow on GMU ORC Hopper

End-to-end guide for setting up and executing the ResiFlow Pass A
(`network_flow_model`) workflow on GMU's ORC Hopper cluster, based on the
actual setup/debug process from the Pass A convergence performance work
(see `notes/perf_findings/GOAL8_FULL_QUEUE_RESULTS.md` Goal 15 for the
memory-fix backstory this guide's env vars depend on).

**Branch note (important, read first):** the memory/performance fixes this
guide relies on (`NIRD_LCP_DEST_CHUNK_SIZE`, `NIRD_FLOW_DB_BATCH_SIZE`,
`NIRD_DUCKDB_MEMORY_LIMIT`, `NIRD_LOG_RSS_CHECKPOINTS`) live on the
`perf/lcp-dest-chunked-dispatch` branch, not `main`, as of this writing.
Clone/checkout that branch explicitly, or confirm these fixes have been
merged to `main` before following this guide against `main`.

---

## 1. Getting an account

- All GMU faculty/staff/students are eligible, sponsored by a GMU faculty
  member. Fill out the [account request form](https://qafederation.ngwebsolutions.com/sp/startSSO.ping?PartnerIdpId=https://shibboleth.gmu.edu/idp/shibboleth&TargetResource=https://dynamicforms.ngwebsolutions.com/Submit/Form/Start/fadd3769-89be-46b4-8eb3-7d13d2237c5b),
  then complete the required "New User tutorial" module -- access doesn't
  activate until that's done.
- Support: `orchelp@gmu.edu`, or walk-in office hours Mon-Thu 2-3pm, Merten
  Hall Room 3112.
- Connect via `ssh -X yourNetID@hopper.orc.gmu.edu`. VPN is only required
  for the Open OnDemand web portal (`ondemand.orc.gmu.edu`), not plain SSH.

## 2. Storage layout

| Mount | Quota | Purge policy | Use for |
|---|---|---|---|
| `/home/$USER` | 60GB, backed up | none | conda base install, small config files, SLURM logs |
| `/scratch/$USER` | no size limit (100k file cap) | files untouched 90+ days deleted | code checkout, conda **envs**, data bundles, DuckDB files |

**Put your conda environments and the ResiFlow data bundle under `/scratch`,
not `/home`.** A `conda create` without `-p` defaults into `$HOME`, which
will eat into the 60GB quota fast (geospatial envs with GDAL/rasterio/
geopandas routinely run several GB).

If `/home` usage looks larger than `du -sh /home/$USER/*` accounts for,
check hidden dotfiles -- the conda package cache
(`~/.conda/pkgs`) is the usual culprit:
```bash
du -sh /home/$USER/.[!.]* 2>/dev/null | sort -rh | head -20
conda clean --all -y   # safe -- only clears cached package downloads
```
Also safe to delete once miniforge is installed: the installer script
itself (`rm ~/Miniforge3-Linux-x86_64.sh`).

### Data bundle layout

The code expects `lodes_data/` as a **sibling** of `soge_clusters/`, not
nested inside it:
```
/scratch/$USER/multimodal_hazard_data/
├── soge_clusters/
│   ├── networks/faf5/faf5_road_links.gpq
│   ├── census_datasets/faf5_od_matrix.pq
│   ├── inputs/test_141node_50m/va_hazard_class50_141node_base.tif   # Pass B / hazard only
│   └── tables/event_damaged_edges_depth30_toy.pq                      # Pass B / hazard only
├── lodes_data/processed/lodes_passenger_assignment_od_jt00_2022.parquet
└── results/                                                            # outputs land here
```
The two "Pass B / hazard only" files are not needed for a plain Pass A
scaling/convergence test -- only the network graph, freight OD matrix, and
one LODES passenger-OD parquet are required for that.

## 3. Environment setup

```bash
# Base miniforge install goes in $HOME (small, keep it there)
wget https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh
bash Miniforge3-Linux-x86_64.sh -b -p $HOME/miniforge
source $HOME/miniforge/bin/activate

# The actual environment goes in /scratch, as its own prefix (not $HOME/miniforge/envs/...)
conda create -p /scratch/$USER/conda_envs/nird python=3.10 -y
conda activate /scratch/$USER/conda_envs/nird

# Geospatial/binary-heavy deps are more reliable via conda-forge:
conda install -c conda-forge igraph duckdb geopandas rasterio shapely pyproj scipy networkx pyarrow -y

# Clone the code (into scratch -- the repo + git history don't need to live in $HOME)
mkdir -p /scratch/$USER/multimodal_hazard_data/code
cd /scratch/$USER/multimodal_hazard_data/code
git clone --branch perf/lcp-dest-chunked-dispatch https://github.com/AliMurtaza53/ResiFlow.git
cd ResiFlow

# Critical, easy to miss: install the resiflow package itself.
# scripts/1_network_flow_model_revision.py only puts the repo root on
# sys.path -- it does NOT make `import resiflow` work on its own, since the
# package lives under src/resiflow (see pyproject.toml's
# [tool.setuptools.packages.find] where = ["src"]). Without this step you
# will get ModuleNotFoundError: No module named 'resiflow'.
pip install -e . --no-deps   # --no-deps: the conda-forge installs above already cover the binary-heavy deps
pip install nismod-snail psutil openpyxl   # remaining pyproject.toml deps not pulled in above

# Sanity check before running anything real:
python -c "import resiflow, igraph, duckdb, geopandas, rasterio, psutil; print('ok')"
```

`psutil` matters specifically because `NIRD_LOG_RSS_CHECKPOINTS=1` silently
fails (caught by a try/except, logged as a non-fatal error) without it --
the job still runs, you just lose all memory visibility.

### Why `source .../activate <prefix>` instead of `conda activate <prefix>` in SLURM scripts

SLURM batch shells aren't interactive login shells, so `conda init`'s shell
hook may not be present. `source $HOME/miniforge/bin/activate /scratch/$USER/conda_envs/nird`
works regardless, since it doesn't depend on shell hook initialization.

## 4. Config file

Create `$HOME/multimodal_hazard_project/config_hopper.json` (kept in
`$HOME` since it's tiny -- unlike the data, this isn't a quota concern):
```json
{
  "paths": {
    "soge_clusters": "/scratch/$USER/multimodal_hazard_data/soge_clusters",
    "base_path": "/scratch/$USER/multimodal_hazard_data/soge_clusters",
    "output_path": "/scratch/$USER/multimodal_hazard_data/results"
  }
}
```
(Substitute your actual username for `$USER` -- SLURM scripts don't expand
this inside a JSON file.)

## 5. SLURM partitions

Partition names and limits drift over time on this cluster -- always
confirm with `sinfo` before assuming a partition exists. As of this
writing:

| Partition | Time limit | Notes |
|---|---|---|
| `normal` | 7 days | Default choice for CPU work, no condo/contributor buy-in needed |
| `interactive` | 12 hours | Open OnDemand sessions |
| `contrib` / `contrib-gpuq` / etc. | 7 days / 5 days | Requires condo node contribution for priority access |
| `bigmem` | 7 days | High-memory nodes |
| `gpuq` | 5 days | GPU nodes -- **not useful for this workload**, no GPU code path exists in ResiFlow (igraph/DuckDB/pandas are all CPU-only) |

There is **no `debug` partition** on this cluster (despite some ORC wiki
pages referencing one) -- use `normal` for short test jobs too, just with a
correspondingly short `--time`.

## 6. SLURM script template

```bash
#!/bin/bash
#SBATCH --job-name=hazard_scale_test
#SBATCH --partition=normal
#SBATCH --time=01:30:00                      # see "how much time" note below
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --output=/home/$USER/multimodal_hazard_project/logs_%j.out
#SBATCH --error=/home/$USER/multimodal_hazard_project/logs_%j.err

module purge
source $HOME/miniforge/bin/activate /scratch/$USER/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json

# Cap iterations for a scaling/smoke test; unset (or set to 0) for a real
# convergence run.
export RESIFLOW_MAX_FLOW_ITERATIONS=1
export NIRD_MAX_FLOW_ITERATIONS=1

# Give each concurrent job its own results variant / DB path so parallel
# test jobs don't collide.
export RESIFLOW_RESULTS_VARIANT=scale_test_cpu8
export NIRD_RESULTS_VARIANT=scale_test_cpu8
export NIRD_BASELINE_DB_PATH=/scratch/$USER/multimodal_hazard_data/scale_test_cpu8.duckdb

# Goal 15 memory fixes -- keep these regardless of core count.
export NIRD_LCP_DEST_CHUNK_SIZE=300
export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_DUCKDB_MEMORY_LIMIT=40GB          # see memory-limit note below
export NIRD_LOG_RSS_CHECKPOINTS=1
export NIRD_LCP_SORT_BY_DEST_COUNT=1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

python /scratch/$USER/multimodal_hazard_data/code/ResiFlow/scripts/1_network_flow_model_revision.py 20 $SLURM_CPUS_PER_TASK
```

### How much `--time` to request

**50 minutes is not enough** for even a single iteration at full-OD scale
(~9.68M rows). A real test at `--cpus-per-task=4` needed ~44.5 minutes just
for LCP dispatch + od_id assignment + edge aggregation, before the
remaining per-iteration steps (edge speed updates, `remain_od`
recomputation, cleanup).

**1.5 hours isn't enough either once `full_odpfc` output is involved.**
A `--cpus-per-task=8` run with `NIRD_PATH_REALIZATION_STRATEGY=duckdb_chunked_compact`
got `CANCELLED DUE TO TIME LIMIT` at `--time=01:30:00` with **no OOM** --
pool dispatch (~18min) + od_id assignment (~4min) + chunked pass 1
(~45-50min) + pass 2 (~8min) already consumed the entire budget before the
`full_odpfc` `INSERT` (writing all 9.68M rows to `odpfc`) got any time at
all. **Request at least 4 hours** for a single-iteration run at this scale
with `full_odpfc` output enabled; a real multi-iteration convergence run
needs proportionally more (`normal`'s 7-day cap is the real ceiling to plan
against).

### How to set `NIRD_DUCKDB_MEMORY_LIMIT`

This is **not** a fixed safe value -- it must leave headroom within your
`--mem` request alongside Python-side RSS, and it needs to scale up with
`--cpus-per-task` because DuckDB's own `PRAGMA threads` (set internally to
`num_of_cpu`) means more cores also means more parallel hash/sort buffers
inside DuckDB itself, which needs more memory for the *same* data. Setting
this too conservatively causes
`_duckdb.OutOfMemoryException: Out of Memory Error: failed to pin block...`
during the `itter_path` aggregation phase (not the LCP dispatch phase).
At `--mem=64G` with the full ~9.68M-row OD:
- `--cpus-per-task=4`: 24GB caused no issue, but 32GB gives more margin (observed Python RSS peaked ~23.7GB pre-`itter_path`)
- `--cpus-per-task=8`: 24GB **failed** (OOM at 22.3/22.3GB used); 40GB resolved it
  at the time, but a later `--mem=128G` / `NIRD_DUCKDB_MEMORY_LIMIT=90GB` run
  at the same OD scale OOM'd again (`83.8/83.8 GiB used`) despite ~16GB of the
  node sitting unused -- see "The bigger lever" below. Treat the 40GB figure
  as strategy-dependent, not a durable ceiling.

Rule of thumb: budget `--mem` total, subtract observed/expected Python-side
RSS (check `NIRD_LOG_RSS_CHECKPOINTS` output), and give DuckDB most of the
rest, scaling upward with core count.

### The bigger lever: `NIRD_PATH_REALIZATION_STRATEGY`

Raising `NIRD_DUCKDB_MEMORY_LIMIT` is not sufficient by itself at
`--cpus-per-task=8` and full OD scale. The reason: `itter_path`'s **default**
strategy (`legacy_compact_sql`) runs the path-explode `CROSS JOIN
UNNEST(t.path)` join that turns OD paths into per-edge flows as **one
unchunked DuckDB query over the entire OD table**. `NIRD_LCP_DEST_CHUNK_SIZE`
does not touch this -- that env var only chunks the earlier LCP dispatch
phase. At 8 threads, DuckDB runs that single giant join with 8 parallel
hash/sort buffers that must stay pinned (non-spillable) for the join's
duration, so the *whole table's* working set has to fit at once, not a
fraction of it.

Set `NIRD_PATH_REALIZATION_STRATEGY=duckdb_chunked_compact` to route through
the alternate code path in `itter_path` that actually respects chunking: it
runs the same join in `num_of_chunk` (the script's first CLI arg) row batches
via `WHERE t.rn BETWEEN ...`, so DuckDB only needs to hold one chunk's join
working set pinned at a time. **This is the fix that matters** -- treat
`NIRD_DUCKDB_MEMORY_LIMIT` as a safety margin on top of it, not the primary
lever.

Other strategies available in the same env var: `pandas_chunked` (most
memory-conservative, offloads the explode/groupby to pandas in chunks, likely
slower) and the default `legacy_compact_sql` (fine at smaller OD scale or
lower core counts where the single-query working set fits in the configured
`NIRD_DUCKDB_MEMORY_LIMIT`).

## 7. Sync and verify before every submission

Edits made locally (code fixes, SLURM script changes) only exist in the local
working copy until pushed -- Hopper has its own separate clone under
`/scratch/$USER/multimodal_hazard_data/code/ResiFlow`. **Every time a file
changes, this sync has to happen before the next `sbatch`, or the job runs
against stale code/config with no warning.**

1. **Locally:** commit and push the change to the branch Hopper tracks
   (`perf/lcp-dest-chunked-dispatch`, or wherever the fixes have landed --
   see the branch caveat at the top of this doc).
   ```bash
   git add -A
   git commit -m "..."
   git push
   ```
2. **On Hopper:** `cd` into the cloned repo and pull.
   ```bash
   cd /scratch/$USER/multimodal_hazard_data/code/ResiFlow
   git pull
   git log -1 --stat        # confirm the expected commit/fix is actually present
   ```
3. **Verify the SLURM script itself**, separately from the code -- it's easy
   to edit `submit_cpu8.slurm` locally, forget to re-sync it (or sync the repo
   but not notice the script still has stale env vars), and burn another
   partial-hour job on a config you didn't mean to run.
   ```bash
   git status              # nothing unexpected modified/stale after the pull
   git diff HEAD~1 -- experiments/pass_a_convergence/hopper/submit_cpu8.slurm
   cat experiments/pass_a_convergence/hopper/submit_cpu8.slurm   # eyeball the actual env vars that will run
   ```
   If the script lives outside git (hand-edited directly on Hopper), skip the
   `git diff` and just `cat` it before every `sbatch` -- there's no other way
   to confirm what's about to run.

Only once both checks pass, move to submission below.

## 8. Submitting and monitoring

```bash
sbatch submit_test.slurm
squeue -u $USER
tail -f /home/$USER/multimodal_hazard_project/logs_<jobid>.err
```

Key log lines to watch for:
- `Chunked LCP dispatch: N origin-tasks split into M tasks` -- confirms the chunking fix is active
- `RSS checkpoint [...]` -- memory visibility (requires `psutil`)
- `The least-cost path flow allocation time: ...` -- the core scaling metric
- `Stop: ...` -- clean completion of the flow-assignment loop
- `CANCELLED ... DUE TO TIME LIMIT` -- needs more `--time`, not necessarily a real problem
- `_duckdb.OutOfMemoryException` -- needs more `NIRD_DUCKDB_MEMORY_LIMIT` headroom (see above)

### Comparing core counts

```bash
grep "least-cost path flow allocation time" /home/$USER/multimodal_hazard_project/logs_cpu*.err
```

**Reference data point** (full ~9.68M-row OD, single iteration, otherwise
identical config): `--cpus-per-task=4` -> 1985.8s; `--cpus-per-task=8` ->
1064.3s -- a ~1.87x speedup for 2x the cores, close to linear. This is the
opposite of what was observed on a hybrid P-core/E-core workstation CPU
(where 8 threads regressed vs. 4) -- Hopper's uniform real cores scale
properly for this workload, since the LCP dispatch phase is embarrassingly
parallel per-origin.

## 9. Known issues and fixes

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'resiflow'` | Package not installed into the active env | `pip install -e . --no-deps` from the repo root |
| `ModuleNotFoundError: No module named 'psutil'` | Not in `pyproject.toml`'s core deps; needed for `NIRD_LOG_RSS_CHECKPOINTS` | `pip install psutil` -- non-fatal without it, but you lose memory visibility |
| `sbatch: error: invalid partition specified: debug` | No `debug` partition exists on this cluster | Use `--partition=normal` |
| `slurmstepd: error: ... CANCELLED ... DUE TO TIME LIMIT` | `--time` too short for the OD scale being run | See "how much `--time` to request" above |
| `_duckdb.OutOfMemoryException: failed to pin block ...` | `NIRD_DUCKDB_MEMORY_LIMIT` too low relative to `--mem` and core count | See "how to set `NIRD_DUCKDB_MEMORY_LIMIT`" above |
| Same OOM persists even after raising `NIRD_DUCKDB_MEMORY_LIMIT` close to `--mem`, with node memory still unused | Default `itter_path` strategy runs the path-explode join unchunked over the whole OD table | Set `NIRD_PATH_REALIZATION_STRATEGY=duckdb_chunked_compact` -- see "The bigger lever" above |
| Env vars like `NIRD_LCP_DEST_CHUNK_SIZE` seem to have no effect | Cloned `main` instead of the branch with the fix | Check you're on `perf/lcp-dest-chunked-dispatch` (or wherever it's been merged to) |
