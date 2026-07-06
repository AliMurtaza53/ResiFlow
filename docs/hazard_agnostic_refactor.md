# Hazard-agnostic disruption refactor (Phase 0)

Design reference for extracting flood disruption from Script 2 into reusable modules,
ahead of the [ResiFlow](https://github.com/AliMurtaza53/ResiFlow) migration.

## Current flood pipeline uses three parallel transforms

| Transform | Module (Phase 0) | Output | Consumer |
|-----------|------------------|--------|----------|
| Exposure | `nird.exposure.raster_line` | `flood_depth_*` per segment | Script 2, 3 |
| Operational fragility | `nird.fragility.flood_operational` | `max_speed` | Script 4 |
| Categorical fragility | `nird.fragility.flood_categorical` | `damage_level_max` | Script 4 recovery |
| Asset damage (USD) | Script 3 | C1–C6 fractions | Summaries |

Do **not** collapse these into a single `damage_ratio → capacity` funnel for flood;
new hazards may use simpler paths when appropriate.

## LinkDisruptionRecord contract

Canonical per-link row in `nird.disruption.link_record`:

- `e_id`, `hazard_type`, `event_id`, `scenario_param`
- `intensity_primary`, `intensity_unit`
- `max_speed`, `damage_level_max`

Legacy flood columns (`flood_depth_max`, etc.) are written for Script 3/4 compatibility
via `apply_legacy_flood_columns()`.

## Frozen downstream paths

```text
results/disruption_analysis/<variant>/<depth_key>/links/road_links_<event>.gpq
results/damage_analysis/<variant>/intersections_<event>_with_damage_values.csv
```

## Package layout (Phase 0)

```text
src/nird/
  disruption/
    link_record.py    # LinkDisruptionRecord + legacy writer
    flood.py          # intersections_with_damage, features_with_damage
    pipeline.py       # run_flood_disruption (Script 2 main)
    io.py             # validate_output, first_existing
  exposure/
    raster_line.py    # snail raster ∩ linestring sampling
  fragility/
    flood_operational.py
    flood_categorical.py
```

Script 2 is a thin CLI: `run_flood_disruption(depth_key, event_key)`.

## Testbeds

See [`docs/testbeds/README.md`](testbeds/README.md). Phase 0 acceptance: all three
testbed E2E tests pass unchanged after extraction.

## ResiFlow handoff

Tag `v0.1.0-phase0-baseline` on the fork marks the transport + disruption boundary
for copying into ResiFlow. UK fragility branches and path renames are deferred to Phase 4.
