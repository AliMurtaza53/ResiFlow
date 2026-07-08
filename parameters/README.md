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

## Pipeline integration

`resiflow.networks.normalize_network_links()` adds:

- `network_source`, `network_class`, `assignment_tier`, `damage_profile`
- `combined_label` (legacy alias for Script 4 / older outputs)

Used by Script 1 (baseline assignment), disruption build (merge from base
scenario), and Script 4 (rerouting breakpoints).
