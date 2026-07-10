# Sioux Falls multihazard testbed

Synthetic hazard rasters and pipeline wiring for comparing indirect rerouting
costs across hazard types on the 24-node Sioux Falls network.

## Quick start (pytest)

```powershell
pip install -e ".[dev]"
pytest tests/test_multihazard_pipeline_sioux_falls.py -v --basetemp .pytest-tmp
pytest tests/test_sioux_falls_pipeline_disruptions.py tests/test_snow_pipeline_sioux_falls.py -v --basetemp .pytest-tmp
```

## Generate rasters

```powershell
python scripts/testbed/generate_synthetic_hazards.py --output-dir <toy_data_root>
```

Set `RESIFLOW_RESULTS_VARIANT=toy_sioux_falls_multihazard`.

## Hazard env vars

| Hazard | `RESIFLOW_HAZARD_TYPE` | `RESIFLOW_FLOOD_SUBTYPE` | Script 2 arg 1 |
|--------|------------------------|--------------------------|----------------|
| Flood surface | (default) | `flood_surface` | `30` |
| Flood river | (default) | `flood_river` | `30` |
| Flood coastal | (default) | `flood_coastal` | `30` |
| Earthquake | `earthquake` | — | `25` |
| Landslide | `landslide` | — | `100` |
| Winter storm | `winter_storm` | — | `100` |
| Snow (legacy) | `snow` | — | `150` |

## Placeholders

Fragility thresholds marked `# PLACEHOLDER — confirm with advisor` in source files.
Script 3 still applies flood-style depth curves via intensity shims for non-flood hazards (v1).

## Mock HAZUS benchmark (RQ1 stub)

```powershell
python scripts/testbed/compare_mock_hazus_benchmark.py `
  --benchmark-csv tests/data/multihazard/mock_hazus_benchmark.csv `
  --variant toy_sioux_falls_multihazard
```
