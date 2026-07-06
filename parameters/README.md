# US-calibrated transport parameters (reference copies)

These JSON files are **version-controlled reference copies** of the US/HCM-calibrated
assignment parameters described in
[`docs/us_calibration_changes_20260627.md`](../docs/us_calibration_changes_20260627.md).

The numbered scripts load parameters from the **active data root** defined in
`config.json` (`paths.soge_clusters/parameters/`), which lives outside this repo.
These copies are kept here so the values are tracked in git. To apply them, copy
the JSONs into the active data root's `parameters/` folder.

Files:

- `flow_cap_plph_dict.json` — designed capacity (passenger-cars/hour/lane)
- `flow_breakpoint_dict.json` — flow at which speed begins to drop (pc/h/ln)
- `free_flow_speed_dict.json` — per-class free-flow speed (mph; fallback behind
  observed FAF5 link speeds)
- `urban_speed_cap.json` — urban speed restriction (mph)
- `min_speed_cap.json` — minimum congested speed floor (mph)
