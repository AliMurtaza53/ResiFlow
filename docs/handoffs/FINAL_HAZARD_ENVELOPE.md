# Final run envelope: 4 hazards x 2 events (2026-11-18)

## Goal
One clean baseline for each demand case (freight F, passenger P, combined F+P), then Stages 2-4 for each hazard event on each case. 3 cases x (1 baseline + 8 events) = 27 jobs.

## Events (owner decision 2026-11-18)
Manifest: `parameters/hazards.final_envelope.json` (point `RESIFLOW_HAZARDS_MANIFEST` at it). Scenario numbers are the existing keys, unchanged.

| Hazard | Scenario | Event | Raster dir under `inputs/multihazard_aligned/` |
|---|---|---|---|
| Flood | 304 | Harvey (Houston) | `flood_harvey_houston` |
| Flood | 305 | Sandy (Northeast) | `flood_sandy_northeast` |
| Earthquake | 403 | New Madrid M7.5 | `earthquake_new_madrid_m75_scenario` (+ `_sa1p0`, `_liquefaction`) |
| Earthquake | 404 | Cascadia M9 | `earthquake_cascadia_m9_scenario` (+ `_sa1p0`) |
| Landslide | 503 | New Madrid co-seismic (new) | `landslide_new_madrid_m75` |
| Landslide | 502 | Cascadia co-seismic | `landslide_cascadia_m9` |
| Winter | 601 | Jonas | `winter_storm` |
| Winter | 603 | Elliott | `winter_storm_elliott` |

## New: New Madrid co-seismic landslide (503)
Built locally 2026-11-18, same recipe as Cascadia (502):
1. `scripts/align_hazard_rasters.py --input inputs/multihazard_raw/landslide/n10_susc/n10_conus.tif --reference inputs/multihazard_aligned/earthquake_new_madrid_m75_scenario/event_1.tif --output inputs/multihazard_aligned/landslide_susceptibility_new_madrid/event_1.tif`
2. `scripts/compute_landslide_pgd.py --susceptibility <above> --pga inputs/multihazard_aligned/earthquake_new_madrid_m75_scenario/event_1.tif --output inputs/multihazard_aligned/landslide_new_madrid_m75/event_1.tif --magnitude 7.5 --susceptibility-max-count 81`

Result: 30,484 x 29,855 grid at 50 m (EPSG:9311), 734M valid pixels, 2.70M nonzero (0.37% of valid), PGD 0.29 mm to 4,990 mm (about 5 m). Plausible next to Cascadia (up to 10.9 m at M9).
Caveats: magnitude 7.5 follows the registry label; the raw folder holds three BSSC2014 variants (one M7.3, two M7.5), and the PGA raster's exact variant is not recorded here. The susceptibility class mapping uses the project's existing 0-81 equal-width binning, not re-verified against USGS n10 documentation. Output is local only; it must be copied to Hopper before 503 can run there.

## Run order and gates
1. Baselines F, P, F+P on the frozen commit and final network (gate: Codex C+S/C+S+G close-out).
2. Stage 2-4 per event per case; P uses `RESIFLOW_DEMAND_CASE=passenger`, F `freight`, F+P `combined`.
3. Pre-run fixes must be merged first (see `PAX_STRUCTURAL_ISOLATION_TRACE.md` for the split-OD rebuild with `--network-links`). Sensitivities (PCE 1.5/2.5, 2 m bridge clearance, winter depth floor, isolation experiments, T26 fast/slow) are held until after this envelope.
4. Every Hopper/Anvil job is profiled per stage; Anvil readiness is checked at run time.

## Open
- The Cascadia, Sandy and Elliott code paths live on `perf/hopper-realize-paths-streaming-fix` (ledger: deferred) and must be merged or rebased onto the frozen commit.
- Copy the 503 raster to Hopper (needs owner go-ahead).
