# Passenger connector-end connectivity fix

The split builder can now accept the eligible nodes from the initialized undirected physical road graph. It excludes Class 50 connectors, keeps roads whose native class is missing, removes initially unusable capacity, drops disconnected connector ends, and renormalizes each county's surviving shares. It raises a descriptive error if any eligible county loses every exit or an unsplit loading point is disconnected.

The passenger OD CLI now requires `--road-links` pointing to the matching initialized `edge_flows.gpq`. This deliberate fail-fast change prevents the CLI from silently building unverified split inputs. Existing Python callers can still use the old function signature. The CLI's `--preconverted-od` path rebuilds previously converted OD without changing occupancy or applying conversion twice. The output directory must be new. `node_targets.csv` and `report.json` record the retained and dropped endpoints.

## Rebuilt data

Hopper outputs are under `/scratch/akothaw/multimodal_hazard_data/stage2_scripts/passenger_connected_fix/rebuilt/`.

Clark County's base crosswalk node 55788 previously split between road endpoints 55804 and 55797. The checked target now assigns weight 1 to 55797 and zero to 55804. This is the only dropped endpoint among all 256 eligible split counties. The retained two-exit county count is 255. The physical network is unchanged.

The new CONUS split has 962,743 OD rows and 51,718,653.8941 trips/day. Every loaded endpoint is in the 343,658-node main physical component. Its OD pairs and weights match the old split after replacing 55804 by 55797 and combining duplicate rows, to 1e-12 relative tolerance. Both rebuilt unsplit inputs match the originals exactly. The Harvey-15 split remains exactly unchanged at 307,097 rows and 28,065,308.5036 trips/day.

Five split tests passed on Hopper. They cover existing equal-share behavior, conservation, holding original self trips, excluding a disconnected exit even when a synthetic centroid link would hide the island, retaining an unclassified physical road, renormalization, and errors when all exits or an unsplit node are disconnected.

## Assignment verification

The corrected CONUS passenger run is job `3788878`, variant `pax_cty1_conus_split_connected`. It uses the clean integrated checkout `badf15e`, passenger vehicle class car, eight CPUs, 600 GB memory, a 40-iteration cap and stage profiling. This is a fresh output variant. Earlier outputs remain available for comparison.
