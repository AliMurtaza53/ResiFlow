# Candidate event list for the advisor figures (multi-state filter), 2026-10-22

Sources: `scenario_registry.py`, `REAL_SCENARIO_SET.md`, and damaged-link footprints from Hopper (`conus_nandu_v1`, August code, so link counts are indicative only): `candidate_event_state_footprint.csv`. States = states with at least one damaged link. "Run status" = what exists on Hopper today.

| # | Hazard | Event | param | States hit (damaged links) | Run status | Note |
|---|---|---|---|---|---|---|
| 1 | Flood | Hurricane Harvey | 304 | **1** (TX, 1,812) | old run (Aug) | Footprint is Houston only; fails a multi-state filter. Keep only if "region" is allowed, or swap for another flood. |
| 2 | Flood | Hurricane Sandy | 305 | CT/NJ/NY/RI (expected, not yet measured) | wired, not run | Natural multi-state flood. |
| 3 | Earthquake | New Madrid M7.5 scenario | 403 | **6** (TN 1,471; AR 777; MO 748; KY 406; IL 190; MS 9) | old run (Aug) | Best multi-state quake; re-run on current code. |
| 4 | Earthquake | Cascadia M9 | 404 | WA/OR/CA (expected) | wired, not run | Needs Hopper prep then run. |
| 5 | Landslide | Cascadia-paired | 502 | WA/OR/CA (expected) | wired, not run | Depends on 404 PGA. |
| 6 | Landslide | New Madrid-paired | TBD | TN/AR/MO/KY (expected) | **not wired** | Needs a scenario entry, source class and run. Do not substitute 501. |
| 7 | Winter storm | Jonas (Jan 2016) | 601 | **6** (VA 8,347; WV 2,109; KY 602; MD 350; OH 114; DE 34) | current run exists | Mid-Atlantic; DE/OH are minor. |
| 8 | Winter storm | Elliott (Dec 2022) | 603 | **45** | old run (Aug) | Full-CONUS SNODAS. |
| 9 | Winter storm | Uri (Feb 2021) | 602 | **50** (26 above 1%) | old run; flagged identical to 601 in Sept export | Optional; check distinct output. |
| 10 | Winter storm | Snowmageddon (Feb 2010) | 604 | **49** | old run | Optional. |

Excluded (single state): Mineral M5.8 earthquake 401 and its landslide 501 (Virginia only), Virginia flood 301 (1 link), NSHM 402.

## Suggested sets
- **8 events (2 per hazard, matches the decided set):** Harvey 304, Sandy 305, New Madrid EQ 403, Cascadia EQ 404, Cascadia LS 502, NM LS (wire), Jonas 601, Elliott 603.
- **10 events (more states, more sensible totals):** the 8 above plus Uri 602 and Snowmageddon 604, which also gives winter storm four events. Drop Harvey from the multi-state set if the filter is strict, leaving 9.

## To make the numbers sensible
1. Runs needed on current code: all of 3, 7, 8 (+9, 10), plus 304 and the never-run 305, 404, 502, and a wired NM landslide.
2. Footprint sanity: the winter events cover most of CONUS, so "top states" will be dominated by area, not by risk. Normalize or cap the state count (top 5) in the figures.
3. Winter-storm direct damage was $499 B on the old code and $20.6 M on current code for Jonas; re-run 602-604 before using them.
4. Wait for the connector/baseline fix (only 11% of demand assigned) before quoting any rerouting or isolation cost.
