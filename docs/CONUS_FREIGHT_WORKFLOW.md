# CONUS Freight Workflow

This workflow uses `config.json` as the single source for the active base path.
For the CONUS freight run it should point to:

```json
{
  "paths": {
    "soge_clusters": "D:\\NIRD_Data\\soge_clusters",
    "base_path": "D:\\NIRD_Data\\soge_clusters",
    "output_path": "results"
  }
}
```

## Required Input Layout

All numbered scripts read from the same base path:

```text
D:\NIRD_Data\soge_clusters
  census_datasets\
    faf5_od_matrix.pq
  networks\faf5\
    faf5_road_links.gpq
    faf5_road_nodes.gpq
  parameters\
    flow_breakpoint_dict.json
    flow_cap_plph_dict.json
    free_flow_speed_dict.json
    min_speed_cap.json
    urban_speed_cap.json
  inputs\test_141node_50m\
    va_hazard_class50_141node_base.tif
    va_hazard_class50_141node_low.tif
    va_hazard_class50_141node_high.tif
```

The VA toy hazard rasters are intentionally reused for the temporary CONUS run.
Script 2 detects these rasters and runs toy hazard mode for event keys:

- `1`: base
- `2`: low
- `3`: high

## Setup

Run this before a new CONUS freight workflow:

```powershell
.\scripts\setup_conus_freight_workflow.ps1 -InstallFreightOd -CopyToyHazards
```

The setup script creates/validates the folder structure, copies the
assignment-ready freight OD into `census_datasets\faf5_od_matrix.pq`, copies the
VA toy hazard rasters, and writes:

```text
D:\NIRD_Data\soge_clusters\tables\conus_freight_workflow_manifest.json
```

## Running In A Visible Terminal

Use the launcher so progress is visible in a PowerShell window:

```powershell
.\scripts\launch_conus_freight_workflow_terminal.ps1 -DepthKey 30 -EventKeys 1,2,3 -NumChunks 20 -NumCpu 1
```

To include both Script 5 sensitivity scripts:

```powershell
.\scripts\launch_conus_freight_workflow_terminal.ps1 -DepthKey 30 -EventKeys 1,2,3 -RunSensitivity
```

For a faster temporary CONUS smoke run, cap Script 1 to one assignment
iteration:

```powershell
.\scripts\launch_conus_freight_workflow_terminal.ps1 -DepthKey 30 -EventKeys 1,2,3 -NumChunks 20 -NumCpu 1 -MaxFlowIterations 1 -RunSensitivity
```

Script 1 tuning knobs exposed by the launcher:

- `-MaxFlowIterations 1`: one all-or-nothing assignment pass. Use `0` for the
  full iterative capacity-feedback run.
- `-ShortestPathDestBatch 0`: solve one origin to all destinations in one igraph
  call. Use a positive value only if memory errors occur.
- `-FlowDbBatchSize 100000`: number of OD path rows inserted into DuckDB per
  batch. Larger values reduce write frequency but use more RAM.
- `-BaselineDbPath <path>`: optional location for Script 1's `baseline.duckdb`.
  Put this on the fastest drive with enough free space if `D:` is a hard drive.

`scripts\2_int_analysis.py` is kept as an alternate Script 2 path. It is not run
by default to avoid duplicate intersection outputs. Add `-RunAlternateScript2`
only when deliberately comparing that older path.

## Primary Numbered Sequence

The default numbered workflow runs:

1. `scripts/1_network_flow_model_revision.py`
2. `scripts/2_intersection_analysis.py` for event keys `1,2,3`
3. `scripts/3_damage_analysis.py`
4. `scripts/3_postprocess_damage.py`
5. `scripts/4_rerouting_and_recovery_scenario_loop.py` for event keys `1,2,3`

With `-RunSensitivity`, it also runs:

6. `scripts/5_sensitivity_analysis_direct.py`
7. `scripts/5_sensitivity_analysis_indirect.py`

All step logs are written under the repository `logs\` folder.
