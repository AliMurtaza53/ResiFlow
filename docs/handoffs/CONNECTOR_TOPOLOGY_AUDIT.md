# Connector topology audit, 2026-11-17

## Scope and method

Read the saved CONUS control graph after edge initialization, excluding the Class 50 connectors and retaining all physical roads with unknown native class. It has 483,442 physical links, 344,994 incident road nodes and 178 undirected components. The main component has 343,658 nodes. Passenger base and split outputs use the same physical link-ID support.

The solver builds undirected physical roads. Endpoint-only access builds directed routing arcs and returns physical edge indices, preserving shared capacity. A strongly connected-component filter applied to raw stored from/to columns would use a different graph from the solver and could incorrectly reject valid access.

Audit all 3,795 official connector road ends, all 256 eligible two-exit passenger counties, and the positive-demand passenger base/split road endpoints. Also check the intended gateway sets in the full CONUS and Harvey-15 experiments.

## Findings

1. Clark County WA, FIPS 53011, is the only CONUS connector with a road end outside the main component. Link 306463 reaches node 55804 in a two-node component. Its other official connector 306464 reaches node 55797, which is on the main component.
2. The passenger split puts 41,971.776 origin trips and 19,380.2692 destination trips on 55804. The affected OD total is 61,352.0452 trips, matching the structural-isolation log. The passenger base has no loaded endpoint outside the main component.
3. All other 255 eligible passenger split counties have both endpoints on the main component. Outside CONUS, 15 parent centroids and four gateway centroids have all their road attachments outside this main component. Those locations are in Alaska and Hawaii, which the current corrected demand excludes. They require geography-aware handling if that scope expands.
4. All 101 sub-county connector ends are on the main component. All 238 loaded CONUS gateways and all 114 loaded Harvey-15 gateways have main-component access. The Clark parent centroid can use its connected exit under endpoint-only routing. Its disconnected exit does not create a baseline freight isolation when the parent itself is the OD endpoint.
5. A further 17 parent connector ends, two sub-county connector ends and 173 gateway connector ends have physical road degree one on the main component. The gateway ends represent 149 distinct gateways. These are connected access leaves, not disconnected islands. Their sole road is a cut edge, so closure or capacity deletion can isolate them. The two sub-county leaves are 13121002 at road node 211915 and 18097001 at 216120. Degree one alone is not a reason to discard an endpoint.
6. A nullable-class audit bug excluded four valid physical roads when selecting `faf5_class.ne(50)`. Their IDs are 333850, 1031185, 1350417 and 1459516. Corrected selection uses the complement of `eq(50).fillna(False)`. The gateway verifier now uses this selection. Re-running it against both saved gateway baselines passes physical-capacity equality, capacity limits, intended gateway loading and one-pass delivery. The disconnected-endpoint conclusion is unchanged.

## Preventive handling

Before allocating OD, build connected components from the initialized physical graph the solver uses, retaining unknown-class physical roads and removing any initially closed links. Check positive demand endpoints by geography against the appropriate connected network. Do not include centroid links when establishing physical connectivity, since they can mask a road island through a multi-exit centroid.

For passenger splitting, drop Clark's disconnected exit and renormalize its share to the connected exit. Do not change the existing demand quantities. If no valid exit remains, emit a hard failure with county/node IDs rather than silently loading a different location. Record dropped exits and before/after totals. Rebuild the split files and rerun the affected passenger comparison to measure the resulting assignment change.

For C/S/G loading, require at least one valid physical exit per intended centroid, and report partially invalid multi-exit centroids separately. After hazard closures and each capacity-pruning step, distinguish demand disconnected by the physical graph from residual demand whose paths still exist. A main-component and degree check at baseline cannot predict the full dynamic congestion-isolation outcome.

Retain degree-one access as valid and report the sole physical road, its initial capacity, cumulative assigned flow and any closure/pruning iteration. This makes the existing passenger and future combined-run cut-off behavior auditable.

## Evidence

The accompanying `CONNECTOR_TOPOLOGY_ENDS.csv` contains the per-link endpoint component size, main-component membership, road degree, incident physical cut edges and bridge-free block size. The complete passenger node inventories and reproduction script are in the local Transport Network Analysis workspace. Hopper artifacts are under `stage2_scripts/connector_topology_audit_20261117/`.

The observations validate the present baseline connectivity scope. They do not establish that degree-one loading is appropriate for every facility or quantify which dynamic link deletions caused the remaining passenger isolation.
