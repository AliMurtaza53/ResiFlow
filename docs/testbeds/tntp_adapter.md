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

## Anaheim (assignment-diagnostics testbed)

- Data: `tests/data/anaheim_tntp/` (TNTP net/trips/best-known flow + `anaheim.geojson` link polylines + `anaheim_nodes.geojson`)
- Registry: `parameters/testbeds/anaheim.json` (`node_file` is the node GeoJSON; `link_geojson` supplies real link geometry)
- 38 zones, 416 nodes, 914 links, of which 118 are zone-centroid connectors (nodes 1-38)
- `read_tntp_nodes` accepts a `.geojson` Point layer; `read_link_geojson` matches polylines to net links by row order and raises if the order or count differs
- Tests: `tests/test_anaheim_testbed.py`
