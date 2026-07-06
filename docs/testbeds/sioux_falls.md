# Sioux Falls pipeline testbed

TNTP Sioux Falls network upcast into the FAF5-compatible schema. Runs scripts 1–4
end-to-end on a real 24-node topology without CONUS-scale data.

## Topology

- **24 nodes**, **76 directed links** (`sf_*` node IDs)
- **5 bridge pairs** (10 directed bridge links)
- **Flooded bottleneck**: physical pair 10–15 (2 directed links)
- **Reroute gain**: physical pair 11–14

## Configuration

| Field | Value |
|-------|-------|
| Results variant | `toy_sioux_falls` |
| Demand scale | `DEMAND_SCALE = 0.3` on TNTP trips |
| Freight share | 9% of scaled passenger demand |
| Capacity | Per-link TNTP `flow_cap_plph` (not flat toy cap) |
| Hazard | 10 m grid; depth > 0 only on bridge 10–15 interior |
| CRS | EPSG:4326 source → EPSG:9311 pipeline outputs |

Fixture: [`tests/sioux_falls_fixtures.py`](../../tests/sioux_falls_fixtures.py).

Static data: [`tests/data/sioux_falls_tntp/`](../../tests/data/sioux_falls_tntp/).

## Key assertions

- E2E pipeline completes (scripts 1–4)
- Exactly **2 flooded / 2 closed** links (bridge 10–15 both directions)
- Passenger and freight disrupted flow > 0, within scaled demand bounds
- Direct damage < $50M (KUSD testbed scale)
- Post-reroute passenger flow on flooded bridge < 0; gain on edge 11–14 > 0
- TNTP coordinates match vendored bstabler GeoJSON

## Run

```powershell
pytest tests/test_sioux_falls_pipeline_disruptions.py -v --basetemp ".pytest-tmp"
```

Single E2E test only:

```powershell
pytest tests/test_sioux_falls_pipeline_disruptions.py::test_sioux_falls_pipeline_scripts_reroute_bridge_bottleneck -v --basetemp ".pytest-tmp"
```

## Scenario QA

```powershell
$env:NIRD_RESULTS_ROOT = ".pytest-tmp/test_sioux_falls_pipeline_scri0/results"
$env:NIRD_RESULTS_VARIANT = "toy_sioux_falls"
$env:NIRD_TESTBED = "1"
python scripts/summarize_scenario_run.py
```

Visual QA: [`scripts/visualizations/visualize_scenario_qa.ipynb`](../../scripts/visualizations/visualize_scenario_qa.ipynb).

## Outputs

```text
{tmp}/results/
  base_scenario/toy_sioux_falls/edge_flows.gpq
  disruption_analysis/toy_sioux_falls/30/links/road_links_1.gpq
  damage_analysis/toy_sioux_falls/intersections_1_with_damage_values.csv
  rerouting_analysis/toy_sioux_falls/30/1/
```

See also the legacy doc [`docs/sioux_falls_testbed.md`](../sioux_falls_testbed.md) (kept for backward links).
