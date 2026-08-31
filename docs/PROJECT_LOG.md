# Project Log — code, methodology, and performance findings

Living record of significant findings, fixes, and open questions that don't belong
in a single commit message or a single doc. Append newest entries at the top of each
section. For hazard *data sourcing* specifics (raster sources, resolutions, unit
conversions), see `docs/CONUS_MULTIHAZARD_METHODOLOGY.md` instead — that's the source of
truth for what feeds the pipeline; this file is the source of truth for what's been
found wrong, fixed, or left open in the code and methodology around it.

Branch: `feature/freight-passenger-shared-capacity` unless noted.

---

## Open items (check this section before reporting numbers externally)

| Item | Status | Where |
|---|---|---|
| Flood damage curves (`damage_ratio_road_flood.xlsx`, `damage_cost_road_flood.xlsx`) vs. Nandu's master spreadsheet | **Resolved (confirmed NOT applied), 2026-08-29** — see "Nandu's parameter audit" entry below. The underlying curve *values* are unchanged; only some unrelated constants (VOT/fuel/occupancy) from the same audit were adopted. | `soge_clusters/damage_curves/`, `soge_clusters/asset_costs/` on Hopper; `parameters/unified_parameters.json` |
| Winter storm (601 Jonas, 602/603/604 Uri/Elliott/Snowmageddon) | Direct damage cost methodology confirmed wrong (flood-shim, ~150-1000x too high vs. real-world Jonas estimates). 602/603/604 additionally never completed a real full-CONUS run — only stale pre-bugfix data exists on disk (2026-08-24), two live attempts since have timed out (24h, then 48h) | `docs/CONUS_MULTIHAZARD_METHODOLOGY.md`, this file's "Winter storm direct-cost methodology" entry below |
| New Madrid (403) asset-type split / freight industry mix | Not yet run — `compute_direct_damage_by_asset_type.py` / `compute_freight_industry_mix.py` never executed for scenario 403 | `results/finale_2026_08/build_finale_figures.py` |
| CPU-scaling benchmark for Script 4 | Written, updated to `streaming_arrays` (the confirmed-faster strategy, see below) but not yet run | `experiments/conus_multihazard/hopper/nandu_v1/submit_earthquake_403_cpu{16,32,64,128}_benchmark.slurm` |
| Winter storm 602/603/604 resubmission with `streaming_arrays` | SLURM scripts updated, not yet resubmitted | `experiments/conus_multihazard/hopper/nandu_v1/submit_winter_storm_60{2,3,4}.slurm` |
| Passenger rerouting at national/CONUS scale | Never run — the freight/passenger shared-capacity fix (below) is verified on the toy network only | `scripts/4_rerouting_and_recovery_scenario_loop.py` |
| Nandu's flood-cost tables (T22/T24) | Verified/sourced replacement data exists but is not wired in (`use_table_*` flags off) — see "Nandu's parameter audit" entry below | `parameters/unified_parameters.json`, Nandu's `parameter_diff_final.xlsx` |
| Fig. 3-style flow validation (modeled vs. observed) | Not started. Our OD is inter-county only, missing intra-county trips, so a direct AADT match won't be exact. Real-count sources identified for when this is picked up: MWCOG annual traffic counts (DMV area) — [layer 0](https://gis.mwcog.org/wa/rest/services/RTDC/Traffic_Counts_Annual/MapServer/0/query?outFields=*&where=1%3D1), [layer 1](https://gis.mwcog.org/wa/rest/services/RTDC/Traffic_Counts_Annual/MapServer/1/query?outFields=*&where=1%3D1); TxDOT truck volume/percent — [feature service](https://services.arcgis.com/KTcxiTD9dsQw4r7Z/arcgis/rest/services/Truck%20Volume%20and%20Percent/FeatureServer/0/query?outFields=*&where=1%3D1); TxDOT historic+current AADT — [feature service](https://services.arcgis.com/KTcxiTD9dsQw4r7Z/arcgis/rest/services/TxDOT_AADT_Annuals_\(Public_View\)/FeatureServer/0/query?outFields=*&where=1%3D1) | (future work) |

---

## Code fixes

### Investigated: `realize_paths_streaming()` per-chunk slowdown at CONUS scale — one real fix landed, two hypotheses disproven, root cause still open (2026-08-30)

Triggered by the Anvil CPU-scaling benchmark (see "Performance findings" below):
Pass A's total wall time was flat across 16-65 worker counts (~83-85 min every
time), meaning whatever dominates isn't the parallelized LCP-dispatch phase --
it's the serial, single-connection `realize_paths_streaming()` step
(`road_revised.py`, used by the `streaming_arrays` path-realization strategy).
A completed run's own per-chunk timing showed pass 1 climbing from 169.6s
(chunk 1) to 224.9s (chunk 18) across 20 chunks of identical row count --
60.6 of the ~83 total minutes.

Two hypotheses looked plausible from reading the code and were tested locally
before touching production code -- both failed to hold up:

1. **`LIMIT/OFFSET`-per-chunk pagination** (both realization passes re-query
   the same table with a growing `OFFSET` each iteration) looked like the
   classic O(n²) pagination antipattern. Tested directly: a 2M-row synthetic
   DuckDB table (same path-column shape) showed **flat** `LIMIT/OFFSET` query
   time regardless of offset (~0.17s from offset=0 to offset=1.9M) --
   contradicts the pattern of DuckDB literally re-scanning skipped rows.
   What *did* hold up: 20 separate `LIMIT/OFFSET` queries cost more in total
   (~3.4s) than one streaming read of the same data via
   `to_arrow_reader()` (~0.66s) -- real, from avoiding repeated
   query-planning/execution overhead, but a small fraction of the observed
   150-224s/chunk. **Landed**: both passes switched to a single
   `to_arrow_reader()` stream. Correctness re-confirmed (188 tests, same
   pinned golden values -- the toy fixture explicitly runs this code path via
   `NIRD_PATH_REALIZATION_STRATEGY=streaming_arrays`).

2. **`np.add.at` called once per OD row** (up to ~484k times/chunk) looked
   like the per-call-overhead antipattern numpy's own docs warn about.
   Tested directly at the real per-chunk row count (483,915): batching to
   one `np.add.at` call per chunk was **slower**, not faster (0.8x). Profiling
   the full per-row loop body (at a *corrected*, realistic path-length
   assumption -- see below) showed `np.add.at` is only ~9.5% of the loop's
   cost anyway; the four per-row `.sum()` calls (fuel/time/toll/length) plus
   `.tolist()` dominate at ~88%. A further attempt to vectorize *those* (flatten
   the chunk's paths once, grouped `np.bincount` sums, `np.split` to
   reconstruct per-row lists -- numerically verified identical to the
   original) was *also* slower (0.7x), not faster. **Reverted both attempts**;
   the original per-row loop is unchanged.

Notable correction made mid-investigation: the network's `length` field
(`faf5_road_links.gpq`) is in **feet**, not miles (median ~472ft ≈ 0.09mi/edge)
-- a real CONUS trip can plausibly span hundreds to tens of thousands of
edges, not the 5-60 initially assumed for the first (misleading) micro-benchmark.
Re-profiling at a corrected, realistic path-length distribution (lognormal,
median ~500 edges) is what surfaced the `.sum()`/`.tolist()` finding above.

**Net result**: one small, real, verified improvement landed (branch
`perf/streaming-arrays-offset-and-vectorize-fix`); the dominant real-world
cost (the bulk of that 60.6 minutes) is still unexplained by anything
reproducible in local testing -- best remaining candidates are Anvil-specific
(shared-partition filesystem/memory contention, or DuckDB's actual behavior
under the very large `NIRD_DUCKDB_MEMORY_LIMIT` settings at true 9.68M-row
scale, neither of which a local test can replicate). Next step if this is
worth pursuing further: attach a real sampling profiler (e.g. py-spy) to a
live Anvil run rather than continuing to guess-and-check locally.

### Fixed: `acc_flow` silently under-reporting flow on shared reroute segments (2026-08-29)

`network_flow_model()` accumulates additively (`road_links["acc_flow"] +=
road_links["flow"]`, `road_revised.py`) — correct for Pass A's own multi-iteration
convergence (accumulator starts at 0). Script 4's recovery loop instead seeded it as
`current_flow - disrupted_flow`, and `current_flow` is always 0 in that loop's
context. Result: an edge the new route doesn't use was stuck at a negative "flow" in
the written output; worse, an edge on *both* the old and new route (a shared
downstream segment) netted to a falsely-plausible `0.0`, silently discarding its real
rerouted flow. Confirmed via `scripts/diagnostics/validate_rerouting_physics.py` and
reproduced on the untouched freight-only default path (not specific to the
freight/passenger fix below). Does not affect aggregate dollar totals (those come
from the solver's own separate scalar returns) — confirmed by diffing the full Sioux
Falls phase0 summary field-by-field before/after; only `passenger_flooded_edge_flow`
changed. Fix, tests, and pinned-reference update: commit `87f75e1`.

### Fixed: freight/passenger double-counted shared capacity in Script 4 (2026-08-29)

Freight and passenger were each rerouted through an independent `network_flow_model`
solve, so both could see the *full* remaining post-disruption capacity on a detour
link as if the other mode's disrupted flow didn't exist. Fixed by combining them into
one demand table (reusing `combine_freight_passenger_od`, the same combination Pass A
already uses) and routing as a single solve, splitting results back out by mode:
isolation splits exactly per OD pair; rerouting cost and edge flow split
proportionally by each mode's disrupted-flow share (the solver only returns
network-wide aggregates for those without re-enabling per-path `odpfc` output, which
stays off for CONUS-scale performance). This bug was dormant — passenger rerouting
has never been run at national scale — so no previously-reported number is affected.
Commit `5feb072`; diagnostic tool added in `6258891`.

### Fixed: two shared-CSV race conditions (2026-08-2x, prior session)

`scripts/3_damage_analysis.py` and `scripts/3_postprocess_damage.py` each did a
non-atomic `to_csv()` write to a file shared across every concurrently-running hazard
job (each job's Script 3 re-walks and reprocesses every scenario's damage CSV found
on disk). Under Hopper concurrency this produced torn/partial reads, understating
`earthquake_401`'s direct damage by 393x ($12.9M vs. correct $5.08B) and
`landslide_501`'s by 9.3x ($3.98M vs. correct $37.2M). Fixed via tmp-file +
`os.replace()` (atomic on POSIX and Windows). Commits `8f8fa79`, `6a4768e`. The
finale figures already reflect the corrected values.

### Stale comments corrected (2026-08-29)

`src/resiflow/disruption/build.py`'s `build_earthquake_link_disruption` and
`build_landslide_link_disruption`, plus `scripts/3_damage_analysis.py`'s
`calculate_damage()` docstring, all still said direct damage for those two hazards
was flood-shimmed. That was true 2026-08-20 and fixed the same day by `a6b6f0b`
(real HAZUS 6.1 routing via `hazards/hazus_bridge.py`) — the comments were never
updated and were actively misleading. Corrected in `626daf8`, which also documents a
previously-unflagged finding: `flood_depth_max` (still set by all three
`build_*_link_disruption` functions) is not vestigial even where the SHIM label no
longer applies to cost — Script 4's residual-floodwater speed gates (day-2/day-3
recovery) key off it for every hazard type, which is a live, unresolved
methodological question for earthquake/landslide (no floodwater to recede).

**Pending, not yet done:** update the `duckdb_chunked_compact` references in
`experiments/conus_multihazard/hopper/nandu_v1/*.slurm` once the strategy A/B test
(above) resolves — every current SLURM script still hard-codes it, and if
`streaming_arrays` wins, those comments/configs need to change together, not be left
half-updated.

---

### Nandu's parameter audit (`parameter_diff_final.xlsx`) was only partially applied (2026-08-17 merge, confirmed 2026-08-29)

The intern's audit workbook (`OneDrive/Research/ASSIP_interns_Ali/Sensitivity Analysis
Nandu/parameter_diff_final.xlsx`) is thorough and well-sourced (USDOT BCA, FHWA NHTS,
EIA, FHWA HERS-ST, ATRI, NBI, van Ginkel et al. 2021) — it's a genuine parameter-by-
parameter audit of every UK-NIRD-inherited constant against a real US-sourced
candidate, with an explicit adoption status per row. Merged via `81bf836`
(2026-08-17), which added the *infrastructure* to switch each constant over
(`use_table_*` flags, `road_cost_scale`/`bridge_cost_scale` in
`unified_parameters.json`) but left every one of those flags at its no-op default.
Confirmed still all `false`/`1.0` today (2026-08-29), unchanged since the merge.

**What was actually adopted:** VOT ($18.50-37.20/hr by vehicle class, USDOT VTTS),
fuel price ($0.90-1.04/L), and vehicle occupancy (1.52, NHTS 2022) — these are live in
`src/resiflow/constants.py` today and correctly sourced.

**What was NOT adopted — the flood/road damage-cost tables specifically:** the
audit's own `T24_asset_costs_US` sheet states outright: *"The UK-current workbook
(damage_cost_road_flood.xlsx) is NOT in the git repo and its GBP/USD provenance is
unresolved — extract and archive it... before replacement (**top audit priority**)."*
This confirms directly what the file-timestamp evidence only suggested: the current
flood damage-ratio/cost workbooks are UK-origin with unresolved currency/price-year
provenance, exactly what the audit flagged as most urgent to fix, and it was never
done. `T24`'s own replacement road-cost figures are marked `VERIFIED` (sourced to
FHWA HERS-ST); `T22`'s damage-ratio-curve replacement (sourced to van Ginkel et al.
2021) is a `TEMPLATE_REPLACE_VALUES` — worth checking whether it's actually populated
with real numbers before flipping `use_table_damage_thresholds`, not just flipping
the flag on a still-templated sheet.

**Action, not yet taken:** decide whether to spend the (apparently modest —
infrastructure already exists) effort to flip these flags and re-verify
`damage_cost_road_flood.xlsx`/`damage_ratio_road_flood.xlsx` against `T24`/`T22`
before any external report cites direct-damage costs as US-sourced. Currently they
are not, for every hazard that goes through `calculate_damage()` (flood, and
winter_storm's shim) — earthquake/landslide are unaffected (real HAZUS 6.1 costs,
separate code path, see below).

## Methodology findings

### Winter storm direct-cost methodology: flood-shim, confirmed wrong (2026-08-29 audit)

SNODAS snow/ice depth (mm) is divided by 1000 and written into a column literally
named `flood_depth_max`, then priced by `calculate_damage()` with FEMA-style flood
depth-damage curves. No HAZUS module exists for winter storm (HAZUS's four modules
are earthquake/flood/hurricane/tsunami). Result: $498.7B direct damage for Jonas vs.
$500M-$3B in independent real-world estimates (~150-1000x too high). This is a wrong
physical process being priced, not a calibration issue — a real methodology (e.g.
state DOT snow/ice removal cost data, priority-tiered by road class/jurisdiction) is
needed, not built here. Indirect/rerouting cost for winter storm is unaffected (comes
from the real network solve). Recommendation: exclude winter storm from any
externally-reported comparison until a real cost model exists, rather than trying to
make the number visually fit.

### Earthquake/landslide direct-cost scope (2026-08-29 audit)

Confirmed real, FEMA HAZUS 6.1 Ch.7-sourced methodology (`hazards/hazus_bridge.py`,
page-image-verified against the actual PDF). Scope limits, both by design and stated
in the module's own docstrings:
- **Earthquake:** bridges only, ground-shaking (Sa(1.0s)) only. Ordinary roads get
  $0 — HAZUS's road fragility table (Table 7-5) is PGD/ground-failure-only, and this
  project has no liquefaction/ground-failure layer for earthquake (only landslide has
  Newmark PGD). This *understates* earthquake damage; it doesn't inflate it.
- **Landslide:** HAZUS's ground-failure (PGD) fragility for both bridges and roads —
  a defensible proxy since PGD is genuinely the shared mechanism, not a
  landslide-bespoke curve (HAZUS has no separate landslide module).

Any external report should state these scope limits explicitly, not just cite "real
HAZUS methodology" without qualification.

### `isolation_usd_per_day` ($50/day) is inert downstream (2026-08-29 audit)

Traced every consumer: only `scripts/4_rerouting_and_recovery_scenario_loop.py` reads
it, writing an `isolation_cost_usd` column to the per-run CSVs as a second,
independently-parameterized valuation kept alongside the primary (VOT-based)
`isolation_cost`. Neither `viz_data_loaders.py` nor `build_finale_figures.py`
reads `isolation_cost_usd` — it does not reach any reported number or visual. The
parameter file's own comment already flags it as "an open research question," not a
sourced figure — this confirms that caveat is accurate and the exposure is limited to
the raw per-run CSVs, not anything already reported.

---

## Performance findings

See `notes/perf_findings/` on branches `perf/numcpu-regression-diagnosis` (2026-07-10)
and `perf/lcp-dest-chunked-dispatch` (2026-07-13, merged into this branch's history)
for full detail. Summary, because these are easy to lose track of across branches:

1. **Multiprocessing pool overhead can make more CPUs *slower*.** NumCpu=2 was 55%
   slower than NumCpu=1 on a full CONUS Pass B run; NumCpu=4 aborted after 96+
   minutes. Root cause: pool spawn/pickle/IPC/result-shipping overhead dominates when
   per-task work is small relative to fixed costs, and large chunks of wall-clock are
   serial phases the pool can't touch anyway.
2. **Mostly fixed since**, via `PRAGMA threads={num_of_cpu}` on the DuckDB
   connections plus vectorizing two Python-loop hot spots (`cap_by_eid` lookup,
   event-edge matching) — 3-4x end-to-end speedup on a 200k-OD profiling scenario,
   byte-identical output confirmed before/after.
3. **`duckdb_chunked_compact` — the strategy every Script 4 SLURM job used through
   2026-08-29 — was explicitly benchmarked against `streaming_arrays` on Script 1's
   Pass A and abandoned as a production candidate there** (slower overall, scales
   *negatively* with CPU count, 1052s→1909s going 1→4 CPUs). That finding was never
   carried into Script 4's config until now.

   **Confirmed at Script-4/CONUS-recovery-loop scale, 2026-08-30** (job 9495350 vs.
   the existing 9471507 baseline, both earthquake/403, both 8 CPUs, only the
   strategy changed): `streaming_arrays` completed in **9h37m35s** vs.
   `duckdb_chunked_compact`'s **12h24m32s** — a **22.4% reduction**. Dollar totals
   (`rerouting_cost`, `isolation_cost`, `direct_damage_total`) matched to 10
   significant figures, differing only by floating-point noise from a different
   execution order — zero correctness cost. All production and benchmark SLURM
   scripts in `experiments/conus_multihazard/hopper/nandu_v1/` switched to
   `streaming_arrays` accordingly (2026-08-30). Already-completed hazards (301, 304,
   401, 403, 501, 601) don't need re-running for this — their numbers are
   unaffected, this only changes how fast a *future* run would go. Winter storm
   602/603/604 (never yet completed, two prior timeouts at 24h/48h) are the
   highest-value candidates to resubmit with this change; the CPU-scaling benchmark
   should also be re-run with the corrected strategy before drawing any core-count
   conclusions.
4. Run-to-run wall-clock variance up to 80% was observed and investigated — traced to
   disk I/O contention from ~105GB of accumulated experiment output on the same node
   during a benchmarking session (self-inflicted, not scheduler randomness), not to
   OD-sampling non-determinism (`apply_sample_od_n` is deterministic, confirmed by
   code read). Worth remembering when reading any single-run Hopper timing: control
   for concurrent I/O load before trusting a wall-clock delta.
