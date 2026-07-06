# Canonical parallel testbed

Three parallel links from `n1` to `n2` with different free-flow speeds. Flooding closes
the fastest link and forces rerouting onto the middle link.

## Topology

```text
n1 ----e_fast (70 mph)----> n2
 |----e_mid  (50 mph)----> |
 |----e_slow (30 mph)----> |
```

## Configuration

| Field | Value |
|-------|-------|
| Results variant | `toy_three_parallel` |
| Flooded edge | `e_fast` |
| Reroute gain edge | `e_mid` |
| OD pair | `n1` → `n2` |
| Freight demand | 100.0 |
| Passenger demand | 30.0 |
| Capacity | `flow_cap_plph=1`, `lanes=1` → 24 veh/day |
| Hazard | Full-edge buffer raster, 200 m resolution |

Fixture: `network_spec("three_parallel")` in [`tests/toy_pipeline_fixtures.py`](../../tests/toy_pipeline_fixtures.py).

## Golden behavior (asserted exactly)

| Metric | Freight | Passenger |
|--------|---------|-----------|
| Disrupted flow | 100.0 | 30.0 |
| Reroute cost | -95.27435151515712 | 25.071499098705655 |
| Flow on gain edge (`e_mid`) | 24.0 | 24.0 |

Baseline: 24 veh on each of `e_fast`, `e_mid`, `e_slow`. Post-reroute the flooded edge
shows negative flow equal to rerouted volume.

## Run

```powershell
pytest tests/test_toy_pipeline_disruptions.py -k three_parallel -v --basetemp ".pytest-tmp"
```

## Outputs

```text
{tmp}/results/
  base_scenario/toy_three_parallel/edge_flows.gpq
  disruption_analysis/toy_three_parallel/30/links/road_links_1.gpq
  rerouting_analysis/toy_three_parallel/30/1/cost_matrix_by_scenario.csv
```
