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
| Earthquake | USGS ShakeMap, 2011 Mineral VA M5.8 | ~1.85km (1 arcmin), EPSG:4326 (assumed, no `.prj` in source)‡, **PGA in g** (converted from ShakeMap's native ln(g)) | Single real event (no native RP) | Real, single historical event | Grid doesn't reach VA's westernmost ~0.68° (west of -83.0°, the Bristol/Cumberland Gap corner) — 96.6% of the VA bbox covered vs. 58.0% for the retired NSHM source. Superseded default 2026-08-03; NSHM 2023 (contour-rasterized, `hazard_output_CONUS.zip` 404s on ScienceBase) still available at `scenario_param=402` / `hazard_subtype=earthquake_nshm` |
| Winter storm | NOAA SNODAS (G02158), 2016-01-23 | ~1km, EPSG:4326, meters→**mm** | Historical severe day (Winter Storm Jonas peak) | Real, single historical event (no native RP) | Snow depth used as ice/closure proxy — shimmed fragility, not a validated snow-specific curve |
| Landslide | USGS n10 susceptibility (Slope-Relief Threshold model) + NSHM PGA above | 90m native (n10), EPSG:4269 | HAZUS PGD at M=5.8 (2011 Mineral, VA — real historical CVSZ event) | **Derived**: HAZUS Newmark PGD (Eq. 4-14/4-15, Table 4-16, digitized Fig. 4-13) computed from susceptibility + PGA, not a raw source | n10 is a continuous 0–81 "susceptible sub-cell count," equal-width-binned into HAZUS None/I–X — a documented modeling choice, not a physical crosswalk |

All four aligned to the common grid via `scripts/align_hazard_rasters.py`; landslide's
derived PGD raster comes from `scripts/compute_landslide_pgd.py`
(`src/resiflow/hazards/landslide_pgd.py` has the full HAZUS methodology).

‡ ShakeMap raster downloads (`.flt`/`.hdr` ESRI BIL grids) don't ship a `.prj`;
EPSG:4326 is USGS ShakeMap's standard product CRS but is an assumption here, not
read from the file itself.

## Resolved: earthquake default switched to real ShakeMap PGA (2026-08-03)

User supplied two new raw hazard rasters for evaluation: `Harvey_Depths_3m_Final.gdb.zip`
(Hurricane Harvey flood depths) and `M5_8_ShakeMap_raster.zip` (USGS ShakeMap for the
2011 Mineral, VA M5.8 event). Evaluated both before wiring anything in:

**Harvey**: inspected via GDAL's `/vsizip/` (39GB zip, ~84GB uncompressed at 3m
resolution, 150074×140878 pixels). Bounds: lon [-97.88, -93.53], lat [27.44, 31.52]
(EPSG:4269) — the greater Houston/Texas Gulf Coast area. **Zero spatial overlap**
with the VA bbox (lon [-83.68, -74.90], lat [36.60, 38.71]) — this is fundamentally
a different region's data and cannot serve as a VA flood default. Not wired in;
blocked pending the user clarifying intended use (a separate case-study region? a
different comparison entirely?).

**Mineral ShakeMap**: real USGS product (`.flt`/`.hdr` mean+std grids for
MMI/PGA/PGV/PSA@0.3,1.0,3.0s). Two things needed resolving before use:
1. **Units**: ShakeMap's `_mean` grids for PGA/PSA are natural-log(g), not linear g
   (confirmed via USGS's own `shakelib.gmice.gmice` docs: "Ground motion amplitude;
   natural log units; g for PGA and PSA"), matching the raw data being all-negative.
   MMI is on its own linear scale (not log-transformed) — confirmed by its raw
   values already sitting on MMI's normal ~1-10 range.
   `scripts/prepare_shakemap_pga.py` (new) does the `exp()` conversion before
   `align_hazard_rasters.py`'s linear-only `--unit-scale` can be applied.
2. **CRS**: no `.prj` in the download; assumed EPSG:4326 (ShakeMap's standard),
   flagged as an assumption rather than silently baked in.

Descriptive stats (raw, `ln(g)` → linear g): mean PGA 0.0085g, range
[0.0008g, 0.6393g] across the full ShakeMap grid; after alignment to the common
50m/EPSG:9311/VA-bbox grid, 96.6% valid coverage (vs. 58.0% for the retired NSHM
source), mean 0.0184g, median 0.0107g, max 0.6385g. Compared against the retired
NSHM 2023 source (mean 0.0627g, median 0.0550g, max 0.1850g): ShakeMap has a much
higher peak but lower mean — expected, since it's a real single-event deterministic
snapshot (sharp peak near the Mineral epicenter, decaying with distance) rather than
NSHM's smoothed, probabilistic 475yr-return-period hazard averaged over all possible
sources. This also makes it the more coherent choice: landslide's HAZUS PGD
calculation already frames its scenario as "M=5.8, 2011 Mineral, VA — real historical
CVSZ event" (see table above), so a real event-specific PGA snapshot matches that
framing better than a long-term probabilistic layer did.

**Wiring**: `RealEarthquakeShakeMapSource` (`src/resiflow/hazards/real_va.py`) is now
the default for `hazard_type=earthquake` (scenario_param 401, unchanged) via
`resolve_real_source()`, generalized to key non-flood hazards by `hazard_subtype` the
same way flood's three subtypes already work. The old NSHM source
(`RealEarthquakeSource`) is preserved, reachable at the new `scenario_param=402`
(`hazard_subtype=earthquake_nshm` in `scenario_registry.py`) or by setting
`RESIFLOW_EARTHQUAKE_SUBTYPE=earthquake_nshm`. `compute_landslide_pgd.py` takes
`--pga` as an explicit CLI path (not auto-resolved), so this switch does **not**
silently change landslide's existing PGD numbers — those still read
`inputs/va_multihazard_aligned/earthquake/event_1.tif` (the NSHM raster, left in
place) unless someone explicitly re-points `--pga` at the new ShakeMap raster, which
would itself be a reasonable follow-up (the landslide scenario's own framing already
assumes the Mineral event specifically) but wasn't done here since it would change
already-established landslide numbers.

Verified: `resolve_real_source()` returns the correct class for all three cases
(default, explicit `earthquake_shakemap_mineral`, explicit `earthquake_nshm`);
pytest stayed at 103 passed / 3 skipped.

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

## Resolved: per-hazard-event odpfc re-explode replaced with a one-time index (2026-08-01)

Even after the Pass B fix, `load_odpfc_source`'s replacement query (`CROSS JOIN
UNNEST(path)`) has to touch every edge of every one of the baseline's ~9.68M paths
to find matches, regardless of how many damaged edges it's matching against — and
it was doing that explode from scratch **per hazard event** (up to 4x). A
1-damaged-edge hazard got far enough to hit an OOM (128GB single-allocation, fixed
separately) before finishing; a 95-damaged-edge hazard (earthquake) ran 6+ hours
without finishing at all under the same query. The real fix wasn't another query
tweak — it was recognizing the explode only needs to happen **once per baseline**,
not once per hazard.

`scripts/build_odpfc_edge_index.py` builds a persistent `(e_id, od_id)` index,
streamed to parquet in a single pass. (First attempt chunked this by `od_id`
range for visible progress, which backfired: the `WHERE` filter didn't push
down through `CROSS JOIN UNNEST`, so every chunk re-exploded the entire table --
confirmed on Hopper as ~83 min/chunk, ~20 days projected across 346 chunks.
Fixed by dropping chunking entirely; see the script's docstring.)
`load_odpfc_source` checks for `<baseline_variant>/odpfc_edge_index/` first and
does a cheap filtered lookup against it if present (no UNNEST at query time);
falls back to the direct explode only if no index exists (toy baselines
unaffected). Run `experiments/va_multihazard/hopper/submit_build_edge_index.slurm`
once per baseline variant before `submit_run_multihazard.slurm`.

## Open: direct-cost source

**Direct costs** (Script 3) currently price all four hazards off the same flood-only
depth-damage-ratio curve (`damage_curves/damage_ratio_road_flood.xlsx`) — a known
shim. Real HAZUS unit-repair-cost tables per hazard are the intended real source;
needs the exact published figures from the user (same "supply the table, don't
invent" pattern as landslide's HAZUS PGD coefficients), not yet started.

## Resolved: freight-by-industry breakdown now uses each hazard's real commodity mix (2026-08-03)

The freight-industry panel (advisor ask, 2026-07-31) originally applied a flat
national SCTG-G5 proxy (`SCTG_NATIONAL_SHARES`, from `faf5_sctg_daily_trucks.csv`)
identically to every hazard, just rescaled by that hazard's own freight total. Since
the shape was identical across hazards, the panel differed from the direct-vs-
indirect panel only by a scalar and carried no information beyond it (flagged when
reviewing the rendered mockup).

**Fix:** `scripts/compute_freight_industry_mix.py` (new) joins Script 4's own
disrupted freight OD pairs — the *same* candidate set that produces that event's
`rerouting_cost_freight_usd` — against `faf5_od_matrix_by_sctg.pq` on
`(origin_node, destination_node)`, and sums that matrix's `Car21` by `sctgG5` over
just those disrupted pairs. This works because `faf5_od_matrix_by_sctg.pq`'s `Car21`
is a true partition of the base `faf5_od_matrix.pq`'s `Car21`: verified locally that
summing the 5 `sctgG5` groups reproduces the base file's `Car21` exactly (zero
difference) for all ~9.77M OD pairs — so weighting by the disrupted pairs' `Car21`
correctly attributes commodity shares of the flow that is actually being rerouted,
not an independent estimate.

Deliberately reuses (via `importlib`, not duplication) Script 4's own
`load_odpfc_source` / `load_path_index_disrupted_candidates` / candidate-source
fallback resolution / `overlay_assignment_flows`, so the OD pairs joined are
identical to what Script 4 used for the cost this panel decomposes. Run once per
hazard event, after that event's Script 4 run, writing
`rerouting_analysis/<variant>/<scenario_param>/<event_id>/freight_industry_mix.json`
— now wired into `run_conus_va_multihazard.py`'s per-event loop automatically.
`load_freight_industry_mix()` (`viz_data_loaders.py`) reads these back into
`plot_freight_industry_breakdown()`'s `industry_shares` param; hazards without a
completed run still fall back to the national proxy individually, so a partially-
finished multihazard run renders without erroring.

Verified end-to-end (not just unit-tested) against a real local baseline
(`results_variant=revision`, scenario_param=30, event_id=1, 124 damaged edges, 368
disrupted freight OD pairs): produced real shares (Ag/fish/forestry 36.3%, Manuf.
goods 37.7%, Mixed & other 14.1%, Petroleum & coal 5.5%, Mining 6.4%) visibly
different in shape from the national proxy (23.4% / 26.8% / 12.8% / 16.0% / 21.0%
respectively) — confirming the join is sensitive to each event's actual disrupted
corridors rather than reproducing the flat proxy.

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
- **2026-08-03**: Wired real per-hazard freight commodity mixes (see "Resolved"
  section above) -- `scripts/compute_freight_industry_mix.py` joins Script 4's
  disrupted freight OD pairs against `faf5_od_matrix_by_sctg.pq`, now run
  automatically per event by `run_conus_va_multihazard.py`. Verified end-to-end
  against a real local baseline; pytest stayed at 103 passed / 3 skipped.
- **2026-08-03**: Evaluated two new raw hazard rasters (see "Resolved: earthquake
  default switched to real ShakeMap PGA" above). Wired the real 2011 Mineral, VA
  ShakeMap PGA in as the new earthquake default (`scenario_param=401`), retiring
  NSHM 2023 to `scenario_param=402` (still fully runnable). Hurricane Harvey's flood
  depth raster evaluated and found to have zero spatial overlap with the VA bbox
  (Houston/Texas Gulf Coast, not VA) -- not wired in, blocked on user clarifying
  intended use.
