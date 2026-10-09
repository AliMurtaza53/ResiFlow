# Winter storm: how it works, and why the rate-based table is not a competing estimate

Central reference for the winter-storm (and `snow`) hazard. Two parts: **(1) how the mechanism works
today**, and **(2) a methodological finding** from evaluating HCM/SHRP2-L08 rate-based factors against
the depth-based approach. Written 2026-09-25; describes the code as of that date.

**In one paragraph.** Snow depth on the ground (SNODAS, peak day) is classified into a damage level with
a depth ladder plus two gated escalators (duration, cold). Depth also sets an ambient speed cap through
the T19-winter crosswalk, which closes a link at 254 mm and above. FAF5 road class sets a plow-clearance
rank (T33) and, with the damage level, a day-of-reopening (T34). **T19 is the only operative
speed/closure mechanism.** A rate-based alternative (SHRP2-L08 speed/capacity factors) was built,
compared on four events, and set aside: it describes a different phenomenon (Section 2).

---

## 1. How winter storm works now

### 1.1 Events and inputs

| Scenario | Event | Peak day |
|---|---|---|
| 601 | Winter Storm Jonas | 2016-01-23 |
| 602 | Winter Storm Uri | 2021-02-17 |
| 603 | Winter Storm Elliott | 2022-12-24 |
| 604 | "Snowmageddon" | 2010-02-06 |

Per event, three rasters are intersected with the network (all from NOAA SNODAS / PRISM, already on disk):

| Input | Field | Source | Known limit |
|---|---|---|---|
| Snow depth (mm) | `winter_storm_mm` | SNODAS peak-day snapshot (product 1036) | One snapshot; no post-storm series |
| Duration (h) | `duration_hours` | Day-over-day SNODAS depth increases in a 3-day window | 24-h granularity: only 0 / 24 / 48 |
| Air temperature (°F) | `air_temp_F` | PRISM daily **minimum** for the peak day | Runs cold vs storm-hour temperature |

### 1.2 Flow

```
SNODAS depth + duration + temperature rasters
        │  (snail intersection, per segment; companions merged on segment keys)
        ▼
[A] Segment damage level   fragility/winter_storm_categorical.py
        │  applied in disruption/winter_storm.classify_merged_intersections
        │  (a post-merge hook: escalators need all three rasters at once)
        ▼
[B] Link aggregation       max depth, max damage level, longest duration, coldest temp per link
        ▼
[C] Ambient speed          fragility/winter_storm_speed.py   max_speed = free_flow × T19 ratio(depth)
[D] Clearance              hazards/winter_storm_clearance.py rank (T33), day_open (T34), peak flag
        ▼
road_links_<event>.gpq  ──►  Script 3 (cost)   Script 4 (rerouting)
```

**[A] Damage level (one function, shared by `winter_storm` and `snow`).** Depth-primary:

| Depth | Base tier |
|---|---|
| > 0 and < 102 mm | minor |
| 102 – < 305 mm | moderate |
| 305 – < 457 mm | extensive |
| ≥ 457 mm | severe |

Two independent one-tier escalators, **applied only when depth ≥ 102 mm** (base tier ≥ moderate):
`duration_hours ≥ 24`, and `T_factor ≥ 1.5` (air temperature ≤ 10 °F, using T32's own T_factor).
They stack and cap at severe. Below 102 mm the tier is depth-only, whatever duration or temperature say.
Missing duration or temperature never escalates. The cold escalator *is* the ice-event handling
(`T32_ice_event_assumption_note.csv` documents that choice; it is not a separate code path).
Why gated: ungated, 31–37% of sub-102 mm links on Uri and Elliott were pushed to extensive/severe purely
by duration/temperature. The ladder boundaries (102/305/457 mm) are the project's VDOT ladder; a primary
citation still needs to be attached. This deliberately does **not** reuse T32's `passes` scalar
(`MAX(depth/50, duration/3)`): MAX-blending is fine for a continuous cost but let the 0/24/48 h duration
proxy dominate a categorical tier. T32's cost formula is untouched.

**[C] Speed and closure.** `max_speed = free_flow_speed × v_ratio(depth)`, passenger-car column of
`T19_winter_speed_closure_crosswalk.csv` (linear interpolation on depth). Reference points:
1.00 at 0 mm, 0.90 at 13 mm, 0.65 at 102 mm, 0.30 at 203 mm, **0.00 from 254 mm**. `max_speed = 0` is
what Script 4 treats as closed. FAF5 ferry (41) and centroid connector (50) links are never restricted.
This replaces the retired flood-shaped quadratics (k = 100 mm / 150 mm, unsourced).

**[D] Clearance rank, day of reopening, peak flag.** Keyed on the **raw FAF5 `Class`** (`faf5_class`
column), not `road_classification` (which collapses classes T33 must tell apart: 23 → `primary`;
16/17/18/19/36/41 → `service`; 33 → `motorway`). Both columns coexist on the network parquet.

- **Rank (T33-new):** direct classes take their rank (11/12/13/16/33 → 1, 14 → 2, 15 → 5). Topology
  classes (ramps 21/22, C/D lanes 23, circles 17, turn lanes 18, access roads 19, 36) inherit the best
  (lowest) rank of any link sharing a node: undirected, repeated until stable. 169 isolated links with
  no ranked neighbour default to rank 2 (the modal rank). Classes 41 and 50 get no rank, no damage
  level, no `day_open`. **Ranks 3 and 4 have no member classes**, so T34's rank-3/4 columns are unused;
  rank 5 is 1,344 links (0.28% of the network).
- **`day_open` (T34):** looked up from damage level × rank. T34 needs a per-link snowfall-region class
  that does not exist yet, so one region applies to every link (default `moderate`; override with
  `hazard_disruption.winter_storm_snow_region`). Damage level "no" → 0; unranked → NA.
- **Peak-day closure flag:** `winter_peak_closure_flag` = rank-5 link whose *peak* depth reached 200 mm
  (passenger-car clearance). It is a one-time flag, **not** a dynamic gate: only a single peak-day depth
  snapshot exists, so a gate re-evaluated each day would either fail forever or never be re-checked. It
  marks links whose `day_open` deserves less trust; it changes nothing else.

### 1.3 Output columns (winter storm `road_links`)

`winter_storm_max_mm`, `damage_level_max`, `max_speed`, `duration_hours_max`, `air_temp_F_min`,
`faf5_class`, `clearance_rank`, `clearance_rank_source` (direct / topology / isolated_default /
excluded / unclassified), `clearance_excluded`, `day_open`, `winter_peak_closure_flag`.
Segment-level `damage_level_surface` (what Script 3/4 actually read) carries the escalated level.

### 1.4 What the downstream scripts do with it

- **Cost (Script 3).** By default winter storm still falls through to the **flood-shaped damage-curve shim**
  (confirmed 150–1000× off vs. real Jonas estimates). With `vulnerability.use_table_winter_storm_cost`
  set true, T32's DOT-regression formula (`hazards/winter_storm_cost.py`) prices direct cleanup cost
  instead. The flag is currently **false**.
- **Rerouting (Script 4).** Winter storm takes the generic (flood-style) path; only earthquake and
  landslide have special residual-speed handling. Day 1: `acc_speed = min(acc_speed, max_speed)` for every
  road, so links with `max_speed = 0` are removed (closed) that day. Days 2–3: the speed cap is gated on
  `flood_depth_max`, which for winter is depth/1000 and would need ≥ 2 m of snow, so **the speed
  restriction effectively ends after day 1**. Capacity recovery over time follows `damage_level_max`
  through the recovery table (bundle CSV, or T26 when `use_table_recovery_design` is on; T26 gives
  0 days for minor/moderate).
- **Not consumed:** `day_open` (T34) and the post-reopening speed curve (T35) are emitted / available but
  Script 4 does not read them yet.

### 1.5 Tables and code map

| Piece | File | Status |
|---|---|---|
| Speed/closure crosswalk | `parameters/tables/T19_winter_speed_closure_crosswalk.csv` | **Operative.** A crosswalk (McBride pavement states mapped onto SNODAS depth), not a sourced depth-speed curve |
| Direct cost | `T32_winter_storm_direct_cost_function.csv` | Sourced; behind `use_table_winter_storm_cost` (off) |
| Ice assumption | `T32_ice_event_assumption_note.csv` | Documentation only |
| Clearance rank | `T33_winter_storm_clearance_order_new.csv` | Operative (rank); keyed on `faf5_class` |
| Day of reopening | `T34_winter_storm_clearance_schedule.csv` | Operative for `day_open`; region defaulted |
| Post-reopening speed | `T35_winter_storm_speed_recovery.csv` | Not wired |
| Rate-based factors | `T19_alt_snowfall_rate_speed_capacity.csv` (v2) | **Discussion / analysis only** (Section 2) |

Code: `fragility/winter_storm_categorical.py`, `fragility/winter_storm_speed.py`,
`hazards/winter_storm_clearance.py`, `disruption/winter_storm.py`, `disruption/build.py`
(`build_winter_storm_link_disruption`), `disruption/pipeline_intensity.py` (`post_merge_fn`),
`preprocess/faf5_network.py` (`attach_faf5_class`), `scripts/add_faf5_class_to_network.py`.
Tests: `tests/test_winter_storm_classification.py`, `tests/test_winter_storm_rate.py`.
`T19-winter`, `T19-alt`, and `T33-new` are not yet listed in `parameters/tables/manifest.csv`.

---

## 2. Finding: rate-based speed factors are not a competing estimate of the depth-based one

### 2.1 Statement

> We evaluated the HCM/SHRP2-L08 snowfall-rate speed and capacity adjustment factors as an alternative
> to the depth-based approach. Across four historical events, the two do not estimate the same
> quantity. The rate-based factors were calibrated on freeway loop-detector data during active
> precipitation, span a narrow band (speed factors 0.81–0.94, capacity factors 0.72–0.97), and are
> defined only while snow is falling. The depth-based approach responds to snow on the ground, including
> where none is falling, and can represent closure. Correcting the unit basis (liquid-equivalent rather
> than depth) did not close the gap. We therefore treat the rate-based factors as a description of
> transient speed reduction on maintained facilities during snowfall, not as a competing estimate of
> closure-driving impairment, and use the depth-based approach as the sole operative mechanism.

### 2.2 What was compared

- **Depth-based (operative):** T19-winter speed ratio (car) at each link's peak SNODAS depth.
- **Rate-based (analysis only):** SNODAS's own 24-h snowfall accumulation (product 1025 SlL01, liquid
  equivalent, in/hr) for the same two daily windows → HCM/SHRP2-L08 intensity bin (light ≤ 0.05,
  light-medium ≤ 0.10, medium-heavy ≤ 0.50, heavy > 0.50 in/hr) → SHRP2-L08 Exhibit 36-25 speed factor
  (SAF) and capacity factor (CAF) by free-flow speed.
- **Unit basis.** The HCM/SHRP2-L08/Hranac thresholds are liquid-equivalent (ASOS/AWOS gauges measure
  liquid equivalent only). A depth-differenced rate is a different quantity: SNODAS depth per unit
  liquid equivalent measured 7.5–8.4×, consistent with ~10:1. The first comparison used the depth rate
  (a unit mismatch); the corrected one uses the liquid-equivalent rate.
- **Sampling:** per-link maximum over points every 500 m; free-flow speed proxied by posted `Speed_Limit`.
  Reproduce with `python scripts/prepare_snowfall_rate_from_nohrsc.py --overwrite-companion`
  (per-link outputs and `summary.csv` land in `results/winter_rate_comparison/`, which is gitignored).

### 2.3 Evidence (links with snow depth > 0)

| Event | Links | T19 median ratio | SAF mean | Within ±0.10 | T19 lower | T19 lower with depth-rate bins (before unit fix) |
|---|---|---|---|---|---|---|
| Jonas | 11,441 | 0.00 | 0.91 | 1.4% | 98.5% | 98.2% |
| Uri | 319,475 | 0.62 | 0.95 | 10.9% | 88.6% | 86.5% |
| Elliott | 209,841 | 0.82 | 0.96 | 28.2% | 71.4% | 66.0% |
| Snowmageddon | 240,582 | 0.63 | 0.94 | 21.5% | 77.9% | 80.1% |

Jonas's depth raster covers only a regional subset, so its row is regional. The ±0.10 tolerance is a
reporting choice, not sourced.

1. **Insensitive to the unit fix.** The bins changed enormously (medium-heavy + heavy links: Uri
   48,422 → 3, Elliott 30,191 → 0) but T19-lower moved by a few points, because SAF barely varies across
   bins (0.81–0.94) while T19 spans 0–1.
2. **Different predictors, weakly related.** Rank correlation between ground depth and liquid-equivalent
   rate across links: Jonas 0.95, Snowmageddon 0.42, Elliott 0.22, Uri 0.09. Depth is not a proxy for
   rate outside an event dominated by one big accumulation.
3. **Snow on the ground with none falling.** 33% (Uri), 40% (Elliott), 19% (Snowmageddon) of snowy links
   had no new snowfall in either window; the rate side gives them no reduction (SAF = 1.0), and T19 is
   lower on 82–89% of them. Of T19's *closed* links, 99.5% (Uri) and 98.9% (Elliott) fall in the "none"
   or "light" rate bins (Snowmageddon 64%, Jonas 13%).
4. **Range and scope.** SHRP2-L08 tops out at a 19% speed loss (SAF 0.81) and a 28% capacity loss (CAF 0.72), cannot express
   closure, and covers freeways only. About 66–67% of network links fall outside its 55–75 mph
   calibration and take the nearest column.
5. **Where they do agree:** ranking, in accumulation-dominated events. In Jonas, 8,160 of the 8,166 "heavy"
   links (depth-rate bins) are T19-closed; in Snowmageddon 91% of "heavy" links are. They agree on *where*,
   not on *how much*.

### 2.4 Interpretation, and how far it goes

**Supported by the data and source designs:** the two estimates use different predictors (ground depth vs.
precipitation rate), different populations (all classes vs. freeways), and different ranges, and the
divergence concentrates where snow is on the ground but not falling.

**An interpretation, not shown by these four events alone:** that the rate-based factors "describe
transient speed reduction on actively maintained facilities." That reading rests on how the source studies
were designed (freeway loop detectors during precipitation), not on a test here.

**Not established:** that T19 is *correct*. T19-winter is itself a crosswalk with low-confidence bins and an
unsourced truck column, and it closes every road class at 254 mm even though its own notes say closure on
plowed roads is operational rather than depth-driven. The finding justifies not blending the two; it does
not validate T19. Say "captures ground-snow impairment by construction," not "is validated."

### 2.5 Limitations of the comparison

- Daily data: a 24-h **mean** rate on two windows, against calibration on hourly gauge rates. No event
  reaches the "heavy" bin and only Jonas reaches medium-heavy (23,303 links), so the daily resolution
  compresses the rate side. A 6-hourly pull is parked; its availability and product code are unverified
  (the original spec's product code was wrong: 1034 is snow water equivalent, depth is 1036).
- **Severe-cold row (< −4 °F) not applied.** Elliott's median link temperature is −5 °F. Its factors
  (SAF 0.92–0.95, CAF 0.90–0.93) are no harsher than the light-snow row, so it would narrow the gap most for
  Elliott but cannot bridge gaps of the size seen for Jonas or Uri; not quantified. The fix is small if
  the numbers must be fully clean: sample `air_temp_F` per link and take the lower of the snow and
  severe-cold factors.
- Depth in this comparison is the aligned peak-day raster; rates come from the native SNODAS grid.
- The 1025 flux (gross snowfall) is used as the rate; differencing SWE snapshots (1034) gave similar bin
  agreement (51–76%) and is net of melt/sublimation.
- Depth differencing is viable only as a crude proxy: unit-corrected (÷10) bin agreement with the flux is
  51–72%, and 19–35% of flux-positive links show no depth gain at all.

### 2.6 Status of the rate-based code

Kept as an analysis tool, not a mechanism. `hazards/winter_storm_rate.py`, the companion-raster wiring and
`scripts/prepare_snowfall_rate_from_nohrsc.py` remain so the finding is reproducible. When the optional
`<subtype>_snowrate` raster is present the winter build adds parallel columns (`hcm_snow_intensity_bin`,
`rate_speed_factor`, `rate_cap_factor`, `t19_vs_saf`, ...); `max_speed` is never touched (tested). To keep
production runs free of any second estimate, do not install the `_snowrate` companion rasters.

---

## 3. Open items (winter storm)

1. **Closure for all classes at 254 mm** vs. T19's own note that plowed-road closure is operational, and
   the rank-5 flag-not-gate intent. Making the curve rank-aware is undecided.
2. **Every snowy link is at least "minor" and therefore `day_open ≥ 1`** (Uri: 147,985 links at exactly 1).
   A trace-depth floor is not defined.
3. **Script 4 does not consume `day_open` / T35**, and the speed restriction ends after day 1.
4. **T34 region** defaults to `moderate` everywhere.
5. VDOT ladder citation; T19 truck column; duration proxy (0/24/48 h) and tmin bias.
6. Direct cost still defaults to the flood shim (`use_table_winter_storm_cost` is off).
