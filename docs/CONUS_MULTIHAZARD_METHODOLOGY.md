# CONUS Multi-Hazard Methodology — Hazard Inventory

Living reference for the CONUS-network multi-hazard cost comparison. Update this
file whenever a hazard's source, resolution, or processing changes — it is the
single source of truth for what's actually feeding the pipeline.

**Grid:** EPSG:9311 (US National Atlas Equal Area). The road network stays
CONUS-scale (FAF5, ~9.68M-row OD) throughout; only the hazard rasters are
region/event-sized, and each is aligned via `scripts/align_hazard_rasters.py`
onto either an explicit `--reference` raster or its own bounds (`--own-bounds`).
The original comparison set (flood_surface/earthquake/winter_storm event_1)
shares one 50m grid clipped to the VA 141-node bbox (lon [-83.68, -74.90], lat
[36.60, 38.71]) -- a holdover from this project's original VA-scoped scope, kept
as-is for those three events so they stay pixel-comparable to each other.
Later, genuinely regional/national events (Harvey/Houston, New Madrid, and the
full-CONUS SNODAS days) are each aligned via `--own-bounds` at their own
resolution instead, specifically to avoid being silently clipped to that grid.

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

## Evaluated: two new raw hazard rasters (2026-08-03)

User supplied two new raw hazard rasters for evaluation: `Harvey_Depths_3m_Final.gdb.zip`
(Hurricane Harvey flood depths) and `M5_8_ShakeMap_raster.zip` (USGS ShakeMap for the
2011 Mineral, VA M5.8 event). Evaluated both before wiring anything in -- see
"Resolved: Harvey wired in as its own case study" and "Resolved: earthquake default
switched to real ShakeMap PGA" below for what happened with each.

## Resolved: Harvey wired in as its own case study, not a VA replacement (2026-08-04)

Inspected via GDAL's `/vsizip/` (39GB zip, ~84GB uncompressed at 3m
resolution, 150074×140878 pixels). Bounds: lon [-97.88, -93.53], lat [27.44, 31.52]
(EPSG:4269) — the greater Houston/Texas Gulf Coast area. **Zero spatial overlap**
with the VA bbox (lon [-83.68, -74.90], lat [36.60, 38.71]) — this is fundamentally
a different region's data and cannot serve as a VA flood default.

Resolution: user confirmed this is intentional (it's the best-resolution defensible
flood-depth grid currently on hand; VA-specific options -- Helene south-VA high-water
marks, etc. -- are still being sourced) and asked to wire it in as its own case study
rather than force it onto VA. Since the road network stays CONUS-scale regardless of
which region's raster is used (only the hazard raster is region-sized -- true for VA
too), this is architecturally a new `flood_harvey_houston` hazard_subtype at
`scenario_param=304`, not a VA flood replacement. `RealFloodHarveyHoustonSource`
(`src/resiflow/hazards/real_events.py`) reads it once aligned.

Confirmed locally (2026-08-03) that this raster is **not tractable to process on a
laptop**: two independent attempts (a windowed 5000×5000px read, and a streaming
decimated `reproject()` straight to a 50m target using `rasterio.band()` as source,
never materializing the full array) both exceeded a 100s timeout reading live from
the zip -- the FileGDB raster's block-indexed random access is efficient against a
real on-disk directory but not against zip-compressed storage at this scale.
`scripts/prepare_harvey_depths.py` (new) does the same streaming reproject, meant to
run on Hopper against an **extracted** (unzipped) copy: reprojects directly to
EPSG:9311 at a configurable resolution (default 50m, matching VA's convention) using
`Resampling.average` (appropriate for a ~278x-by-area downsample), deriving the
target grid from the source's own bounds since no pre-existing Houston reference
raster exists. Writes straight to the `inputs/multihazard_aligned/
flood_harvey_houston/event_1.tif` convention -- running it through
`align_hazard_rasters.py` afterwards would resample a second time for no benefit,
and that script's full-array read is exactly what's infeasible at this scale.
**Not yet run** (needs the ~84GB extracted file on Hopper's scratch, not this
laptop) -- `resolve_real_source()`/registry wiring is in place and tested (returns
`None` gracefully until the aligned raster exists), but no real Harvey numbers exist
yet. Confirmed no hardcoded VA-only spatial clip would interfere: the leftover
`fairfax_study_area.gpkg` check in `SiouxFallsMultihazardSource.__init__` only
matches toy/test fixture directories, never the real `soge_clusters` base path.

## Resolved: Hurricane Sandy wired in as a second real-flood case study (2026-09-10)

User supplied 4 FEMA coastal-flood depth grids clipped to CT/NJ/NY/RI
(`ct3m0214c.tif`, `nj3m0214c.tif`, `nys3m0214c.tif`, `ri3m0214c.tif`,
under `inputs/multihazard_raw/flood/`) and asked to stitch them into one
footprint. Inspected via rasterio: all EPSG:4269, float32, ~3m/px
(dx≈3.09e-5°, matching Harvey's own ~3m convention), same nodata sentinel
(`-3.4028230607370965e+38` = `np.finfo('float32').min`), depths 0–18m
(NJ max ~17.9m). Each file is LZW-compressed and >90% nodata by area (a
rectangular state bounding box around a thin real coastal/estuary
inundation extent) — that combination is why NJ's file is ~1GB on disk
despite a raw uncompressed array of ~14.4GB (53694×67048px).

Unlike Harvey (one raster), these 4 rasters' bounding boxes genuinely
overlap along shared coastline (CT/RI, NY/NJ across the Hudson) even though
their valid (non-nodata) footprints mostly don't. `scripts/prepare_sandy_depths.py`
(new) mosaics them: streams each source individually into one destination
array via `reproject()`+`rasterio.band()` (never a full `src.read()` — same
reasoning as Harvey, necessary at NJ's raw array scale even though the file
itself is small), then averages any output pixel that gets valid data from
more than one source rather than picking one arbitrarily (confirmed locally:
only ~0.7–1.0% of valid output pixels are affected either way). The core
mosaic function (`build_sandy_mosaic`) is resolution-parameterized and
reused by both the pipeline's aligned 50m input and the comparison figures'
coarser display mosaic, so the two can't drift apart.

Wired in as its own `flood_sandy_northeast` hazard_subtype at
`scenario_param=305` — a second real-flood case study alongside Harvey
(`flood_harvey_houston`, 304), **not a replacement of it** in the pipeline;
both stay runnable. `RealFloodSandyNortheastSource`
(`src/resiflow/hazards/real_events.py`) reads the aligned output once it
exists (own-bounds grid, same reasoning as Harvey — a 4-state footprint
would be silently clipped to nothing useful against the VA reference grid
or Harvey's Houston bbox). Hopper SLURM pair mirroring Harvey's:
`submit_sandy_prep.slurm` (mosaic, ~2 min locally at 50m, so `--partition=normal`
unlike Harvey's — no extraction step needed, the 4 raw files together are
under 2GB) then `submit_sandy_305.slurm` (Script 2→3→3_postprocess→4,
`--partition=bigmem` defensively since the damaged-edge count against the
CONUS network is unmeasured, same reasoning as Harvey's 304 job).

The hazard-footprint comparison figures (`scripts/figures/plot_hazard_footprints_*.py`)
now show Sandy instead of Harvey in the flood panel — user's explicit
request, to keep the figure's story on a genuinely dense, comparison-relevant
Northeast Corridor flood event; Harvey remains a fully separate, runnable
pipeline scenario, just no longer plotted there.

## Resolved: earthquake default switched to real ShakeMap PGA (2026-08-03)

Real USGS product (`.flt`/`.hdr` mean+std grids for
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

**Wiring**: `RealEarthquakeShakeMapSource` (`src/resiflow/hazards/real_events.py`) is now
the default for `hazard_type=earthquake` (scenario_param 401, unchanged) via
`resolve_real_source()`, generalized to key non-flood hazards by `hazard_subtype` the
same way flood's three subtypes already work. The old NSHM source
(`RealEarthquakeSource`) is preserved, reachable at the new `scenario_param=402`
(`hazard_subtype=earthquake_nshm` in `scenario_registry.py`) or by setting
`RESIFLOW_EARTHQUAKE_SUBTYPE=earthquake_nshm`. `compute_landslide_pgd.py` takes
`--pga` as an explicit CLI path (not auto-resolved), so this switch does **not**
silently change landslide's existing PGD numbers — those still read
`inputs/multihazard_aligned/earthquake/event_1.tif` (the NSHM raster, left in
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

`run_conus_multihazard.py` previously ran a "Pass B" step (Script 1 in
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
unaffected). Run `experiments/conus_multihazard/hopper/submit_build_edge_index.slurm`
once per baseline variant before `submit_run_multihazard.slurm`.

## Resolved: Stage 2 row explosion for widespread hazards (2026-08-03/04)

The index fix above didn't fully solve it for hazards with a widespread
damaged-edge footprint. `winter_storm` (601): 11,556 of the CONUS network's
483K edges damaged (2.4%, from Winter Storm Jonas's real footprint plus a
25mm/~1in "minor" threshold) — over 100x earthquake's 95 damaged edges. This
OOM'd (SIGKILL, confirmed via `oom_kill` in the SLURM error log) even after
the index fix, at 8 CPU / `NIRD_DUCKDB_MEMORY_LIMIT=130GB` / `--mem=160G`.

Diagnosed by splitting `load_odpfc_source` into its two stages and timing
them separately via an interactive `srun` (not `sbatch` — watched live, same
method that found the missing `snkit` dependency): Stage 1 (`hit_od_ids`,
the distinct-`od_id` index lookup) completed cleanly in ~20 min at
production-comparable resources (8 CPU / 140GB) — not the bottleneck. Stage 2
(the old `SELECT o.* ... SEMI JOIN ... -> fetchdf()`) is what died: it pulled
**16.67 million matched rows** into one pandas DataFrame, each carrying a
`path` list column.

Root cause of why 16.67M is so much larger than the true number of disrupted
OD *pairs*: `od_id` is assigned fresh per Pass-A iteration
(`road_revised.py`'s `next_od_id_base + ROW_NUMBER()`), not a stable
per-(origin,destination) key — the same OD pair gets a new `od_id`, and can
get a genuinely different realized path, each time capacity-constrained
rerouting sends it a different way across Pass A's 18 iterations. The
existing caller (`overlay_assignment_flows`) was already deduping the result
down to one row per `(origin_node, destination_node)` — just *after* paying
the cost of materializing every iteration's copy as Python objects first.

**First fix attempt (2026-08-04), confirmed insufficient on Hopper (2026-08-05):**
pushed the dedup into SQL against `o.*` directly (`QUALIFY ROW_NUMBER() OVER
(PARTITION BY origin_node, destination_node ORDER BY od_id) = 1`). Verified
correct locally (identical row count on a baseline with no real duplication,
zero duplicate pairs in output, pytest 103/3), but **still OOM'd on the real
winter_storm job** (`120.7/121GiB used` at failure). Reducing the *output*
size doesn't reduce the *peak* memory needed to compute it: the window
function has to buffer/sort every one of the 16.67M matched rows — `path`
array included — to rank them, before `QUALIFY` can discard the losers.

**Working fix (2026-08-05):** narrow-then-widen. Rank on a projection of just
`od_id`, `origin_node`, `destination_node` — never referencing `path` at all
— so Parquet's columnar layout means that column's data is never touched
during ranking (same narrow footprint as Stage 1's `hit_od_ids`, already
proven tractable at this row count). Only *then* join the winning
(deduplicated, much smaller) `od_id` set back against the full table to fetch
complete rows. Verified locally: identical 368-row result (no-op on a
baseline with nothing to dedupe), zero duplicate pairs, pytest stayed at 103
passed / 3 skipped.

**Confirmed working on the real Hopper job (2026-08-05):** an interactive test
on the `bigmem` partition (`amd069-090`, 1TB+ RAM per `sinfo`) got
`load_odpfc_source` to complete in ~37 min with **zero OOM**, producing
1,774,874 candidate rows — down from the broken version's 16.67M, a ~9.4x
reduction, matching the iteration-repetition theory. Script 4 then proceeded
cleanly into its own internal rerouting `network_flow_model()` re-solve
(1.77M disrupted freight OD pairs), completing iteration 1 in ~32 min and
reaching 67% through iteration 2's LCP dispatch before the interactive
session's own 2h wall-clock limit (not a crash) cut it off. That re-solve's
iteration controls are `max_iterations=unbounded` (`stagnant_limit=3`), so
the true total runtime across all iterations — and however many recovery-day
scenarios follow — isn't known yet, but the memory bottleneck this whole
investigation was chasing is resolved. Resubmitted as an unattended
`sbatch` job (`experiments/conus_multihazard/hopper/submit_winter_storm_bigmem.slurm`,
24h budget, `bigmem`) rather than another timed-out interactive session.

## Root cause identified: `odpfc_edge_index` needs to be sorted by `e_id` (2026-08-09)

The two fixes above (index-based lookup, then narrow-then-widen) reduced the
*output* size of `load_odpfc_source`'s Stage 1 query, but landslide (501, only
7 damaged edges) still took ~89 minutes and up to 755GB — the same order of
magnitude as winter_storm's 11,556-edge query. That gap (tiny filter, same huge
cost) was the tell: the query's cost was never actually driven by how selective
the filter is.

**Mechanics**: `odpfc_edge_index` (built by `build_odpfc_edge_index.py`, one
streaming pass, deliberately unsorted so the explode itself pipelines without
materializing the full table) has `e_id` values scattered essentially randomly
across every row group, since the data was written in `od_id`-explosion order.
Parquet's row-group min/max statistics — the mechanism DuckDB uses to skip data
it can prove doesn't match a filter — are useless when a row group's `e_id`
range spans nearly the whole ID space. So every filtered query, regardless of
how few edges it's matching against, has to scan essentially the entire ~92.3B
row table. The filter changes the *output* size, not the *work* required to
produce it.

**Fix**: `scripts/sort_odpfc_edge_index.py` (new) re-sorts an already-built
index by `(e_id, od_id)` — kept as a separate step from the explode (not merged
into `build_odpfc_edge_index.py`) so an existing index doesn't need to be
rebuilt from scratch, and a failed/retried sort can't damage the already-proven
explode output. Secondary sort on `od_id` (suggested by the user) is nearly
free at sort time (already paying for an external sort on `e_id`) and clusters
`od_id` values within each matching row group, cheapening the downstream Stage
2 join against `odpfc.pq` as well.

**Verified locally** (2026-08-09) against a 39.2M-row toy index (from the
`revision` baseline): sorting reduced `TABLE_SCAN` rows read from 36,932,943 to
741,568 for a 7-edge filter — **~49.8x fewer rows scanned** — with byte-identical
query results (18,597 distinct `od_id` either way) confirming the sort changes
nothing except physical layout. `EXPLAIN ANALYZE` showed DuckDB attempting the
same dynamic filter (`e_id IN (...) AND e_id BETWEEN X AND Y`) against both the
sorted and unsorted files — the filter is always constructed, but can only skip
data when the file's row groups are actually sorted by that column. CONUS scale
(92.3B rows) should see proportionally more benefit, since there's more data to
skip relative to any given filter's selectivity.

Sequenced as three Hopper jobs, in order:
1. `submit_verify_edge_index_sort.slurm` — re-confirms the same result (rows
   scanned, correctness) in Hopper's own environment against a small baseline,
   before committing to the expensive real one.
2. `submit_sort_edge_index_production.slurm` — sorts the real
   `convergence_cpu8_bounded18` index (92.3B rows, ~386GB). Has pre-flight
   checks inline (confirm `bigmem`'s actual max walltime and available scratch
   space — this exact operation has never been timed at this scale, so the
   7-day budget in the script is a generous guess, not a measured requirement).
   Writes to a new directory, swapped in manually after verifying row counts
   match — no code changes needed in `4_rerouting_and_recovery_scenario_loop.py`
   either way, since it only requires `odpfc_edge_index/part_*.pq` to exist with
   `(od_id, e_id)` columns, not a particular sort order.
3. `experiments/pass_a_convergence/hopper/submit_cpu8_bounded20.slurm` — a
   modest step up (`RESIFLOW_MAX_FLOW_ITERATIONS=20`, not 18), as its own new
   `convergence_cpu8_bounded20` variant (`convergence_cpu8_bounded18` stays
   untouched and is what the current 4-hazard advisor comparison is built
   from). Not the eventual truly-unbounded convergence run — that's planned
   for Anvil once its credit exchange clears — this is a smaller,
   well-understood test using bounded18's exact proven config with only
   `RESIFLOW_MAX_FLOW_ITERATIONS`, the variant name, and memory headroom
   (128G→160G, matching the real 180GB-per-node capacity confirmed elsewhere
   this session) changed.

## Resolved: negative day0 rerouting cost -- missing isolation cost (SC) term (2026-08-09)

Earthquake (401, real ShakeMap data, `edges=103`) completed successfully but
reported a **negative** day0 rerouting cost (`rerouting_cost = -$1,104,034`,
making `combined_total_cost` negative overall -- a disruption event that looks
like it *saved* money). Persistent symptom across hazards; a previous session
already tried one fix (`consistent_baseline` in
`4_rerouting_and_recovery_scenario_loop.py`, comparing post vs. pre on the same
loaded-speed network rather than pre's stale free-flow costs) -- confirmed via
the log that this fix *did* run, and the negative number persisted anyway, so a
second, distinct cause was still present.

**Mechanics**: `network_flow_model`'s `total_cost`/`cost_time`/`cost_fuel`
(`road_revised.py`, `cList`) sum only over successfully-routed flow (the
`odpfc` table). Any OD flow that can't find a path at all goes into a separate
`isolated_od` table/`trip_isolations_*.pq` output and contributes **$0** to
`total_cost` -- tracked, but not priced. Confirmed on Hopper for earthquake
401's day0: `trip_isolations_freight_s1_day0.pq` (post/damaged network) sums to
**1,359.2** units of isolated flow, vs. **0.13** (noise) for
`..._day0_baseline.pq` (undisrupted network) -- the damaged network genuinely
disconnects ~5.7% of day0's disrupted-OD demand, and those (likely
above-average-cost, since they lost *every* path) trips are priced at $0
instead of a real cost, making the damaged network look artificially cheaper
than the undisrupted one.

**Fix, grounded in the source framework**: the codebase implements
[nismod/dafni-nird](https://github.com/nismod/dafni-nird)'s stress-testing
methodology (Li et al., *"Stress-testing road network resilience using
counterfactual flood events"*, TRD 2026 -- confirmed by reading the paper
directly). That paper keeps rerouting cost (RC, Eq. 7) and isolation cost (SC,
Eq. 8-9) as **two separate terms**, summed only in the combined total
(`IC = RC + SC`) -- RC is legitimately computed only over routed flow and was
never meant to also account for isolation; the actual gap was that Script 4's
`combined_total_cost` had no SC term at all, so isolation's real cost was
silently dropped rather than just mispriced.

Added `isolation_cost = isolated_flow_total * omega` to
`4_rerouting_and_recovery_scenario_loop.py`, where `omega` is a per-unit-flow,
per-day economic loss for unroutable flow. The paper anchors `omega` on
passenger-commuter labour-productivity loss (GBP/hr x 7hr workday); for
freight that framing doesn't transfer (a stranded truck isn't a commuter
losing wages), so `omega` reuses the existing sourced
`constants.VOT_USD_PER_HOUR["ogv"]` ($32.50/hr, USDOT-sourced truck-driver
value-of-time) x 24h/day = $780/unit-flow/day (user-selected option, over a
literal 7h-workday transplant or a fixed value-of-lost-trip figure).
`combined_total_cost` is now `rerouting_cost + isolation_cost +
direct_damage_total` (both the per-day and final aggregate computations); new
`isolated_flow_total`/`isolation_cost` columns added to the per-day and
`cost_matrix_*_by_scenario.csv` outputs. `pytest tests/` and the toy
disruption pipeline both verified passing after the change.

## Resolved: direct-cost source now uses real HAZUS 6.1 methodology for earthquake/landslide (2026-08-20)

**Background:** Direct costs (Script 3) originally priced all four hazards off
the same flood-only depth-damage-ratio curve
(`damage_curves/damage_ratio_road_flood.xlsx`) — confirmed via a real Hopper
`cost_matrix_by_scenario.csv` showing nonzero `direct_damage_total_usd` for
`earthquake_401` that traced back to `disruption/build.py`'s
`build_earthquake_link_disruption()`/`build_landslide_link_disruption()`/
`build_winter_storm_link_disruption()` each repackaging their own hazard's real
intensity (PGA×0.5, PGD_mm/1000, ice_mm/1000) into a column literally named
`flood_depth_max`, priced by `scripts/3_damage_analysis.py`'s
`calculate_damage()` (hardcoded `flood_types=["surface","river"]`, no
`hazard_type` branching at all). Every non-flood hazard's direct cost was
FLOOD repair cost applied to a relabeled non-flood intensity value, not any
hazard-specific damage function.

**Fix — the core module:** `src/resiflow/hazards/hazus_bridge.py` (new, ~570
lines) implements FEMA Hazus 6.1's Earthquake Model Technical Manual (July
2024) Ch. 7 "Direct Physical Damage to Transportation Systems" and the
Inventory Technical Manual (Aug 2024) Ch. 9 replacement-cost tables — full
28-class HWB bridge classification (Table 7-1), lognormal fragility curves for
both ground-shaking (Sa(1.0s), Table 7-6) and ground-failure (PGD, Table
7-5/7-7) axes, damage-ratio-by-state (Table 11-10), and $/km road / $/sqft
bridge replacement costs (Table 9-2/9-3). Every table was verified against the
actual FEMA PDF via page-image rendering (an earlier text-layer extraction
pass silently misaligned one table and dropped another's embedded
stacked-fraction equations). KNOWN LIMITATIONS are documented in the module's
own docstring (Kshape correction not implemented; Sa+PGD combination uses
"more severe axis governs," not HAZUS's possibly-more-nuanced combined
treatment; HWB28 falls back to HWB1's curve).

**Per-hazard status:**

| Hazard | Direct cost source | Notes |
|---|---|---|
| Flood | Real flood depth-damage curves (`damage_ratio_road_flood.xlsx`) | Always was the real source for this hazard; no shim |
| Landslide | Real HAZUS PGD (ground-failure axis only) | Bridges + roads. Committed `a6b6f0b` |
| Earthquake | Real HAZUS Sa(1.0s) (ground-shaking axis only), bridges only | Roads report $0 for earthquake — correct per HAZUS: Table 7-5's road fragility is PGD/ground-failure-only, no shaking curve, and this pipeline has no liquefaction PGD computed for earthquake (only landslide's Newmark PGD exists). Sa(1.0s) intersection wired `bde7c55` (2026-08-20) — see below |
| Winter storm | **Still the flood shim** | HAZUS has no dedicated module for this hazard at all (confirmed by the research pass) — a real cost source here would need a different data source entirely (e.g. state DOT snow/ice removal cost data), not started |

**How earthquake's Sa(1.0s) gets to the network** (closed 2026-08-20, was
deferred as too high-blast-radius the session before): earthquake sources with
a prepared Sa(1.0s) companion raster (`RealEarthquakeShakeMapSource`,
`RealEarthquakeNewMadridScenarioSource` — flagged via a new `sa1p0_companion`
class attribute on `SiouxFallsMultihazardSource`) now run a second raster
intersection pass alongside PGA, plumbed through via a `source_field` kwarg on
the three intensity-hazard `intersections_fn` callbacks
(`disruption/earthquake.py` branches on it; `landslide.py`/`winter_storm.py`
accept-and-ignore it for call-signature compatibility with the shared
`run_intensity_disruption` loop in `disruption/pipeline_intensity.py`). The
resulting `psa1p0_g` column flows through Script 3 exactly like `pga_g`/
`landslide_mm` already do — no Script 3 changes needed beyond
`compute_row_direct_damage_musd`'s earthquake branch, which reads it directly.
Verified end-to-end against the real local New Madrid Sa(1.0s) raster
(~0.12–0.14g near the epicenter) with a synthetic line GeoDataFrame, plus the
full local test suite.

**Where the tests live:** `tests/test_hazus_bridge.py` (28 tests — classification
edge cases, fragility math, cost scaling/governing-axis selection, the
`compute_row_direct_damage_musd` integration points for every hazard type).

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
— now wired into `run_conus_multihazard.py`'s per-event loop automatically.
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
  automatically per event by `run_conus_multihazard.py`. Verified end-to-end
  against a real local baseline; pytest stayed at 103 passed / 3 skipped.
- **2026-08-03**: Evaluated two new raw hazard rasters (see "Resolved: earthquake
  default switched to real ShakeMap PGA" above). Wired the real 2011 Mineral, VA
  ShakeMap PGA in as the new earthquake default (`scenario_param=401`), retiring
  NSHM 2023 to `scenario_param=402` (still fully runnable). Hurricane Harvey's flood
  depth raster evaluated and found to have zero spatial overlap with the VA bbox
  (Houston/Texas Gulf Coast, not VA).
- **2026-08-04**: Wired Harvey in as its own case study (`scenario_param=304`,
  `flood_harvey_houston`) rather than a VA flood replacement, per user direction --
  same CONUS network, region-specific raster only, same pattern VA already uses.
  `scripts/prepare_harvey_depths.py` added for the Hopper-side prep (confirmed
  locally this raster isn't tractable to process on a laptop -- see "Resolved:
  Harvey wired in" above); registry/source-class wiring tested, but no real Harvey
  numbers exist yet pending that Hopper run. Also generalized `build.py`'s flood
  block to prefer `scenario.hazard_subtype` over a possibly-stale
  `RESIFLOW_FLOOD_SUBTYPE` env var, mirroring the earthquake fix (a latent
  correctness bug: an explicit `scenario_param` could previously be silently
  overridden by a leftover env var from a prior run).
- **2026-08-04**: Diagnosed winter_storm's (601) OOM at the source, not by raising
  `--mem` again -- an interactive, timed, two-stage breakdown of
  `load_odpfc_source` (see "Resolved: Stage 2 row explosion for widespread
  hazards" above) found Stage 1 (index lookup) completes cleanly in ~20 min; Stage
  2 was pulling 16.67M rows (not OD pairs -- `od_id` recurs once per Pass-A
  iteration a pair got rerouted through) into one pandas DataFrame before its
  caller deduped it back down anyway. First fix attempt moved that dedup into SQL
  (`QUALIFY ROW_NUMBER() ... = 1` against `o.*`) -- verified locally, but this
  still OOM'd on the real Hopper job (confirmed 2026-08-05): ranking against
  full-width rows still has to buffer every `path` array to compute the ranking,
  even though the final output is small.
- **2026-08-05**: Fixed the above properly -- narrow-then-widen. Rank on just
  `od_id`/`origin_node`/`destination_node` (never touching `path`, same narrow
  footprint as Stage 1), then join the winning od_id set back for full rows.
  Verified locally (368-row no-op, zero duplicate pairs); pytest stayed at 103
  passed / 3 skipped. **Confirmed working on the real Hopper job** the same day
  (see "Resolved: Stage 2 row explosion" above): `bigmem` partition, zero OOM,
  16.67M candidate rows down to 1,774,874, Script 4 proceeded cleanly into its
  own rerouting re-solve. Resubmitted unattended via
  `submit_winter_storm_bigmem.slurm` (24h budget) since the remaining
  bottleneck is wall-clock time for an unbounded-iteration convergence loop,
  not memory.
- **2026-08-09**: Sorted `odpfc_edge_index` by `(e_id, od_id)` to fix the real
  driver of `load_odpfc_source`'s memory floor (see "Root cause identified"
  above) -- verified locally and on Hopper (~42-50x fewer rows scanned,
  identical results); production sort of the real 92.3B-row
  `convergence_cpu8_bounded18` index and the 20-iteration Pass A follow-up
  (`convergence_cpu8_bounded20`) queued as the next Hopper jobs. Also fixed a
  second, distinct negative-rerouting-cost bug: earthquake (401)'s real
  ShakeMap run completed with `rerouting_cost = -$1.1M` at day0 despite the
  earlier `consistent_baseline` fix, traced to isolated (unroutable) flow
  being priced at $0 instead of via a proper isolation-cost (SC) term -- see
  "Resolved: negative day0 rerouting cost" above.
- **2026-08-20**: Replaced the flood-shim direct-cost path with real HAZUS 6.1
  methodology for earthquake and landslide (see "Resolved: direct-cost source"
  above) -- new `src/resiflow/hazards/hazus_bridge.py` module, full 28-class
  HWB bridge fragility + PGD road fragility + replacement-cost tables. Also
  added New Madrid M7.5 scenario ShakeMap (earthquake, `scenario_param=403`)
  and 3 additional full-CONUS-extent SNODAS winter-storm days (Uri/Elliott/
  Snowmageddon, `scenario_param=602/603/604`) -- New Madrid chosen over a
  probabilistic (return-period) hazard map per methodological direction from
  Li et al. 2026's framework: a coherent single-event ShakeMap is what traffic
  can realistically reroute around, a statistical envelope isn't. Wired
  Sa(1.0s) into the earthquake raster-intersection path (previously deferred
  as high-blast-radius) so earthquake bridges now get a real Sa(1.0s)-based
  cost instead of reporting $0. Fixed a NaN-truthy bug in the new module
  caught by the existing toy pipeline test before being called done. Winter
  storm remains on the flood shim -- HAZUS has no dedicated module for it.
- **2026-09-10**: Wired Hurricane Sandy in as a second real-flood case study
  (see "Resolved: Hurricane Sandy wired in" above) -- `scenario_param=305`,
  `flood_sandy_northeast`, alongside Harvey (304, still fully runnable, not
  replaced). New `scripts/prepare_sandy_depths.py` mosaics 4 FEMA
  state-clipped depth grids (CT/NJ/NY/RI) via streaming `reproject()`, same
  approach as Harvey's prep script; `RealFloodSandyNortheastSource` added to
  `real_events.py`. Ran the mosaic locally at 50m (~2 min, 59.1M px grid,
  0.74% of valid pixels came from >1 overlapping source, averaged) to
  produce the aligned pipeline input; Hopper SLURM pair
  (`submit_sandy_prep.slurm`/`submit_sandy_305.slurm`) added but not yet run
  there. Also swapped the hazard-footprint comparison figures' flood panel
  from Harvey to Sandy per explicit user request -- both figure scripts and
  `_hazard_footprints_common.py`'s `load_harvey()` replaced with
  `load_sandy_flood()`, reusing the same `build_sandy_mosaic()` core the
  pipeline input uses, just at a coarser display resolution.
