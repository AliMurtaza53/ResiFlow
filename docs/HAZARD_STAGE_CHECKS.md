# Hazard-stage checks (Script 4 rerouting)

Two checks on how the rerouting stage treats baseline traffic and partial capacity loss. Both are reproducible with the scripts named below. Neither changes model code.

## 1. Baseline flow does not reach the rerouting stage

Script 1 writes `edge_flows.gpq` with both `acc_*` (loaded flow, residual capacity) and `current_*` (initial state: flow 0, original capacity). `resiflow.disruption.pipeline` renames `acc_*` to `current_*` only when `current_*` is absent; when both exist it drops `acc_*`. So the disruption stage sees `current_flow = 0` and `current_capacity = original capacity`, and Script 4 starts rerouting with no background load.

Sioux Falls, full Script 1 to 4 chain (`scripts/testbed/sioux_falls_background_flow_check.py`):

| | baseline table | disruption-stage table |
|---|---|---|
| flow | `acc_flow` sum 2,886,921 | `current_flow` sum 0 |
| capacity | `acc_capacity` sum 15,803,983 (residual) | `current_capacity` sum 18,690,904 (original) |

Does it matter? It depends on baseline load. At the fixture's default demand (max baseline V/C 0.14) adding background flow back overloads no link. At 10x that demand (max baseline V/C 1.00, 7 of 76 links above 0.8), 3 links exceed physical capacity once `baseline - released + rerouted` is computed, with 9,747 units of excess against 62,262 rerouted. Capacity here is the undamaged physical capacity, so damage would make it worse. Treat this as a small-network demonstration of direction, not a CONUS magnitude.

## 2. The per-OD disruption rule is blind to partial capacity loss

Script 4 flags `disrupted_flow = (flow - acc_capacity).clip(lower=0)` per path row, where `acc_capacity` is the minimum damaged-link capacity on that path. It compares one path's flow with the link capacity, not the link's total load.

Anaheim baseline at 20x demand, the 10 most loaded links damaged (`scripts/testbed/hazard_stage_rule_check.py`; the rule is replicated from the script, not executed through it):

| capacity kept | link-load excess | flow the rule flags | overloaded links with no path flagged |
|---|---|---|---|
| 50% | 894,155 | 0 | 10 of 10 |
| 25% | 1,412,555 | 0 | 10 of 10 |
| 0% (closed) | 1,930,955 | 871,446 | 0 of 10 |

Closures are caught. Partial reductions (for example the 50% step in the extensive and severe recovery curve) are not, whenever no single path carries more than the damaged capacity. Rerouting cost during those phases is then understated, and links stay above their damaged capacity.
