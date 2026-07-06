# Canonical routing disruption testbeds

Three reproducible networks exercise the full NIRD pipeline (Scripts 1–4) in pytest
temporary directories. Each testbed validates hazard exposure, operational disruption,
direct damage, and freight/passenger rerouting on a known topology.

| Testbed | Variant | Topology | Primary assertion |
|---------|---------|----------|-------------------|
| [Canonical parallel](canonical_parallel.md) | `toy_three_parallel` | 3 parallel links n1→n2 | Exact golden reroute costs onto `e_mid` |
| [Braess](braess.md) | `toy_braess` | Classic Braess diamond | Partial-edge flood; reroute onto `e_13` |
| [Sioux Falls](sioux_falls.md) | `toy_sioux_falls` | TNTP 24-node / 76-link network | Bridge 10–15 flood; realism-mode calibration |

## Run all testbed E2E tests

```powershell
pip install -e ".[dev]"
pytest tests/test_toy_pipeline_disruptions.py tests/test_sioux_falls_pipeline_disruptions.py -v --basetemp ".pytest-tmp"
```

## Scenario QA after a run

Point summary tools at the **pipeline** pytest folder (`test_sioux_falls_pipeline_scri0`, not `links_reproje0`):

```powershell
$env:NIRD_RESULTS_ROOT = ".pytest-tmp/test_sioux_falls_pipeline_scri0/results"
$env:NIRD_RESULTS_VARIANT = "toy_sioux_falls"
$env:NIRD_TESTBED = "1"
python scripts/summarize_scenario_run.py
```

Or open [`scripts/visualizations/visualize_scenario_qa.ipynb`](../../scripts/visualizations/visualize_scenario_qa.ipynb).

## Relationship between testbeds

```text
three_parallel / braess  →  exact numeric golden values (routing algebra)
sioux_falls              →  real topology + calibrated demand/capacity (integration)
```

Synthetic parallel/Braess tests use `flow_cap_plph=1` so toy demand exceeds daily capacity
and disrupted flow is nonzero. Sioux Falls uses per-link TNTP capacities and scaled demand.

## Fixture entry points

| Testbed | Build function | Test module |
|---------|----------------|-------------|
| three_parallel, braess | `build_toy_dataset(tmp_path, name)` | `tests/test_toy_pipeline_disruptions.py` |
| sioux_falls | `build_sioux_falls_dataset(tmp_path)` | `tests/test_sioux_falls_pipeline_disruptions.py` |

Shared orchestration: `run_pipeline_scripts()` in `tests/toy_pipeline_fixtures.py`.

## Hazard-agnostic refactor

See [`docs/hazard_agnostic_refactor.md`](../hazard_agnostic_refactor.md) for the Phase 0
disruption contract (`LinkDisruptionRecord`) and ResiFlow migration plan.
