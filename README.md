# ResiFlow

Hazard-agnostic transport resilience framework derived from [DAFNI-NIRD](https://github.com/nismod/DAFNI-NIRD). ResiFlow keeps the four-script NIRD workflow (baseline assignment → hazard disruption → direct damage → rerouting/recovery) but refactors disruption around a shared link contract, adds freight + passenger OD, and ships pytest testbeds that run without a CONUS data bundle.

**For reviewers coming from NIRD:** start with [`docs/PIPELINE_OVERVIEW.md`](docs/PIPELINE_OVERVIEW.md) (script flow and outputs), then [`docs/hazard_agnostic_refactor.md`](docs/hazard_agnostic_refactor.md) (what changed and why). Run the testbed suite below — no `config.json` or FAF5 inputs required.

| Branch | Purpose |
|--------|---------|
| [`main`](https://github.com/AliMurtaza53/ResiFlow/tree/main) | Stable refactor: hazard-agnostic disruption, Sioux Falls / toy testbeds, CONUS smoke tooling |
| [`feature/sioux-falls-multihazard`](https://github.com/AliMurtaza53/ResiFlow/tree/feature/sioux-falls-multihazard) | WIP: multihazard Sioux Falls testbed, unique scenario keys, cost-comparison panels (not merged to `main`) |

## Quick start (reviewers)

```powershell
git clone https://github.com/AliMurtaza53/ResiFlow.git
cd ResiFlow
conda env create -f environment.yml   # or: pip install -e ".[dev]" && pip install nismod-snail
conda activate resiflow
pytest tests/test_toy_pipeline_disruptions.py tests/test_sioux_falls_pipeline_disruptions.py tests/test_scenario_registry.py -v --basetemp .pytest-tmp
```

Full testbed E2E (includes ~5 min multihazard on the feature branch):

```powershell
pytest tests/test_toy_pipeline_disruptions.py tests/test_sioux_falls_pipeline_disruptions.py -v --basetemp .pytest-tmp
# feature branch only:
pytest tests/test_multihazard_pipeline_sioux_falls.py -v --basetemp .pytest-tmp
```

## Install

**Python 3.10+** (CI uses 3.12). GDAL/rasterio are easiest via conda on Windows.

```powershell
# Option A — conda (recommended on Windows)
conda env create -f environment.yml
conda activate resiflow

# Option B — pip only (requires GDAL already on PATH)
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pip install nismod-snail
```

Copy configuration templates and point them at your data:

```powershell
copy config.example.json config.json
copy .env.example .env
# Edit config.json → paths.soge_clusters to your data bundle root
```

Environment variables accept `RESIFLOW_*` names with `NIRD_*` fallbacks (`resiflow.config`).

## Data layout

Scripts read from `config.json` → `paths.soge_clusters` (also `base_path`):

```text
<data_bundle>/
  networks/faf5/faf5_road_links.gpq
  census_datasets/faf5_od_matrix.pq          # freight OD
  parameters/
    assignment_profiles.json                 # copy from repo parameters/
    network_mapping.faf5.json
    ...
  inputs/test_141node_50m/                   # hazard rasters (toy or production)
```

Copy reference parameters from [`parameters/`](parameters/) into your data bundle before production runs. See [`parameters/README.md`](parameters/README.md).

Passenger OD (optional): build with `scripts/build_lodes_passenger_od.py`, then set `RESIFLOW_PASSENGER_OD_PATH` or place under `<parent>/lodes_data/processed/`.

## Run the model

Numbered scripts form the main pipeline. Run from the repository root with the conda/venv active and `RESIFLOW_CONFIG_PATH` set.

| Step | Script | Purpose |
|------|--------|---------|
| 1 | `scripts/1_network_flow_model_revision.py` | Baseline cap-constrained assignment (freight ± passenger) |
| 2 | `scripts/2_intersection_analysis.py` | Hazard ∩ network → disrupted links |
| 3 | `scripts/3_damage_analysis.py` | Direct damage from fragility curves |
| 4 | `scripts/4_rerouting_and_recovery_scenario_loop.py` | Rerouting costs + recovery scenarios |

```powershell
$env:RESIFLOW_CONFIG_PATH = "config.json"
$env:RESIFLOW_MAX_FLOW_ITERATIONS = "2"    # smoke: cap assignment iterations (0 = full)
$env:RESIFLOW_SAMPLE_OD_N = "50000"        # smoke: subsample OD rows

python scripts/1_network_flow_model_revision.py 20 1
python scripts/2_intersection_analysis.py 30 1
python scripts/3_damage_analysis.py
python scripts/4_rerouting_and_recovery_scenario_loop.py 30 1 1 1
```

**Snow disruption:** `RESIFLOW_HAZARD_TYPE=snow` and pass snow depth (mm) as Script 2's first argument.

## Documentation map

| Doc | Audience |
|-----|----------|
| [`docs/PIPELINE_OVERVIEW.md`](docs/PIPELINE_OVERVIEW.md) | Script-by-script flow, inputs/outputs |
| [`docs/hazard_agnostic_refactor.md`](docs/hazard_agnostic_refactor.md) | Disruption refactor design |
| [`docs/testbeds/README.md`](docs/testbeds/README.md) | Toy / Sioux Falls pytest testbeds |
| [`docs/CONUS_FREIGHT_WORKFLOW.md`](docs/CONUS_FREIGHT_WORKFLOW.md) | Full CONUS data bundle + launcher |
| [`docs/PERFORMANCE_CONUS.md`](docs/PERFORMANCE_CONUS.md) | CONUS runtime bottlenecks and mitigations |
| [`docs/lodes_passenger_module.md`](docs/lodes_passenger_module.md) | LODES passenger OD |
| [`docs/FREIGHT_OD_DISAGGREGATION.md`](docs/FREIGHT_OD_DISAGGREGATION.md) | FAF5 freight OD build |

Summarize a completed run:

```powershell
python scripts/summarize_scenario_run.py
```

## Testbeds

Pytest fixtures exercise the full pipeline on toy and TNTP-derived networks:

```powershell
pytest tests/ -v --basetemp .pytest-tmp
```

| Testbed | Docs |
|---------|------|
| Three-parallel, Braess, Sioux Falls | [`docs/testbeds/README.md`](docs/testbeds/README.md) |
| TNTP adapter + UE benchmark | [`docs/testbeds/tntp_adapter.md`](docs/testbeds/tntp_adapter.md) |
| Multihazard Sioux Falls (feature branch) | [`docs/testbeds/multihazard_sioux_falls.md`](docs/testbeds/multihazard_sioux_falls.md) |

Compare BPR user equilibrium vs ResiFlow cap-constrained assignment (Sioux Falls):

```powershell
python scripts/compare_ue_capconstrained.py --testbed sioux_falls
```

## Package layout

| Module | Role |
|--------|------|
| `resiflow.networks` | Link normalization, FAF5/OSM/TNTP adapters, assignment tiers |
| `resiflow.demand` | Freight + passenger OD loading and merge |
| `resiflow.hazards` | Hazard-agnostic event sources + scenario registry (feature branch) |
| `resiflow.disruption` | Operational disruption pipeline |
| `resiflow.assignment` | BPR UE benchmark (TNTP testbeds) |
| `resiflow.testbeds` | Registered TNTP / toy testbed JSON specs |

## Development

```powershell
pip install -e ".[dev]"
pytest tests/ -v --basetemp .pytest-tmp
ruff check src tests
```

Do not commit `config.json`, `.env`, local databases, `results/`, or `.pytest-tmp/` (see `.gitignore`).

## Attribution

Derived from DAFNI-NIRD. See [NOTICE](NOTICE).
