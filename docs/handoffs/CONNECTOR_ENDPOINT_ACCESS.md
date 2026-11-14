# FAF5 endpoint-only connector access

The Harvey-15 baseline found 2,362 of 1,844,969 paths (0.128%) using a non-endpoint centroid. This exceeded the agreed 0.1% gate. The recovery job stopped before flood intersection.

Use the existing experiment branch and native-network switch. The routing worker uses separate departure and arrival vertices for official centroids and maps directed routing arcs back to the original physical edge indices. Existing assignment, capacity, and path-export tables retain one row per physical link.

Budget one focused routing regression run and one Anaheim check with intact and disrupted access. Verify eligible exit choice, no through-routing, conservation and shared capacity. Advance to one paired Harvey-15 comparison only after the testbed gates pass. Require zero shortcut paths in the baseline and recovery exports, and stop and report any regression. OD quantities, payloads and physical road capacities remain fixed.
