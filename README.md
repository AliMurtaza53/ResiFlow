# ResiFlow

Hazard-agnostic transport resilience framework (forked from DAFNI-NIRD Phase 0).

## Quick start

```powershell
pip install -e ".[dev]"
pytest tests/test_toy_pipeline_disruptions.py tests/test_sioux_falls_pipeline_disruptions.py -v --basetemp .pytest-tmp
```

## Testbeds

See [docs/testbeds/README.md](docs/testbeds/README.md).

## Attribution

Derived from [DAFNI-NIRD](https://github.com/nismod/DAFNI-NIRD). See NOTICE.
