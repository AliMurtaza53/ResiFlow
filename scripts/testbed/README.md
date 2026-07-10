# Sioux Falls multihazard synthetic rasters

Generator: `generate_synthetic_hazards.py`

All rasters use **EPSG:9311** (Sioux Falls pipeline CRS). Flood depths are in
**meters**; snow/winter-storm and landslide use **mm**; earthquake uses **PGA (g)**.

## Event keys (shared across hazard types)

| Key | Purpose |
|-----|---------|
| `0` | **Miss** — Gaussian hotspot 50 km outside network extent; expects zero disrupted links |
| `1` | **Bridge bottleneck** — targets physical pair 10–15 (or equivalent localized hotspot) |
| `3` | **Disconnect stress** — broader corridor or regional field to stress isolation / rerouting |

## Hazard fields

| Folder | Unit | Peak (design) | Generator summary |
|--------|------|---------------|-------------------|
| `flood_surface` | m depth | 0.50 | bridge_interior (evt 1); Gaussians/corridors otherwise |
| `flood_river` | m depth | 0.48 | Gaussian centered near node 10 (evt 1) |
| `flood_coastal` | m depth | 0.55 | Gaussian near node 20 (evt 1) |
| `earthquake` | g (PGA) | 0.45 | Radial decay from epicenter near node 10 |
| `landslide` | mm displacement | 180 | Narrow corridor (25 m) along nodes 6–8 for evt 3 |
| `winter_storm` | mm ice/snow | 120 | Regional `snow_band` for evt 3; bridge_interior for evt 1 |

Values marked **PLACEHOLDER** in the generator should be confirmed with the advisor.

## Usage

```powershell
python scripts/testbed/generate_synthetic_hazards.py --output-dir .pytest-tmp/my_toy_data
```

Outputs:

```text
<output-dir>/inputs/sioux_falls_multihazard/
  manifest.json
  flood_surface/event_{0,1,3}.tif
  flood_river/...
  flood_coastal/...
  earthquake/...
  landslide/...
  winter_storm/...
```

Set `RESIFLOW_RESULTS_VARIANT=toy_sioux_falls_multihazard` when running the pipeline.
