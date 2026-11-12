# Hazard input summary (tracked)

Small, tracked summary of every hazard layer the pipeline uses or has prepared: source links, native grid, units and unit status, where the raw and aligned files are, and what is still open. The data itself is large and gitignored.

| File | Content |
|---|---|
| `hazard_raster_specs_summary.csv` | One row per aligned layer (13): native grid and resolution, unit status, value statistics, data links, raw/aligned paths (local and Hopper), prep script, open gaps |
| `hazard_raster_sources_and_units.csv` | Shorter per-hazard provenance and unit-verification sheet |
| `flood_units_source_verification.md` | Evidence that the Harvey and Sandy flood depths are in feet, and the conversion that was applied |

Regenerate after any change: `python scripts/diagnostics/update_hazard_summary.py` (idempotent; also copies the CSVs to the local mirror).

## Where the data is (local, gitignored)
Everything hazard-related lives under `inputs/multihazard_raw/` (ignored by `.gitignore`):
- `earthquake/`, `flood/`, `landslide/`, `winter_storm/`, `Harvey_CUAHSI/`, `Harvey_Depths_3m_Final.gdb`: raw and near-raw downloads
- `audit_2026-11-12/`: the audit folder, with `rasters/` (all 13 aligned layers plus the feet versions of the two floods), CRS and parameter audits, the footprints GeoPackage, and a mirror of the CSVs above
- `inputs/multihazard_aligned/` (sibling folder, also ignored): the aligned layers the local code reads

On Hopper: raw under `/scratch/akothaw/multimodal_hazard_data/inputs_raw/`, aligned under `/scratch/akothaw/multimodal_hazard_data/soge_clusters/inputs/multihazard_aligned/<layer>/event_1.tif`.

## Open items (2026-11-12)
- **New Madrid provenance:** the aligned layer (780x637 px, linear percent g, max 1.31 g) is not the `nm19fema_m7p7_mt_se` scenario that was downloaded (601x541 px, ln g, max 1.42 g). Decide which scenario is intended.
- **Harvey deep tail:** 29% of valid pixels exceed 3 m and the maximum is 45.3 m after the feet-to-metres conversion; inspect in GIS for water bodies.
- **Winter storms:** SNODAS unit scale for Uri, Elliott and Snowmageddon not confirmed; raw files are local but not read.
- **Aligned grid:** 50 m for every layer except winter storms (1 km); only the floods have native data finer than 50 m.
