# Network and assignment parameters (reference copies)

These JSON files are **version-controlled reference copies** of transport
assignment parameters and editable network-class mappings.

Scripts load parameters from the **active data root**
(`config.json` → `paths.soge_clusters/parameters/` or `inputs/parameters/`).
Copy these files into that folder to apply them in production runs.

## Assignment profiles

- `assignment_profiles.json` — canonical tier-keyed profiles:
  - `flow_cap_plph`, `flow_breakpoint`, `free_flow_speed`, `urban_speed_cap`,
    `min_speed_cap`, `congestion_factor`
- Older data bundles may still ship per-profile JSON files (`flow_cap_plph_dict.json`,
  etc.) with UK-style keys (`M` / `A_dual` / `A_single` / `B`). When
  `assignment_profiles.json` is absent, `load_assignment_profiles()` reads those
  files and coerces keys to assignment tiers via `coerce_profile_dict`.

Assignment tiers: `freeway`, `arterial`, `collector`, `local_access`.

## Network source mappings

Editable heuristic maps from normalized `network_class` → assignment tier and
damage profile:

- `network_mapping.faf5.json` — FAF5 / ResiFlow coarse classes
- `network_mapping.osm.json` — OSM `highway` tags

Override the active source with `RESIFLOW_NETWORK_SOURCE=faf5|osm`.

## Unified scalar parameters

- `unified_parameters.json` — optional overrides for scalar (non-dict) numeric
  constants used across the pipeline: unit conversions, BPR user-equilibrium
  defaults, damage-aggregation currency scaling, FAF5 preprocessing defaults,
  hazard depth-scale/closure-threshold constants, and synthetic-testbed hazard
  peak intensities.
- Loaded via `resiflow.parameters.get_parameter(section, key, default)`. If this
  file (or a given section/key) is absent from the active data root, the caller's
  hardcoded `default` is used instead — so this file is entirely optional and
  omitting it changes nothing.
- Structure: a flat JSON object of `{"section": {"key": value, ...}, ...}` groups
  (`conversions`, `assignment_ue_bpr`, `damage_aggregation`, `preprocess`,
  `hazard_disruption`, `testbed_synthetic_hazards`). See the bundled copy in this
  directory for the current default values and exact key names.

## Pipeline integration

`resiflow.networks.normalize_network_links()` adds:

- `network_source`, `network_class`, `assignment_tier`, `damage_profile`
- `combined_label` (legacy alias for Script 4 / older outputs)

Used by Script 1 (baseline assignment), disruption build (merge from base
scenario), and Script 4 (rerouting breakpoints).
