# Assumptions register

Written 2026-11-12. One place for the small modelling decisions and assumptions behind the flood, freight and testbed results.
Status: **owner** = decided by the owner (date); **default** = inherited from the model, not re-decided; **provisional** = made to proceed, to revisit; **open** = not yet decided.
"Where" says what to change. Entries marked `param` are in `parameters/unified_parameters.json` and can be overridden per run with `RESIFLOW_PARAM_OVERRIDES`; the rest live in code or data files.

## Hazard inputs
| # | Assumption | Value | Where | Status |
|---|---|---|---|---|
| H1 | Harvey and Sandy depths are feet and converted to metres | x0.3048 | `scripts/prepare_harvey_depths.py`, `prepare_sandy_depths.py` (`--unit-scale`) | owner, verified from FEMA MOTF metadata |
| H2 | Harvey cells deeper than 30 ft are water bodies and edge artifacts and are masked (NaN) | 9.144 m | `prepare_harvey_depths.py --max-depth-m` | owner 2026-11-12, after the owner's GIS inspection |
| H3 | Rasters are aligned to one grid and resampled by averaging over wet pixels | 50 m (floods, earthquakes, landslide), 1 km (winter storms) | `scripts/align_hazard_rasters.py` | default; coarse sources gain no detail at 50 m |
| H4 | All data sit in EPSG:9311 (NAD27 / US National Atlas Equal Area). The network carries the NAD83 to NAD27 shift (checked on 40 links, 0.0 m). The runtime treats 9311 as an alias of EPSG:2163 | EPSG:9311 | `src/resiflow/geo_runtime.py` | default; alias is a latent risk for a raster truly in 2163 (about 3 km off) |
| H5 | New Madrid earthquake layer | `bssc2014newmadrid_32_m7p5_se` (31, 33 and FEMA M7.7 are sensitivity options) | hazard summary CSV | owner |
| H6 | Cascadia earthquake layer | median map (16th and 84th percentile are sensitivity options) | hazard summary CSV | owner |
| H7 | Winter storm hazard is the physical SNODAS snow depth, unmodified; operational response is modelled separately (T33, T34, T35, T32) | n/a | hazard prep | owner |
| H8 | Mineral and Cascadia ShakeMap are ln(g) converted to g; New Madrid is percent g; landslide is mm (HAZUS Newmark PGD) | n/a | prep scripts | default, verified |
| H9 | **Check / sensitivity, no change made:** winter-storm damage has no minimum depth, so any snow depth above 0 is "minor" and T34 closes it for 1-2 days, although plowing starts at about 25-50 mm and most of the network (interstates, highways) is plowed quickly. Option: a floor `hazard_disruption.winter_storm_min_depth_mm` (25 or 50 mm), after measuring the share of links with 0-25 mm and 25-50 mm per storm | no floor today | `src/resiflow/fragility/winter_storm_categorical.py` (`_damage_tier`); flagged in `docs/hazard_inputs/hazard_raster_specs_summary.csv` | open, owner 2026-11-12 |
| H10 | Synthetic Sioux Falls earthquake gets a Sa(1.0 s) companion = PGA x 0.67 (HAZUS bridge cost needs Sa(1.0 s)); the ratio is from the Mineral ShakeMap peaks | 0.67 | `param` `testbed_synthetic_hazards.sa1p0_to_pga_ratio` | provisional, confirm with the advisor |

## Exposure and closure (Script 2)
| # | Assumption | Value | Where | Status |
|---|---|---|---|---|
| E1 | One depth per link = the maximum over its raster-cell pieces. One deep cell closes the whole link | max | `src/resiflow/disruption/flood.py` (`features_with_damage`) | default; owner asked it be reported, not changed |
| E2 | Closure thresholds: cars 30 cm, trucks 60 cm | 30 / 60 | `param` `hazard_disruption.flood_closure_threshold_cm`, `..._truck_cm` | default (Kramer et al. 2016) |
| E3 | Speed reduction below closure follows a quadratic in depth | exponent 2.0 | `param` `hazard_disruption.speed_depth_exponent` | default |
| E4 | Major roads (HPMS F1 to F3) have an embankment subtracted from the flood depth; surface flood 1.0 m | 1.0 m | `param` `hazard_disruption.flood_embankment_surface_m` | default, units corrected 2026-11-12 (was 100 against metres) |
| E5 | Same, for river, "flood" (observed inundation such as Harvey) and coastal | 2.0 m | `param` `hazard_disruption.flood_embankment_river_m` | owner 2026-11-12: Harvey keeps the 2.0 m value for now |
| E6 | Bridges, culverts and ramps take the depth of the ground cell under them. No deck or underpass elevation is used. Harvey-15 (job 3704490): bridges were 2,187 of 7,490 flooded links (29%), 1,718 truck-closed, $330.9M. Sensitivity switch added 2026-11-13: bridge deck clearance subtracted from bridge pieces | 0.0 m (default) | `param` `hazard_disruption.bridge_deck_clearance_m`; override file `experiments/conus_multihazard/hopper/overrides/bridge_clearance_2m_sourced.json`; job `submit_harvey15_e6_clearance.slurm` | open; default unchanged until the 2 m run is read |
| E7 | Piece lengths are measured in the equal-area projection. A geodesic length is carried beside it and checked at the end of Script 2 | `length_geodesic_m`, `length_check_<event>.json` | `src/resiflow/exposure/geodesic.py` | owner 2026-11-12 |

## Direct cost (Script 3)
| # | Assumption | Value | Where | Status |
|---|---|---|---|---|
| C1 | Flood costing is the sourced path only: T24 CP25 $/lane-mile for roads, T30 $/sq ft for bridges, Rostami construction value for tunnels. The legacy workbook path is retired | n/a | `scripts/3_damage_analysis.py`, `param` `vulnerability.use_sourced_asset_costs` (true) | owner 2026-11-12 |
| C2 | Roads are priced per raster-cell piece and summed. A bridge or tunnel is priced as a whole structure and counted once per link | n/a | `src/resiflow/damage_aggregation.py` | owner 2026-11-12 (fixes the 57x and the $500B double count) |
| C3 | Bridge deck area = `averageWidth` x `structure_length_m`; damage ratio from the HAZUS damage state by span count | n/a | `calculate_damage_sourced` | default |
| C4 | Sensitivity seams scale road and tunnel cost, and bridge cost | 1.0 / 1.0 | `param` `damage_costs.road_cost_scale`, `bridge_cost_scale` | default |
| C5 | Winter storm direct cost uses the T32 DOT regression | on | `param` `vulnerability.use_table_winter_storm_cost` | default |
| C6 | Earthquake road damage is zero by design; earthquake and landslide bridges use HAZUS | n/a | `scripts/3_damage_analysis.py` | default |
| C7 | The legacy `snow` hazard (scenarios 150 and 701, its pipeline, source and Sioux Falls test) is removed. Winter storms run only as `winter_storm` (T32 cost, T33 to T35 response). Generic helpers `snow_band` and `snow_categorical` remain | n/a | removed 2026-11-12 | owner |

## Freight and demand
| # | Assumption | Value | Where | Status |
|---|---|---|---|---|
| F1 | Truck payload is flat | 20 t/truck | OD build manifest | default; the doc says T29 by SCTG group |
| F2 | Freight OD is truck (FAF mode 1) only; air and multimodal are not included (5.0% of truck tons) | n/a | OD builder | default |
| F3 | One node per county in the OD (nearest suitable road node). FAF centroid connectors are absent from the network | n/a | OD builder | provisional; structural fix not built |
| F4 | Harvey-15 OD is subset to 15 states and counties; the whole network is kept | 15 iterations | Harvey job scripts | owner |
| F6 | Harvey-15 OD geography verified 2026-11-13: crosswalk node ids equal the corrected conterminous crosswalk for all 1,359 counties; mean straight-line haul 175 mi (FAF published 186; the scrambled OD gave 909). Corrected full-CONUS OD: 193 mi, 0 nodes missing | n/a | `scripts/diagnostics/haul_length_check.py` logic | verified |
| F5 | Passenger OD is disabled in the Harvey run | n/a | `RESIFLOW_DISABLE_PASSENGER_OD=1` | provisional; passenger centroid loading to be investigated |

## Testbeds (Sioux Falls and Anaheim)
| # | Assumption | Value | Where | Status |
|---|---|---|---|---|
| T1 | Synthetic FAF-like asset attributes are assigned; existing values are never overwritten | `synthetic_assets=True` | `src/resiflow/testbeds/assets.py` | owner |
| T2 | HPMS class from road class: motorway/freeway 1, trunk 2, primary/arterial 3, secondary 4, tertiary/collector 5, unclassified 6, local 7. NHS is classes 1 to 3 | table | `assets.py` | provisional |
| T3 | Synthetic geometry: lane width 3.65 m, bridge span 30 m, two bores per tunnel | 3.65 / 30 / 2 | `assets.py` | provisional |
| T4 | Sioux Falls is South Dakota, urban area 82252 (small urbanized); Anaheim is California, urban area 51445 | n/a | `parameters/testbeds/*.json` | provisional, checked against T39 |
| T5 | Anaheim may use pseudo-regions for state-level figures | n/a | testbed suite | owner |
| T6 | Testbed intensity ladder (events 4 low, 5 high, 6 extreme): floods 0.2 / 1.0 / 2.5 m, PGA 0.2 / 0.8 / 1.2 g, landslide 60 / 500 / 1500 mm, snow 30 / 260 / 450 mm. Placeholder test inputs chosen around each closure point, not claims about real hazard strength | see left | `param` `testbed_synthetic_hazards.intensity_ladder` | provisional, 2026-11-12 |

## How to keep this current
Add a row when a decision is made. If it can be a parameter, make it one (as E4 and E5 now are) and point the row at the key.
