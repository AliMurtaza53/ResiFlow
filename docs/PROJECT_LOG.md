# Project Log — code, methodology, and performance findings

Living record of significant findings, fixes, and open questions that don't belong
in a single commit message or a single doc. Append newest entries at the top of each
section. For hazard *data sourcing* specifics (raster sources, resolutions, unit
conversions), see `docs/VA_MULTIHAZARD_COMPARISON.md` instead — that's the source of
truth for what feeds the pipeline; this file is the source of truth for what's been
found wrong, fixed, or left open in the code and methodology around it.

Branch: `feature/freight-passenger-shared-capacity` unless noted.

---

## Open items (check this section before reporting numbers externally)

| Item | Status | Where |
|---|---|---|
| Flood damage curves (`damage_ratio_road_flood.xlsx`, `damage_cost_road_flood.xlsx`) vs. Nandu's master spreadsheet | **Unconfirmed** — both files on Hopper are timestamped 2026-07-18, predating the HAZUS bridge work (Aug 20) and New Madrid (Aug 26-27). Cannot verify content (binary xlsx, no Python execution on Hopper read-only access). Needs direct confirmation: did Nandu's update ever land in these files? | `soge_clusters/damage_curves/`, `soge_clusters/asset_costs/` on Hopper |
| Winter storm (601 Jonas, 602/603/604 Uri/Elliott/Snowmageddon) | Direct damage cost methodology confirmed wrong (flood-shim, ~150-1000x too high vs. real-world Jonas estimates). 602/603/604 additionally never completed a real full-CONUS run — only stale pre-bugfix data exists on disk (2026-08-24), two live attempts since have timed out (24h, then 48h) | `docs/VA_MULTIHAZARD_COMPARISON.md`, this file's "Winter storm direct-cost methodology" entry below |
| New Madrid (403) asset-type split / freight industry mix | Not yet run — `compute_direct_damage_by_asset_type.py` / `compute_freight_industry_mix.py` never executed for scenario 403 | `results/finale_2026_08/build_finale_figures.py` |
| Path-realization strategy A/B test (`duckdb_chunked_compact` vs `streaming_arrays`) for Script 4 | Submitted, pending result | `experiments/va_multihazard/hopper/nandu_v1/submit_earthquake_403_strategy_streaming_arrays.slurm` |
| CPU-scaling benchmark for Script 4 | Written, held pending the strategy result above (no point scaling a strategy that may already be wrong) | `experiments/va_multihazard/hopper/nandu_v1/submit_earthquake_403_cpu{16,32,64,128}_benchmark.slurm` |
| Passenger rerouting at national/CONUS scale | Never run — the freight/passenger shared-capacity fix (below) is verified on the toy network only | `scripts/4_rerouting_and_recovery_scenario_loop.py` |

---

## Code fixes

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
`experiments/va_multihazard/hopper/nandu_v1/*.slurm` once the strategy A/B test
(above) resolves — every current SLURM script still hard-codes it, and if
`streaming_arrays` wins, those comments/configs need to change together, not be left
half-updated.

---

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
3. **`duckdb_chunked_compact` — the strategy every current Script 4 SLURM job
   hard-codes — was explicitly benchmarked against the fix above and abandoned as a
   production candidate**: slower overall, and scales *negatively* with CPU count
   (1052s→1909s going 1→4 CPUs). That finding was never carried into Script 4's
   config, which still uses it today. Untested at Script-4/CONUS-recovery-loop scale
   specifically (the benchmark was on Script 1's Pass A) — hence the A/B test in
   "Open items" above, which should resolve before any CPU-scaling conclusions are
   drawn.
4. Run-to-run wall-clock variance up to 80% was observed and investigated — traced to
   disk I/O contention from ~105GB of accumulated experiment output on the same node
   during a benchmarking session (self-inflicted, not scheduler randomness), not to
   OD-sampling non-determinism (`apply_sample_od_n` is deterministic, confirmed by
   code read). Worth remembering when reading any single-run Hopper timing: control
   for concurrent I/O load before trusting a wall-clock delta.
