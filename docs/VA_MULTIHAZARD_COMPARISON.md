# VA Multi-Hazard Comparison — Hazard Inventory

Living reference for the CONUS-network / VA-footprint multi-hazard cost comparison.
Update this file whenever a hazard's source, resolution, or processing changes —
it is the single source of truth for what's actually feeding the pipeline.

**Common grid:** EPSG:9311 (US National Atlas Equal Area), 50m resolution, clipped to
the VA 141-node bbox (lon [-83.68, -74.90], lat [36.60, 38.71]). Network stays
CONUS-scale (FAF5, ~9.68M-row OD); only the hazard rasters are VA-sized.

| Hazard | Source | Native res / CRS / unit | Severity tier | Real vs. derived | Key caveat |
|---|---|---|---|---|---|
| Flood (surface) | VA DCR ImageServer, `Floodplains/Depth_01pct` | ~100m, EPSG:2284, **feet** | 1% annual chance (100yr) | Real, feet→m converted | 16 artifact pixels near raw data's 200ft mask cutoff excluded (`--max-valid 195`) |
| Earthquake | USGS NSHM 2023, contour-rasterized | ~1km (0.01°), EPSG:4326, **PGA in g** | 10% in 50yr (~475yr) | Real, contour-rasterized workaround | Official gridded `hazard_output_CONUS.zip` 404s on ScienceBase; not the true uniform-hazard grid |
| Winter storm | NOAA SNODAS (G02158), 2016-01-23 | ~1km, EPSG:4326, meters→**mm** | Historical severe day (Winter Storm Jonas peak) | Real, single historical event (no native RP) | Snow depth used as ice/closure proxy — shimmed fragility, not a validated snow-specific curve |
| Landslide | USGS n10 susceptibility (Slope-Relief Threshold model) + NSHM PGA above | 90m native (n10), EPSG:4269 | HAZUS PGD at M=5.8 (2011 Mineral, VA — real historical CVSZ event) | **Derived**: HAZUS Newmark PGD (Eq. 4-14/4-15, Table 4-16, digitized Fig. 4-13) computed from susceptibility + PGA, not a raw source | n10 is a continuous 0–81 "susceptible sub-cell count," equal-width-binned into HAZUS None/I–X — a documented modeling choice, not a physical crosswalk |

All four aligned to the common grid via `scripts/align_hazard_rasters.py`; landslide's
derived PGD raster comes from `scripts/compute_landslide_pgd.py`
(`src/resiflow/hazards/landslide_pgd.py` has the full HAZUS methodology).

## Not yet split out (open question, 2026-07-27)

Flood is currently only wired as `flood_surface` (fluvial/riverine, from VA DCR's
regulatory floodplain grid). The architecture already supports `flood_river` /
`flood_coastal` as distinct subtypes (`scenario_param` 302/303) — VA DCR's same
ImageServer folder lists a `NOAA_SLR_2017` layer that could serve as a real coastal
source. Pluvial (rainfall-driven, non-riverine) has no identified real source yet —
would need new data acquisition, not just relabeling.

## Resolved: Pass B eliminated, not warm-started (2026-07-30)

`run_conus_va_multihazard.py` previously ran a "Pass B" step (Script 1 in
`event_candidates` mode) per hazard event, intended as a cheap re-solve of only the
ODs affected by that event's damaged edges. It wasn't cheap: `NIRD_BASELINE_PATH_OUTPUT_MODE=
event_candidates` only filters what gets *written* after routing — the LCP dispatch
and OD-path realization still cold-started over the **entire** CONUS demand, with no
capacity reduction applied for the damaged edge at all (confirmed on Hopper:
~35-40 min/iteration at cpu8, hit a 4-hour SLURM limit mid-iteration-3). Since it
never actually disrupted the network, Pass B was solving the exact same problem
Pass A already solved — just less converged.

**Fix: Pass B was removed entirely.** `scripts/4_rerouting_and_recovery_scenario_loop.py`
already had a fallback chain that reads candidate OD pairs directly from the Pass A
baseline's own `odpfc.pq` when no Pass-B-specific output exists — the only blocker was
`load_odpfc_source()` loading that *entire* file into memory (fine for a small toy
baseline, not a ~386GB CONUS one). Fixed to filter via a DuckDB `UNNEST`/`EXISTS`
query (same shape as the existing `path_index` fallback), so it now scans instead of
materializes. Net effect: faster (no redundant re-solve), and *more* accurate (uses
Pass A's full 18-iteration convergence rather than a bounded Pass B).

## Open: direct-cost source and freight industry breakdown

**Direct costs** (Script 3) currently price all four hazards off the same flood-only
depth-damage-ratio curve (`damage_curves/damage_ratio_road_flood.xlsx`) — a known
shim. Real HAZUS unit-repair-cost tables per hazard are the intended real source;
needs the exact published figures from the user (same "supply the table, don't
invent" pattern as landslide's HAZUS PGD coefficients), not yet started.

**Freight-by-industry breakdown** (advisor ask, 2026-07-31): real 2022 FAF5
county-level truck OD data already exists locally, tagged by SCTG-G5 commodity
group — `soge_clusters/census_datasets/faf5_od_matrix_by_sctg.pq` (40M rows, same
`origin_node`/`destination_node`/`Car21` schema the main assignment already uses,
plus an `sctgG5` tag per row) and a precomputed national summary
(`faf5_sctg_daily_trucks.csv`: Manufactured goods 26.8%, Ag/fish/forestry 23.4%,
Mining 21.0%, Petroleum & coal 16.0%, Mixed & other 12.8%). Confirmed via repo-wide
grep: **not currently referenced anywhere in `demand.py`, Script 1, or Script 4** —
the assignment/rerouting pipeline has zero commodity-level disaggregation today.
`plot_freight_industry_breakdown()` (new, `viz_data_loaders.py`) renders this using
the real national shares as a proxy, applied proportionally to each hazard's freight
total. Real per-hazard shares need Script 4's disrupted-candidate OD pairs joined
against `faf5_od_matrix_by_sctg.pq` on the shared origin/destination keys — a scoped
follow-up, not yet implemented.

## Fragility curve status

| Hazard | Status |
|---|---|
| Flood | Established, real depth-damage curves |
| Earthquake | Established (`_MAJOR_PGA`/`_MINOR_PGA`, 0.10–0.45g) |
| Winter storm | Shimmed (`_MAJOR_MM`/`_MINOR_MM` on snow depth as ice proxy) |
| Landslide | Shimmed thresholds (`_MAJOR_MM`/`_MINOR_MM`, 25–300/15–200mm), now fed by a real HAZUS PGD input instead of a rescaled susceptibility score |

## Change log

- **2026-07-27**: Initial version. All 4 hazards aligned and landslide PGD computed
  locally; CONUS Pass A baseline (bounded, 18 iterations) running on Hopper.
- **2026-07-30**: Bounded Pass A baseline finished cleanly (18 iterations,
  `edge_flows.gpq` confirmed). Fixed a real bug in `duckdb_chunked_compact` +
  `event_candidates` mode (missing `temp_iteration_costs` table), then discovered
  Pass B was redundant compute entirely and removed it -- Script 4 now reads
  candidate OD pairs directly from Pass A's own `odpfc.pq` via a scale-fixed
  fallback query (see "Resolved" section above).
- **2026-07-31**: Redesigned the cost comparison viz (`plot_multihazard_cost_panels`)
  into direct-vs-indirect and freight-vs-passenger panels with a colorblind-safe
  palette; added `plot_freight_industry_breakdown()` using real (not invented)
  national SCTG-G5 shares, pending real per-hazard wiring (see above). Published as
  a mockup preview artifact pending real Hopper results.
