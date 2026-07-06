# Braess testbed

Classic Braess paradox diamond network. Flooding targets the interior of `e_23` only
(partial-edge raster), closing that link while leaving detour edges open.

## Topology

```text
        e_12
    n1 -----> n2
    |  e_13   | e_24
    v         v
    n3 -----> n4
        e_34
    (diagonal e_23 connects n2–n3)
```

## Configuration

| Field | Value |
|-------|-------|
| Results variant | `toy_braess` |
| Flooded edge | `e_23` (interior only) |
| Reroute gain edge | `e_13` |
| OD pair | `n1` → `n4` |
| Freight demand | 12.0 |
| Passenger demand | 13.0 |
| Hazard | `interior_fraction=(0.35, 0.65)`, 50 m resolution |

Partial-edge flooding is critical: a full bbox buffer would flood every edge. The fixture
rasterizes only the middle segment of `e_23` so Script 2 closes exactly one link.

Fixture: `network_spec("braess")` in [`tests/toy_pipeline_fixtures.py`](../../tests/toy_pipeline_fixtures.py).

## Golden behavior (asserted exactly)

| Metric | Freight | Passenger |
|--------|---------|-----------|
| Disrupted flow | 12.0 | 13.0 |
| Reroute cost | 5.160587707273884 | 5.5906366828800245 |
| Flow on gain edge (`e_13`) | 12.0 | 13.0 |

Baseline path: `e_12` → `e_23` → `e_34` at 24 veh per edge; `e_13` starts at 0 flow.

## Run

```powershell
pytest tests/test_toy_pipeline_disruptions.py -k braess -v --basetemp ".pytest-tmp"
```
