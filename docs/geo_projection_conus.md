# CONUS Geo Projection Guide

This project uses **EPSG:2163** (US National Atlas Equal Area / NAD83 Albers) for CONUS
freight networks and hazard rasters. State-sized and multi-state hazard tiles should
share this CRS so Script 2 can intersect them with the FAF5 link layer without
projection failures.

## Automatic setup

Importing or running scripts that use [`src/nird/geo_runtime.py`](../src/nird/geo_runtime.py)
configures GDAL and PROJ from the active Python environment (`sys.prefix`). You do not
need to set environment variables manually when using the `nird` conda env.

Check the resolved paths on any machine:

```powershell
micromamba activate nird
python -c "from nird.geo_runtime import get_geo_runtime_status; print(get_geo_runtime_status())"
```

PowerShell launchers dot-source [`scripts/lib/nird_geo_env.ps1`](../scripts/lib/nird_geo_env.ps1)
to apply the same settings before calling Python.

## New machine checklist

1. Create the environment: `micromamba env create -f environment.yaml`
2. Install the package: `pip install -e .`
3. Point [`config.json`](../config.json) at your local `soge_clusters` data bundle
4. Verify geo runtime: `python -c "from nird.geo_runtime import get_geo_runtime_status; print(get_geo_runtime_status())"`
5. If hazard rasters were copied from another PC, normalize CRS tags:

```powershell
python scripts/normalize_hazard_crs.py --input-dir <base_path>/inputs/test_141node_50m --in-place
```

6. Run Script 2 smoke:

```powershell
python scripts/2_intersection_analysis.py 30 1
```

## Symptoms and fixes

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `GDAL_DATA is not defined` | Python launched outside `nird` env | Use env `python.exe` or dot-source `nird_geo_env.ps1` |
| Raster CRS shows `LOCAL_CS[...US National Atlas...]` | GDAL wrote alias tags on another machine | Run `scripts/normalize_hazard_crs.py` or regenerate toy hazards |
| Script 2 exit `-1066598273` | Native snail crash from CRS/grid mismatch | Normalize rasters; check log for `geo_grid ... grid_crs=EPSG:2163` |
| Prefilter count ≈ full network | Raster bounds/CRS do not overlap links | Inspect `rasterio.open(path).crs` and `.bounds` |
| `Could not transform raster extent` | Genuinely different CRS (e.g. WGS84 tile) | `geo_runtime` will warp raster chips; verify `warped=true` in logs |

## Tools

| Tool | Purpose |
| --- | --- |
| `nird.geo_runtime` | Portable GDAL/PROJ bootstrap, CRS canonicalization, snail-safe grids |
| `scripts/normalize_hazard_crs.py` | Rewrite hazard GeoTIFF CRS to EPSG:2163 (metadata-only or warp) |
| `scripts/generate_va_toy_hazard.py` | Create toy VA hazards with authoritative EPSG tags |

## Script 2 log markers

A healthy CONUS toy run should include lines like:

```text
Using GDAL_DATA: ...
Using PROJ_DATA: ...
Raster extent prefilter for va_hazard_...tif: 483599 -> <candidate_count> road links
geo_grid raster_crs=... feature_crs=EPSG:2163 grid_crs=EPSG:2163 warped=false links=...
Script 2 COMPLETE
```

The candidate count should be far below the full FAF5 link count when the hazard covers
a state-sized area.

## Related notes

- Raster-extent prefilter handoff: [`HANDOFF_CONUS_SCRIPT2_PREFILTER_20260601.md`](../HANDOFF_CONUS_SCRIPT2_PREFILTER_20260601.md)
- Input assumptions: [`docs/assumptions_inputs/README.md`](assumptions_inputs/README.md)
