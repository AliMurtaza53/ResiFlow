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
4. Liquefaction companion: the same CUSEC raster as M7.5 (native EPSG:4269, independent of the PGA grid), aligned (nearest neighbour, `align_hazard_rasters.py --nearest`) onto the M7.7 PGA grid as `earthquake_new_madrid_m77_scenario_liquefaction` (the raw EPSG:4269 raster makes the sampler fail with an empty window; native copies are in `inputs_raw/earthquake/liquefaction_cusec_native/`). T31 snaps magnitude to its nearest 0.5 step, so M7.7 uses the M7.5 table row; this is a documented approximation.
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

## Frozen inputs for network A (recorded 2026-11-22)
Root on Hopper: `/scratch/akothaw/multimodal_hazard_data`. The scratch purge deletes files older than 90 days, so copy these somewhere permanent before the freeze.

| Input | Path | Note |
|---|---|---|
| Network A | `stage2_scripts/connector_test1_inputs/faf5_road_links.gpq` + `connector_crosswalk.csv` | physical network + 3,795 official Class 50 connectors; recipe `scripts/diagnostics/prepare_faf_connector_pilot.py` |
| Freight OD (C+S+G) | `stage2_scripts/connector_test2_gateway_full/conus/harvey15_gateway_od.pq` | full CONUS despite the name; 11,204,772 rows, 1,510,749.556669 trucks/day; audit files alongside. **Built on a flat 20 t payload, see below** |
| Passenger OD | `stage2_scripts/passenger_A_split_20261122/` (`passenger_conus_split_od.pq`, `passenger_harvey15_split_od.pq`, `SHA256SUMS`) | job 3861097, 22 s; identical to the 2026-11-17 rebuild; weak-component guard validated against the CONUS native-network baseline `results/conus_connector_test2g_gateway/edge_flows.gpq` (343,658-node main component); Clark 55788 -> 55797 at 1.0, 55804 receives nothing; 51,718,653.894 vehicle trips/day conserved (962,743 split rows); input `inputs_passenger/passenger_cty1way_conus_od.pq` (LODES jobs 146.26M x county ACS vehicles per job, one direction, intrazonal 56.7M dropped) |

## Freight payload basis: flat 20 t vs T29 (scoping, 2026-11-22)
Finding: the freight OD lineage uses a **flat 20.0 t per truck**. The by-commodity matrix (`scratch_tests/hpms_la_challenger/isolated_base/census_datasets/faf5_od_matrix_by_sctg.pq`, 40.0M rows) implies exactly 20.000 t in every commodity group, and its total 1,735,334.7 trucks/day is the flow that became 1,510,749.556 after the conterminous correction and the intrazonal drop. T29 (FHWA-HOP-20-011 Table 52 combination-unit payloads by commodity, adopted 2026-09-23, now the code default) is therefore not in the frozen OD.

| sctgG5 | trips/day at 20 t | at T29 | T29 payload |
|---|---|---|---|
| 0109 ag, fish, forestry | 405,796 | 474,338 | 17.11 |
| 1014 mining | 364,156 | 318,318 | 22.88 |
| 1519 petroleum, coal | 278,149 | 243,244 | 22.87 |
| 2033 manufactured | 464,865 | 540,227 | 17.21 |
| 3499 mixed, other | 222,368 | 246,528 | 18.04 |
| total (12.668 billion tons/yr) | 1,735,335 | 1,822,655 | 19.39 weighted |

T29 per commodity gives **+5.03% trucks** and shifts the mix, so a single scale factor is not equivalent.

### Rebuilt on T29 (2026-11-22, owner chose the more defensible basis)
Hopper dir `stage2_scripts/payload_rebuild_20261122/` (`SHA256SUMS` there). Recipe: `scripts/diagnostics/rebuild_faf_od_payload.py` (by-commodity matrix, scale each row by 20/T29, sum by node pair, drop AK/HI and remap with `make_conterminous_od.transform_od`), then `prepare_faf_conus_subcounty_od.py` (mean weights) and `prepare_faf_gateway_pilot.py --payload-table` (the port reconstruction used a hard-coded 20 t; it now takes T29).
- **Reproduction gate:** the flat-20 path reproduces `faf5_od_matrix.pq` and `inputs_corrected/faf5_od_matrix_conterminous.pq` exactly (0 differing rows, max abs diff 0.0; job 3862714).
- **Result (jobs 3862787, 3862870):** node flow 1,822,654.59 (+5.03%); conterminous 1,816,952.04; after intrazonal removal and gateway step **1,596,299.49 trucks/day (+5.66% vs 1,510,749.56)**, 11,204,877 rows (old 11,204,772; 105 new rows, 0.006 trucks/day), zero same-node rows, no negatives.
- **Gates:** conservation 1e-9 passed in every arm; mean/zero/parent_only haul within +-2% of control (control 198.87 mi, mean 198.88). Haul versus the old OD is +3.0% (193.12 to 198.88 mi) because the commodity mix shifted toward lighter-payload, longer-haul groups; expected, not tuned.
- **Not payload-dependent, unchanged:** FAF published directional centroid totals (used for split weights and port targets). Port budgets use a published target against a 5% larger reconstructed supply, so zone fractions fall slightly.
- **Frozen freight OD for network A is now** `t29/conus/harvey15_gateway_od.pq` (sha256 af5daa34...). The old flat-20 file stays as the reference. Harvey-15 subset was not rebuilt.

## Final-code qualification (2026-11-23, code `a9ce7b3`, Hopper `code/ResiFlow_final_a9ce7b3`)
- **Tests on Hopper:** 28 passed (Toy, Sioux Falls, phase-0 and flood parity, multihazard pipeline, passenger Stage 4, UE correlation, connector-network switch). Run with no `RESIFLOW_CONFIG_PATH`: with the cluster config the toy tests load the real OD and fail. The stale legacy-costing test was removed (`55cfed9`).
- **Bug found and fixed:** the endpoint cherry-pick missed `RESIFLOW_FAF5_CONNECTOR_NETWORK` in Stage 1, Stage 3 and the intensity pipeline. A first baseline without the connectors isolated 99.6% of demand. Fixed in `a9ce7b3` with `tests/test_connector_network_switch.py`. Every run must log `initial number of edges in the network: 487237` and `Initial isolated flows: 0.0`.
- **Baselines on network A (T29 freight OD, 15 iterations max):** freight 1:17 wall, 100% delivered in one pass, 0 isolated, travel cost $484.1M. Passenger 0:56 wall, 87.4% delivered, 0 structural and 12.6% congestion isolation at iteration 15, remain 0.70%, conservation and capacity invariants held. Combined (PCE 54,911,252.9/day) is the acceptance run: still iterating at the time of writing (remain 35.6%, 28.5%, 23.6% after iterations 1 to 3, about 70 minutes each).
- **Stage 2 + 3 smoke on all eight events** (freight baseline, final OD and network; `experiments/final_envelope/`). 3,795 virtual links in every event, none exposed.

| Event | Stage 2 wall | Damage rows | Direct damage (M USD) | Note |
|---|---|---|---|---|
| 304 Harvey | 7 min | 89,439 | 11,291 | identical to the earlier virtual-exempt run |
| 305 Sandy | 12 min | 23,360 | 3,880 | |
| 403 New Madrid M7.7 | 112 min | 2,232,707 | 134,041 | PGA max 1.398 g; needed the aligned liquefaction raster |
| 404 Cascadia M9 | 43 min | 913,063 | 158,685 | |
| 503 New Madrid M7.7 landslide | 42 min | 24,402 | 29,109 | |
| 502 Cascadia landslide | 22 min | 103,571 | 348,453 | **review**: exceeds the Cascadia shaking damage |
| 601 Jonas | 66 min | 617,582 | 20.6 | |
| 603 Elliott | not logged | 805,831 | 168.7 | |

- **FAF22 agreement, freight baseline (matched road links, 483,442, all with a published value):** flat-20 t gateway baseline modeled/FAF22 trips = 1.298 (Pearson 0.584); final T29 baseline = **1.407 (Pearson 0.587)**. The excess over FAF22 rises about 11 points (+5.66% trucks, +3.0% haul, as expected) while the pattern correlation is unchanged. T29 is therefore the more defensible payload but moves the volume level further from FAF22 on this network; FHWA's disaggregation, empty-mile treatment and path choice differ, so this is reported, not tuned. Script: `scripts` copy in `stage2_scripts/faf22_cmp.py` on Hopper.
- **First envelope job end to end (freight, Harvey 304, job 3864873):** Stages 2 to 4 completed in 2:45 wall (Stage 4 2:33, 82 GB peak RSS), exit 0. Day 0 isolates 59,426 trucks/day ($53.1M), day 7 15,504 ($13.8M), none from day 14 on. Centroid pass-through audit: **0 shortcuts** over all 11,204,877 baseline paths and the Harvey day-0 and day-7 path exports.
- **Open for review:** 502 (landslide damage 2.2 times the Cascadia shaking damage on a quarter of the damage rows); Stage 2 is single-threaded and slow for the large earthquake grids (403 takes under two hours), so run events as separate jobs in parallel.
- **Anvil:** conda env `nird_v4` rebuilt (the old ones were purged; first attempt failed on a corrupted package cache, retried with a fresh one), code `ResiFlow_final_8a0cbba` synced (needs a refresh to `a9ce7b3`, jobs override with `PYTHONPATH`), frozen inputs on scratch and on `/anvil/projects/x-civ260045/frozen_inputs_networkA_20261123/`. Not yet on Anvil: hazard rasters (about 9 GB), baseline result folders.
- **Launching:** `experiments/final_envelope/baseline.slurm` (CASE=freight|passenger|combined) and `event.slurm` (CASE, EV, CODE_SHA) reproduce these runs; `event_summary.py` produces the table above.

## Run order and gates
1. Baselines F, P, F+P on the frozen commit and final network (gate: Codex C+S/C+S+G close-out).
2. Stage 2-4 per event per case; P uses `RESIFLOW_DEMAND_CASE=passenger`, F `freight`, F+P `combined`.
3. Pre-run fixes must be merged first (see `PAX_STRUCTURAL_ISOLATION_TRACE.md` for the split-OD rebuild with `--network-links`). Sensitivities (PCE 1.5/2.5, 2 m bridge clearance, winter depth floor, isolation experiments, T26 fast/slow) are held until after this envelope.
4. Every Hopper/Anvil job is profiled per stage; Anvil readiness is checked at run time.

## Open
- The Cascadia, Sandy and Elliott code paths live on `perf/hopper-realize-paths-streaming-fix` (ledger: deferred) and must be merged or rebased onto the frozen commit.
