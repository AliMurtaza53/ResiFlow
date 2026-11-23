# Final run envelope: 4 hazards x 2 events (2026-11-18)

## Goal
One clean baseline for each demand case (freight F, passenger P, combined F+P), then Stages 2-4 for each hazard event on each case. 3 cases x (1 baseline + 8 events) = 27 jobs.

## Events (owner decision 2026-11-18)
Manifest: `parameters/hazards.final_envelope.json` (point `RESIFLOW_HAZARDS_MANIFEST` at it). Scenario numbers are the existing keys, unchanged.

| Hazard | Scenario | Event | Raster dir under `inputs/multihazard_aligned/` |
|---|---|---|---|
| Flood | 304 | Harvey (Houston) | `flood_harvey_houston` |
| Flood | 305 | Sandy (Northeast) | `flood_sandy_northeast` |
| Earthquake | 403 | New Madrid M7.7 southern fault (FEMA/USGS `nm19fema_m7p7_mt_se`) | `earthquake_new_madrid_m77_scenario` (+ `_sa1p0`, `_liquefaction`) |
| Earthquake | 404 | Cascadia M9 | `earthquake_cascadia_m9_scenario` (+ `_sa1p0`) |
| Landslide | 503 | New Madrid M7.7 co-seismic (new) | `landslide_new_madrid_m77` |
| Landslide | 502 | Cascadia co-seismic | `landslide_cascadia_m9` |
| Winter | 601 | Jonas | `winter_storm` |
| Winter | 603 | Elliott | `winter_storm_elliott` |

## Update 2026-11-22: New Madrid is now the M7.7 scenario (owner decision)
Rule from the owner: both New Madrid scenarios are valid, authentic USGS/FEMA products, so use the more intense one. M7.7 (`nm19fema_m7p7_mt_se`, southern fault, mean grids stored as ln g) has PGA max 1.420 g and SA(1.0 s) max 1.286 g, against 1.309 / 1.037 g for the M7.5 central-fault `bssc2014newmadrid_32_m7p5_se`. Scenarios 403 and 503 now use M7.7; the M7.5 subtypes (`earthquake_new_madrid_m75_scenario`, `landslide_new_madrid_m75`) and their rasters stay in the code and on disk as an optional sensitivity. The M7.5 sections below are kept as the record of how that variant was built.

M7.7 build (local, 2026-11-22), source `Downloads/New Madrid/M7.7-Southernfault/raster.zip`, copied to `inputs/multihazard_raw/earthquake/new_madrid_m77_scenario/`:
1. `prepare_shakemap_pga.py --zip raster.zip --layer pga_mean --units ln_g` and `--layer psa1p0_mean --units ln_g` (ln g, not percent g as in the M7.5 pack).
2. `align_hazard_rasters.py --own-bounds --resolution 50` for both: 22,018 x 20,148 cells (EPSG:9311), 363M valid pixels, PGA 0.0093 to 1.416 g.
3. Landslide: n10 susceptibility aligned with `--reference` to the M7.7 PGA, then `compute_landslide_pgd.py --magnitude 7.7 --susceptibility-max-count 81`: 4.65M nonzero pixels, PGD 0.32 mm to 7.34 m (M7.5 variant: 2.70M, 5.0 m).
4. Liquefaction companion: the same CUSEC raster as M7.5 (native EPSG:4269, independent of the PGA grid), copied to `earthquake_new_madrid_m77_scenario_liquefaction`. T31 snaps magnitude to its nearest 0.5 step, so M7.7 uses the M7.5 table row; this is a documented approximation.
Footprint note: the M7.7 grid spans lon -95 to -85, lat 31 to 40, narrower than the M7.5 grid (lon -96.5 to -81.5, lat 30.1 to 42.4); outside it, the hazard is zero.

## Hopper raster inventory (checked 2026-11-22)
The 2026-11-01 scratch purge had emptied Jonas (`winter_storm`) and dropped all winter and liquefaction companions. Restored from local copies with sizes verified: `winter_storm`, `winter_storm_{airtemp,duration,snowrate}`, `winter_storm_elliott_{airtemp,duration,snowrate}`, `earthquake_new_madrid_m75_scenario_liquefaction`; M7.7 rasters copied the same day. Sandy depths on Hopper are in metres (max 5.52 m, equal to the 17.9 ft source maximum times 0.3048).

## New: New Madrid co-seismic landslide (503), M7.5 variant (superseded by M7.7 above)
Built locally 2026-11-18, same recipe as Cascadia (502):
1. `scripts/align_hazard_rasters.py --input inputs/multihazard_raw/landslide/n10_susc/n10_conus.tif --reference inputs/multihazard_aligned/earthquake_new_madrid_m75_scenario/event_1.tif --output inputs/multihazard_aligned/landslide_susceptibility_new_madrid/event_1.tif`
2. `scripts/compute_landslide_pgd.py --susceptibility <above> --pga inputs/multihazard_aligned/earthquake_new_madrid_m75_scenario/event_1.tif --output inputs/multihazard_aligned/landslide_new_madrid_m75/event_1.tif --magnitude 7.5 --susceptibility-max-count 81`

Result: 30,484 x 29,855 grid at 50 m (EPSG:9311), 734M valid pixels, 2.70M nonzero (0.37% of valid), PGD 0.29 mm to 4,990 mm (about 5 m). Plausible next to Cascadia (up to 10.9 m at M9).
Scenario identity (confirmed 2026-11-18 against the USGS scenario API and by pixel comparison): the New Madrid PGA (403) is **bssc2014newmadrid_32_m7p5_se**, "M 7.5 Scenario Earthquake - New Madrid central fault", hypocenter 36.455N -89.622W, depth 15.6 km, PGA max 1.309 g; https://earthquake.usgs.gov/scenarios/eventpage/bssc2014newmadrid_32_m7p5_se/executive. Magnitude 7.5 is therefore right for the PGD. The owner's downloads (2026-11-18) are the `_33_` M7.5 central-fault variant (hypocenter 35.83N, PGA max 1.192 g) and the FEMA M7.7 southern-fault scenario `nm19fema_m7p7_mt_se`; both are byte-identical to packs already under `inputs/multihazard_raw/earthquake/new_madrid_scenario/` and are unused (optional sensitivities; the M7.7 pack is in ln g).
Other caveat: susceptibility classes use the project's existing 0-81 equal-width binning, not re-verified against USGS n10 documentation. The raster is copied to Hopper at `/scratch/akothaw/multimodal_hazard_data/soge_clusters/inputs/multihazard_aligned/landslide_new_madrid_m75/event_1.tif` (50,017,694 bytes, size verified); Hopper's code checkout does not yet know scenario 503 until the frozen commit is synced.

## Run order and gates
1. Baselines F, P, F+P on the frozen commit and final network (gate: Codex C+S/C+S+G close-out).
2. Stage 2-4 per event per case; P uses `RESIFLOW_DEMAND_CASE=passenger`, F `freight`, F+P `combined`.
3. Pre-run fixes must be merged first (see `PAX_STRUCTURAL_ISOLATION_TRACE.md` for the split-OD rebuild with `--network-links`). Sensitivities (PCE 1.5/2.5, 2 m bridge clearance, winter depth floor, isolation experiments, T26 fast/slow) are held until after this envelope.
4. Every Hopper/Anvil job is profiled per stage; Anvil readiness is checked at run time.

## Open
- The Cascadia, Sandy and Elliott code paths live on `perf/hopper-realize-paths-streaming-fix` (ledger: deferred) and must be merged or rebased onto the frozen commit.
