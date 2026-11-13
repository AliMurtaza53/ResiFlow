# Sioux Falls all-hazards suite: findings (Hopper job 3708666, 2026-11-13)

## Goal and method
Run the production Scripts 1 to 4 on Sioux Falls for 6 hazards (flood surface, river, coastal, earthquake, landslide, winter storm) x 6 events (0 miss, 1 bridge, 3 disconnect, 4 low, 5 high, 6 extreme) x 6 variants (`default` toy one-row recovery table; `recovery_fast|average|slow` real T26 schedules; `winter_region_high|low` T34 region). 156 cells, all `ok`, 3h05m, exit 0. Data: `docs/testbed_suite/results_2026-11-13/multihazard_inspection.csv` (one row per cell) and `recovery_timeseries.csv` (cost per event day). Inspector: `scripts/diagnostics/inspect_multihazard_sioux_falls.py`. Ladder peaks are placeholders (`testbed_synthetic_hazards.intensity_ladder`).

## What populates now
| Hazard | Closures | Direct cost | Rerouting / isolation |
|---|---|---|---|
| Flood (surface, river, coastal) | events 1, 3, 5, 6 (event 4 = 0.2 m slows only) | $4M to $373M | day 0 only, zero from day 30 on, identical across fast/average/slow |
| Winter storm | events 5, 6 (260, 450 mm) | tiny ($0.00001M to $0.03M) | isolation at day 0; persists to day 110 (average) |
| Landslide | none | $0.2M to $302M | yes (events 5, 6), persists to day 110 (average), 45 (fast), 342 (slow) |
| Earthquake | none | $0.01M to $31.5M (bridges only) | none in any cell |

## Findings (each needs an owner decision or a trace; nothing was changed)
1. **Winter storm picks up the T26 capacity schedule.** `scripts/4_rerouting_and_recovery_scenario_loop.py` (lines 1102-1131) applies `road_recovery_dict`/`bridge_recovery_dict` by `damage_level_max` to every hazard. With the real T26 tables, winter event 6 still has rerouting cost 3,845.70 at days 60, 90 and 98 (average) although T34 reopens every link within 7 days (`max_day_open` 7 at event 6); under `fast` it is zero by day 30. The same value, 3,845.70, appears for landslide event 6. So winter recovery looks double-governed (T34/T35 and T26). Confirm intent against `docs/WINTER_STORM.md`. The production default (`use_table_recovery_design` false) uses the bundle's `recovery design_updated.csv`, which has the same shape, so a real winter run may carry the same issue.
2. **Earthquake never disrupts flow.** Bridges are damaged and priced (up to $31.5M at 1.2 g) but no cell has a cost matrix. Disrupted OD pairs are selected by closed links (`max_speed <= 0`, line 1172) and earthquake speeds are reduced, never zero; T26 capacity cuts alone do not create candidates, so Script 4 prints "No flooded od pairs" and skips. Decide whether a complete-damage bridge should close at day 0.
3. **Landslide has rerouting without a closure** (`links_closed` 0, rerouting nonzero at events 5 and 6), so some path other than `max_speed == 0` creates candidates. Trace it before relying on landslide rerouting.
4. **Flood recovery does not depend on the T26 scenario.** fast, average and slow give identical flood rows (day 0 cost, then zero). Flood reopening is governed by T27, so the T26 variants test only landslide and winter. A flood recovery sensitivity needs a T27 variant.
5. **River versus surface at 0.2 m:** river prices two bridges ($4.07M) at 0.2 m; surface and coastal price $0. Probably a curve difference; check `flood_categorical` thresholds before reading river results.
6. **Only day 0 changes for floods; recovery over time shows only where capacity (T26) or day_open (T34) is used.** Winter region changes `max_day_open` as designed (event 6: high 4, moderate 7, low 11 days), yet the day-0 cost is identical across regions, because the cost matrix only samples day 0 in the winter-region variants (toy table).

## Not done
Anaheim; the results-bundle writer and self-check (spec sections 5 and 6); invariants 6 and 8 (replacement-value cap, flow conservation) are not yet checked by code.
