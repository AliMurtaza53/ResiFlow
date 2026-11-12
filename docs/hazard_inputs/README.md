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

## Decisions (2026-11-12)
- **New Madrid:** keep `bssc2014newmadrid_32_m7p5_se`; sensitivity options (`_33_`, `_31_`, FEMA M7.7) documented in the `sensitivity_run_option` column.
- **Cascadia:** keep the median map; 16th/84th percentile sensitivity documented the same way.
- **Winter storms:** pending a check (see the `decision` column).

## Open items (2026-11-12)
- **New Madrid scenario choice:** the aligned layer is exactly USGS `bssc2014newmadrid_32_m7p5_se` (M7.5, hypocenter -89.62/36.45, depth 15.6 km; verified pixel for pixel, percent g confirmed). The other BSSC2014 variants are `_31_` (M7.3, 36.93N) and `_33_` (M7.5, 35.83N, near Memphis); the FEMA `nm19fema_m7p7_mt_se` is a separate M7.7 southern-fault scenario. All four raster packs are local. Pick one deliberately; results depend on hypocenter.
- **Harvey deep tail:** 29% of valid pixels exceed 3 m and the maximum is 45.3 m after the feet-to-metres conversion; inspect in GIS for water bodies.
- **Winter storms:** units and georeferencing are consistent with the NSIDC guide (product 1036, integer mm, per-file header). Each storm is ONE daily snapshot of total snow depth, so it includes seasonal snowpack; a storm-increase raster (window maximum minus a pre-storm baseline) has not been built.
- **Cascadia:** the median map is in use; USGS also publishes 2nd/16th/84th/98th percentile maps as a sensitivity band.
- **Aligned grid:** 50 m for every layer except winter storms (1 km); only the floods have native data finer than 50 m.
