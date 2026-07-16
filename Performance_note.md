## CONUS-scale performance: bottlenecks and mitigation options

ResiFlow’s CONUS path is a **four-stage, CPU-bound geospatial + network-assignment pipeline** on the full FAF5 road layer (~**484k directed links**; Script 2 logs show raster prefilter from ~484k → hazard extent subset) with county-level freight OD merged with LODES passenger OD. Current smoke configuration (`scripts/run_conus_smoke_50k.ps1`) subsamples to **50k OD rows**, caps assignment to **2 iterations**, runs **freight + passenger**, and executes **Pass A → Script 2 (×3 events) → Script 3 → Pass B → Script 4 (×3 events)**. Sioux Falls multihazard (24 nodes, 6 hazards) completes in **~5 min**; CONUS smoke at 50k OD is **~1.5–3 h** wall-clock on a single workstation (order-of-magnitude; dominated by Scripts 1 and 4). Full CONUS with unconstrained OD and full equilibrium convergence is not yet a practical single-machine run without further algorithmic or infrastructure changes.

---

### Where time goes (by script)

| Stage | Core work | Scaling | Typical bottleneck |
|-------|-----------|---------|-------------------|
| **Script 1 (Pass A)** | Cap-constrained iterative assignment: igraph **shortest-path trees per origin batch**, capacity feedback, DuckDB path realization (`baseline.duckdb`) | **O(I × \|O\| × SP)** per iteration *I*; path storage **O(\|OD\| × avg path length)** | CPU (LCP), RAM, disk I/O on DuckDB |
| **Script 2** | Hazard raster ∩ link geometries via **snail** (GDAL), plus fragility transforms | **O(links in raster extent)** per event; full network load once | Geometry/raster I/O; largely single-threaded per event |
| **Script 3** | Segment-level HAZUS-style damage curves | **O(damaged segments)** | Usually minor vs assignment |
| **Pass B (Script 1 rerun)** | Filter ODs whose baseline paths cross damaged edges → `event_disrupted_candidates/` | Depends on hazard footprint + path DB size | DuckDB scan + path–edge intersection |
| **Script 4** | Per disrupted OD: chunk expansion, igraph rebuild, **two** `network_flow_model` solves (post-disruption + consistent baseline), × recovery days × **freight + passenger** | **O(\|candidates\| × scenarios × modes)** | Dominates once \|candidates\| ≫ smoke sample |

**Multihazard CONUS** multiplies Scripts 2–4 by the number of hazard scenarios (unique `scenario_param` per hazard). Script 1 baseline is shared (Pass A once), but disruption/damage/reroute loops are per hazard unless parallelized at workflow level.

---

### Why the current algorithm is expensive

Production assignment is **not** standard BPR Frank–Wolfe UE. Script 1 uses **iterative all-or-nothing with piecewise cap-constrained speed–flow feedback** (`road_revised.network_flow_model`), with shortest paths on an **igraph** graph and optional multiprocessing (`num_of_cpu`). A BPR + Frank–Wolfe UE implementation exists (`resiflow.assignment.ue_bpr`) but is a **TNTP benchmark only**, not the CONUS production path.

Asymptotically, each assignment iteration is still **one shortest-path computation per origin** (batched via `get_shortest_paths` / worker pool). Path realization materializes OD→path→edge incidence in **DuckDB** or partitioned Parquet (`NIRD_PATH_REALIZATION_STRATEGY=streaming_arrays`). That design is correct for traceability (which ODs cross which damaged edges) but memory- and I/O-heavy at national OD scale.

Script 4 repeats the same pattern on the **disrupted subgraph** for every recovery day and both modes, with a **pre/post cost difference** for rerouting metrics — so reroute cost is sensitive to trip isolation (negative values when isolated trips drop out of post-assignment).

---

### What is *not* a bottleneck today

- **GPU**: No CUDA/cuGraph path in the stack. igraph, snail/GDAL, DuckDB, and pandas/geopandas are CPU libraries. A GPU would require a different shortest-path / assignment backend and likely a full rewrite of path-realization logic — unlikely to be a drop-in win without OR-level reformulation.
- **Script 3 direct damage**: Segment curve evaluation is cheap relative to national assignment.

---

### Mitigations (ordered by practicality)

**1. More compute (easiest near-term)**  
- Increase `num_of_cpu` on Scripts 1 and 4 (multiprocessing LCP pool), but
  **don't push past 4** on this machine — 8 measurably regressed (§10),
  likely hyperthread contention. On this machine (i7-14700, 8 P-cores/16
  threads + 12 E-cores/12 threads), unpinned worker processes can land on
  slower E-cores; set
  `NIRD_WORKER_CPU_AFFINITY="0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15"` to pin
  LCP workers to the (empirically verified — see
  `notes/perf_findings/GOAL8_FULL_QUEUE_RESULTS.md` §8) P-core logical
  processors; measured ~1.7-2x LCP dispatch speedup. Opt-in and
  machine-specific — re-verify core indices before reusing on different
  hardware.
  **`NIRD_PERSISTENT_LCP_POOL=1` (create the worker pool once instead of
  respawning it) wins on short runs but degrades badly over many iterations
  (LCP time nearly tripled by iteration 2 in a 5M-OD test — §11) — do not
  use it for convergence-style/long runs, only short bounded-iteration
  smoke tests.**
- Run hazards/events as **embarrassingly parallel jobs** (separate processes per `scenario_param` × event).  
- Use a machine with **fast NVMe** for `baseline.duckdb` and recovery DBs (`NIRD_BASELINE_DB_PATH`).

**2. Memory / I/O tuning**  
- Smoke already sets: `NIRD_ODPFC_OUTPUT_MODE=skip`, `NIRD_WRITE_FULL_ODPFC=0`, `streaming_arrays`, `NIRD_ENABLE_SPLIT_CACHE=1`.  
- For full runs: tune `NIRD_FLOW_DB_BATCH_SIZE` (default 100k) -- this is the
  dominant lever on peak RAM at national OD scale, **not** worker count or
  per-origin destination-list size (both tested and ruled out; see
  `notes/perf_findings/GOAL8_FULL_QUEUE_RESULTS.md` Goal 15). At 5M OD, the
  default 100k caused peak RSS to reach ~45GB (killed a run at 625MB free
  system RAM); `NIRD_FLOW_DB_BATCH_SIZE=50000` cut that to ~7.2GB for only
  ~+45% wall time per iteration -- the recommended setting for any
  multi-million-OD run on a workstation-class machine. Also set an explicit
  `PRAGMA memory_limit` via `NIRD_DUCKDB_MEMORY_LIMIT` (default 24GB) as a
  backstop. Avoid materializing full ODPFC unless needed for Pass B.  
- If RAM blows up further: reduce `ShortestPathDestBatch` (split
  all-destinations-from-one-origin calls) per CONUS workflow docs -- note
  this trades wall time for memory in the same way as
  `NIRD_FLOW_DB_BATCH_SIZE`, and the batch-size lever proved much more
  effective per unit of slowdown in direct testing.

**3. Demand / scope reduction (valid for smoke & sensitivity)**  
- `RESIFLOW_SAMPLE_OD_N` (50k smoke).  
- `RESIFLOW_MAX_FLOW_ITERATIONS` (1–2 for smoke; `0` = run to convergence).  
- Pass B candidate filtering (`NIRD_BASELINE_PATH_OUTPUT_MODE=event_candidates`) avoids re-solving the full OD matrix in Script 4.

**4. Algorithm / OR changes (higher effort, largest upside)**  
- **Frank–Wolfe / TAPAS-class assignment**: Replace or shadow the current cap-constrained AON loop with a proper traffic assignment method (FW already prototyped for BPR UE). Benefit: fewer iterations to equilibrium-like state; does **not** remove per-iteration shortest-path cost but improves convergence rate. TAPAS-style advanced step rules may help if cap-constrained piecewise curves can be expressed in a differentiable or convex surrogate — needs OR validation against current piecewise profiles.  
- **Hybrid / hierarchical routing**: Highway hierarchy, regional partitioning, or supernode aggregation to cut SP work on 484k-link graphs.  
- **Candidate-only rerouting**: Strengthen Pass B so Script 4 never touches non-impacted ODs (already the design intent).  
- **Isolation-aware indirect cost**: Treat isolated demand as lost surplus (not negative rerouting), important for OR interpretation at CONUS scale.

**5. Script 2 geo performance**  
- Raster extent prefilter already reduces 484k → hazard subset.  
- Production CONUS needs **tiled national hazard mosaics** + parallel snail jobs; current path is one state-size toy rasters (Virginia, US) on full FAF5 geometry.  
- Ensure EPSG:2163 normalization (`normalize_hazard_crs.py`) to avoid snail/GDAL failures/retries.

---

### Reference configuration (current smoke)

```powershell
RESIFLOW_SAMPLE_OD_N=50000
RESIFLOW_MAX_FLOW_ITERATIONS=2
NIRD_PATH_REALIZATION_STRATEGY=streaming_arrays
NIRD_ODPFC_OUTPUT_MODE=skip
NIRD_ENABLE_PASSENGER_REROUTING=1
OMP_NUM_THREADS=1   # avoid oversubscription with multiprocessing pool

# Recommended additions on this machine (i7-14700) when num_of_cpu > 1 (keep num_of_cpu<=4):
NIRD_WORKER_CPU_AFFINITY=0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15   # verified P-core threads
# NIRD_PERSISTENT_LCP_POOL=1   # only for short smoke tests -- degrades over long runs, see §11

# Required at multi-million-OD scale (Goal 15) to avoid OOM:
NIRD_FLOW_DB_BATCH_SIZE=50000   # default 100k risks ~45GB peak RSS at 5M OD; 50k -> ~7.2GB
NIRD_DUCKDB_MEMORY_LIMIT=24GB   # backstop PRAGMA memory_limit on the long-lived DuckDB connection
```

**Bottom line for OR/CS/software:** CONUS scale is gated by **repeated national-scale shortest-path assignment and path materialization**, not by damage curve evaluation or visualization. Near-term wins are **parallel hardware + workflow sharding + candidate filtering**; medium-term wins require **assignment algorithm upgrades (FW/TAPAS-class)** and/or **network decomposition**; GPUs are not on the critical path unless the assignment kernel is reimplemented.