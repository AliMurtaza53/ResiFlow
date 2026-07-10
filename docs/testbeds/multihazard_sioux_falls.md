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

| Hazard | `RESIFLOW_HAZARD_TYPE` | `RESIFLOW_FLOOD_SUBTYPE` | `scenario_param` (Script 2 arg 1) | `closure_threshold` |
|--------|------------------------|--------------------------|-----------------------------------|---------------------|
| Flood surface | (default) | `flood_surface` | `301` | `30` cm |
| Flood river | (default) | `flood_river` | `302` | `30` cm |
| Flood coastal | (default) | `flood_coastal` | `303` | `30` cm |
| Earthquake | `earthquake` | — | `401` | `25` |
| Landslide | `landslide` | — | `501` | `100` mm |
| Winter storm | `winter_storm` | — | `601` | `100` mm |
| Snow (legacy) | `snow` | — | `701` | `150` mm |

Unique `scenario_param` values prevent output collisions under
`disruption_analysis/`, `damage_analysis/<scenario_param>/`, and
`rerouting_analysis/`. CONUS runs use the same registry via `hazards.json`
(see `parameters/hazards.example.json`).

## Placeholders

Fragility thresholds marked `# PLACEHOLDER — confirm with advisor` in source files.
Script 3 still applies flood-style depth curves via intensity shims for non-flood hazards (v1).

**Coastal flood categorical damage (scenario 303):** vectorized thresholds in
`src/resiflow/fragility/flood_categorical.py` mirror the scalar coastal branch
(major FAF: 40/90/180/500 cm; minor FAF: 30/80/150/400 cm). These are
assumed until advisor-confirmed coastal fragility curves are available.

## Multihazard visualization

Panel results are written outside pytest's temp folder so they survive test runs.

```powershell
python scripts/testbed/run_multihazard_sioux_falls.py
# default output: results/multihazard_panel/
```

Then open `scripts/visualizations/visualize_scenario_qa.ipynb`, set:

```python
os.environ["NIRD_RESULTS_ROOT"] = "./results/multihazard_panel/results"
os.environ["NIRD_RESULTS_VARIANT"] = "toy_sioux_falls_multihazard"
```

Run the **Multihazard cost comparison** cells at the bottom for the 2×3 panel chart.

Or summarize from the CLI:

```powershell
python scripts/summarize_scenario_run.py --multihazard `
  --results-root results/multihazard_panel/results `
  --variant toy_sioux_falls_multihazard
```

**Do not** store panel results under `.pytest-tmp/` — `pytest --basetemp .pytest-tmp` deletes that tree.

## Mock HAZUS benchmark (RQ1 stub)

```powershell
python scripts/testbed/compare_mock_hazus_benchmark.py `
  --benchmark-csv tests/data/multihazard/mock_hazus_benchmark.csv `
  --variant toy_sioux_falls_multihazard
```
