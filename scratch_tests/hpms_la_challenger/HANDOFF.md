# Handoff: HPMS-LA challenger → assignment performance test

For a fresh agent. Branch: `feature/hpms-la-challenger`.
Mandate: `C:\Users\akothaw\Desktop\hpms_la_challenger_instructions.md`.
Hopper SSH: `ssh hopper-me` (see `C:\Users\akothaw\Desktop\hopper_access_handoff.md`).

## What is already done (do not rebuild)

| Artifact | Path |
|---|---|
| Mid-noded LA HPMS links/nodes (arterial/freeway/collector only) | `scratch_tests/hpms_la_challenger/artifacts/hpms_la_links_noded.parquet`, `…/hpms_la_nodes_noded.parquet` |
| Topology QA | `…/artifacts/topology_qa_noded.json` |
| 12 LA centroids | `scratch_tests/hpms_la_challenger/la_centroids.json` |
| Voronoi catchments + block counts | `…/artifacts/la_subarea_catchments.json` |
| Unique-segment connector dry-run | `…/artifacts/enclosing_connector_probe.json` |
| Inspect map | `C:\Users\akothaw\Desktop\hpms_la_challenger_progress_map.html` |

**Reuse, do not re-derive:** `src/resiflow/hpms_fclass.py`, `src/resiflow/preprocess/network_connector_insertion.py` (`is_eligible_attachment_edge`, `find_enclosing_connectors`, `split_edge_at_fraction`, `build_bidirectional_connector`).

**Connector rules already enforced in the dry-run:** eligible edges only (no freeway/ramp/bridge/tunnel); mid-segment; **≤1 connector per HPMS `route_id`** (and parent_e_id / 50 m corridor fallback). Uncapped enclosing-block rule still returns 1 for all 12 (unenclosed); unique-segment pad targets 2–4 without inventing roads.

**Known limits:** locals (`f_system=7`) excluded — 100% missing `through_lanes` in LA. Do not invent lanes. Network is LA densification candidate, not national HPMS.

## What is NOT done (your job for a performance test)

Demand is not yet loaded onto a spliced FAF5+HPMS network. No cheap-checks written. No SLURM assignment run. Map = dry-run only.

## Steps to test model performance (Hopper)

### 0. Sync code + artifacts

```bash
# local
cd C:/Users/akothaw/Desktop/ResiFlow
git checkout feature/hpms-la-challenger
# push if remote lacks this branch, then on Hopper:
ssh hopper-me 'cd /scratch/akothaw/multimodal_hazard_data/code/ResiFlow && git fetch && git checkout feature/hpms-la-challenger && git pull'
scp -r scratch_tests/hpms_la_challenger/artifacts \
  hopper-me:/scratch/akothaw/multimodal_hazard_data/scratch_tests/hpms_la_challenger/
scp scratch_tests/hpms_la_challenger/la_centroids.json \
  hopper-me:/scratch/akothaw/multimodal_hazard_data/scratch_tests/hpms_la_challenger/
```

### 1. Isolated network copy (never write shared soge_clusters)

```bash
SRC=/scratch/akothaw/multimodal_hazard_data/soge_clusters
DST=/scratch/akothaw/multimodal_hazard_data/scratch_tests/hpms_la_challenger/isolated_base
rm -rf "$DST"
cp -al "$SRC" "$DST"
# break hardlinks BEFORE any rewrite
rm -f "$DST/networks/faf5/faf5_road_links.gpq" "$DST/networks/faf5/faf5_road_nodes.gpq"
# after writes: verify shared original row counts/sizes unchanged
```

Config shape (paths only): mirror `/home/akothaw/multimodal_hazard_project/config_hopper_v4_connector.json` but point `paths.base_path` / `paths.soge_clusters` at `$DST`.

### 2. Splice ADD-ONLY + attach 12 centroids

New script (does not exist yet) should:

1. Load FAF5 links/nodes from `$DST` (native CRS EPSG:9311).
2. Append `hpms_la_links_noded.parquet` / `hpms_la_nodes_noded.parquet` with their own ID space (nodes already ≥500000).
3. Splice HPMS↔FAF5 at matched points without mutating FAF5 attributes except legal mid-segment splits via `split_edge_at_fraction`.
4. For each of 12 centroids in `la_centroids.json` / `enclosing_connector_probe.json` → `connectors_unique_segment`: insert centroid node + bidirectional connectors with `build_bidirectional_connector`; split attachment edges.
5. Relabel LA OD destinations/origins from FAF node ids → new centroid ids using  
   `/scratch/akothaw/multimodal_hazard_data/scratch_tests/county_connector_remedy/v3_vehicle_trips/passenger_od_multinode_v3.pq`  
   (same OD totals; only attachment nodes change).
6. Write patched `faf5_road_links.gpq` / `faf5_road_nodes.gpq` into `$DST` and a new OD parquet under  
   `/scratch/akothaw/multimodal_hazard_data/scratch_tests/hpms_la_challenger/`.

### 3. Cheap-checks (before any assignment)

Mirror  
`/scratch/akothaw/multimodal_hazard_data/scratch_tests/county_connector_remedy/verify_la_connector_cheap_checks.py`:

- demand conservation (exact)
- no centroid shortcut
- through-route cost unchanged on unsplit FAF5 paths
- legal topology (eligibility + one connector per route_id)

Fail → stop and report. Do not submit SLURM.

### 4. Assignment twin (2 iter, fair compare)

Template:  
`/scratch/akothaw/multimodal_hazard_data/code/ResiFlow/experiments/conus_multihazard/hopper/submit_la_connector_BEFORE_2iter.slurm`

Keep identical: `NIRD_MAX_FLOW_ITERATIONS=2`, `NIRD_PATH_REALIZATION_STRATEGY=streaming_arrays`, bigmem 400G,  
`scripts/1_network_flow_model_revision.py`.

- **BEFORE (FAF5 arm):** existing unmodified network + `passenger_od_multinode_v3.pq` (or the project’s current FAF5 connector AFTER if comparing against denser FAF5 connectors — document which).
- **AFTER (HPMS arm):** config pointing at `$DST` + HPMS-patched OD; unique `NIRD_RESULTS_VARIANT` + DuckDB path under hpms_la_challenger.

### 5. Metrics / decision gate

Report: `assigned_fraction` at final iter (common demand basis) and **assigned-vehicles-per-compute-hour**.  
Anchor discussed: ~20% improvement — **confirm with user before declaring verdict**.  
If topology/splice fails or gain doesn’t justify network growth → stop with a clear no.

## Rebuild map after splice (optional)

```text
python scratch_tests/hpms_la_challenger/probe_enclosing_connectors.py
python scratch_tests/hpms_la_challenger/run_catchments_local.py   # if catchments stale
python scratch_tests/hpms_la_challenger/build_progress_map_html.py
→ C:\Users\akothaw\Desktop\hpms_la_challenger_progress_map.html
```

## Do not

- Build statewide/national HPMS
- Invent `through_lanes` for locals
- Write into shared `/scratch/.../soge_clusters` without the `cp -al` + `rm` isolation pattern
- Treat dry-run connectors on the HTML map as already in the assignment network
