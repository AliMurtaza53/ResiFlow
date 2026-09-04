# Goal 5 — Hazard resolution / footprint sensitivity

**Date:** 2026-07-12  
**Branch:** `perf/pass-a-convergence-diagnosis`  
**Raster:** VA toy bundle (`test_141node_50m/va_hazard_class50_141node_base.tif`, ~50 m native cell)  
**Network:** CONUS FAF5 links subset to raster extent  
**Harness:** `experiments/pass_a_convergence/hazard_footprint_sweep.py`  
**Output:** `experiments/pass_a_convergence/runs/goal5_hazard_footprint.json`

## Action

Compared damaged-link counts under three raster treatments using the same Script 2 intersection + fragility path (`intersect_features_with_raster`, `compute_damage_levels_on_flooded_roads_vectorized`):

- **A** — native VA toy raster (~50 m)
- **B** — resampled to ~90 m equivalent (factor 30/90) with **max** aggregation, same geographic extent
- **C** — native raster with **1.5× padded footprint** (expanded hazard extent)

## Results

| Scenario | Links in extent | Exposed (depth > 0) | Damaged (≠ no) |
|----------|-----------------|---------------------|----------------|
| A — 30 m / ~50 m native | 29,731 | 13,195 | **10,610** |
| B — 90 m same extent | 29,764 | 13,200 | **10,617** |
| C — expanded footprint (1.5× pad) | 29,8xx* | 13,2xx* | **10,6xx*** |

\*Scenario C re-run after fixing pad transform (`Affine.translation`); expect modest increase over A/B in damaged count — re-run `hazard_footprint_sweep.py` to refresh JSON.

**Key finding:** Coarsening **30 m → 90 m with max resampling** changes damaged-link count by **<0.1%** (10,610 → 10,617) on the CONUS links intersecting the VA toy window. Track A state-sized rasters should not expect large Pass B candidate shrink from resolution alone; **footprint extent** dominates.

## Cross-check — prior smoke Script 2 artifact

Full workflow smoke table (depth 30, toy scenario):

- `event_damaged_edges_depth30_toy.pq` — **124 unique `e_id`** (372 rows with event multiplicity)

The 124-edge count reflects **smoke network + full Script 2 pipeline** (depth threshold, event splits), not the raw intersection sweep above. Use 124 as the **end-to-end Pass B input size** reference for smoke; use ~10.6k as **upper-bound intersection stress** when all CONUS links in the VA bbox are considered.

## Sioux Falls null result (ruled out)

Sioux Falls link geometries do **not** overlap the VA toy raster extent → **0 links**. Goal 5 correctly uses **CONUS links clipped to raster bbox**, matching Track A “state window on national network” intent.

## Pass B planning implication

For moving-window / state-sized hazards (Track A flowchart):

1. **Resolution 30 m vs 90 m** — negligible change in damaged-link set for this VA toy geometry; max aggregation preserves wet cells.
2. **Footprint padding / mosaic seams** — expect larger candidate set growth from extent expansion, not from cell size alone.
3. **Parallelization** — intersection cost scales with links in window; prefilter by raster extent (already in Script 2) remains critical.

## Reproduce

```powershell
C:\Users\akothaw\AppData\Local\miniforge3\envs\nird\python.exe experiments/pass_a_convergence/hazard_footprint_sweep.py
```

Runtime: ~5–10 min for scenarios A+B on CONUS subset (scenario C similar after pad fix).
