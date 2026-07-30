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

## Known limitation: Pass B is not warm-started (2026-07-30)

`run_conus_va_multihazard.py`'s Pass B step (re-solving the network under each
hazard's damaged edges) is **not** the cheap "only re-solve affected candidates"
operation earlier comments in this repo described. `NIRD_BASELINE_PATH_OUTPUT_MODE=
event_candidates` only filters what gets *written* after routing; the LCP dispatch
and OD-path realization still cold-start over the **entire** CONUS demand, needing
roughly as many iterations to converge as Pass A itself (confirmed on Hopper:
~35-40 min/iteration at cpu8, hit a 4-hour SLURM limit mid-iteration-3).

For this pass, Pass B is bounded to **5 iterations** (`--pass-b-max-iterations`,
default in `run_conus_va_multihazard.py`) rather than run to full convergence —
rerouting costs in the resulting summary should be read as **directional, not
fully converged**. A proper warm-start (seed Pass B's initial edge capacity from
Pass A's converged `edge_flows`, identify only the OD pairs whose Pass-A-realized
path touches a damaged edge via `odpfc.pq`, and re-solve only that narrow subset)
is designed but not yet implemented — see the branch's commit history / ask for
the design writeup. Revisit this bound once that lands.

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
  `event_candidates` mode (missing `temp_iteration_costs` table). Discovered Pass B
  is not actually cheap (see limitation above); bounded to 5 iterations for this
  pass pending a proper warm-start implementation.
