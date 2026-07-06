# TNTP testbed adapter

ResiFlow can run benchmark networks from the [TNTP](https://github.com/bstabler/TransportationNetworks) format without replacing the production FAF5/OSM pipeline.

## Layers

| Package | Role |
|---------|------|
| `resiflow.networks.tntp` | Parse TNTP node/net/trip files; build GeoDataFrames |
| `resiflow.demand.tntp` | Load scaled OD from TNTP trips |
| `resiflow.testbeds` | JSON registry under `parameters/testbeds/` |
| `resiflow.assignment.ue_bpr` | BPR + Frank-Wolfe user equilibrium benchmark |
| `resiflow.assignment.compare` | Run UE and cap-constrained assignment on the same testbed |

Production assignment still uses `road_revised.network_flow_model` (piecewise speed–flow, capacity constraints). UE is a comparison baseline only.

## Sioux Falls

- Data: `tests/data/sioux_falls_tntp/`
- Registry: `parameters/testbeds/sioux_falls.json`
- Mapping: `parameters/network_mapping.tntp.json`
- Pipeline fixtures: `tests/sioux_falls_fixtures.py` (FAF5-compatible outputs with `sf_` node prefix)

## UE vs cap-constrained comparison

```bash
python scripts/compare_ue_capconstrained.py --testbed sioux_falls
```

Expect **correlation**, not identity: UE uses link-specific BPR parameters from the TNTP net file; ResiFlow uses tier-based piecewise speed–flow curves from `assignment_profiles.json`. ResiFlow's baseline assignment graph is **undirected**, so compare undirected link totals (sum of both directions) for routing-pattern similarity; directed correlation is usually lower.

Tests: `tests/test_ue_vs_capconstrained_sioux_falls.py` (marked `slow` for the full comparison).
