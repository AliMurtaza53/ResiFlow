#!/usr/bin/env python3
"""Draw the freight OD build flowchart (what scripts/build_conus_freight_od.py does, with the June-19 build numbers and where it breaks)."""
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

BLUE, GREY, RED, GREEN = "#dbe8f5", "#eef0f2", "#f7d9d4", "#dff0e3"
EDGE = {BLUE: "#3a7ca5", GREY: "#7a8591", RED: "#c0392b", GREEN: "#3b8d5a"}

STEPS = [
    ("INPUTS", BLUE,
     ["FAF5.7.1 regional OD: FAF zone to FAF zone, by SCTG commodity and mode",
      "BTS county disaggregation factors: truck_origin_factors, truck_destination_factors"],
     ["2,671,386 FAF rows read; 684,470 truck rows kept", "60,251 zone-pair x SCTG records", "files under Desktop\\data\\faf5_data"]),
    ("1  Split FAF zone flows into county pairs", GREY,
     ["county tons = FAF zone tons x origin county factor x destination county factor",
      "then tons to daily truck trips (payload per truck)"],
     ["faf5_conus_county_od.py", "40,049,004 county-pair x SCTG rows", "12.67 billion tons preserved",
      "1,735,334.7 trips/day; flat 20 t/truck per manifest"]),
    ("2  FAF5 loading centroids", GREY,
     ["FAF5Network.gdb, layer FAF5_Nodes: 3,796 loading-centroid points (lon/lat)",
      "CentroidID is the county FIPS for most counties"],
     ["faf5_network_loading_centroids.gpq", "exported from the geodatabase"]),
    ("3  Snap each loading centroid to the nearest road node", GREY,
     ["nearest node in networks/faf5/faf5_road_nodes.gpq (EPSG:2163, metres)",
      "result: assigned_node_id = a node id in THAT file's numbering"],
     ["map_network_centroids_to_assignment_nodes", "map_bts_od_to_network_centroids.py:285"]),
    ("4  County to node crosswalk (3,144 counties)", GREY,
     ["exact match, county FIPS = CentroidID: 3,133 counties",
      "no match: nearest loading centroid from the TIGER county centroid: 11 counties",
      "(9 Connecticut planning regions, 2 Alaska boroughs); warned at 36 and 83 miles"],
     ["bts_county_to_network_centroid_crosswalk_2022.csv", "build_detail_zone_crosswalk, line 335"]),
    ("5  Assignment OD", GREEN,
     ["each county-pair row becomes (origin_node, destination_node); sum to Car21",
      "faf5_od_matrix.pq: 9,774,907 rows, 3,143 distinct nodes, 1,735,334.699 trips"],
     ["trips preserved before and after mapping", "crosswalk node = OD node for 3,144 of 3,144 counties"]),
    ("6  Script 1 routes the OD node ids on the road LINKS", RED,
     ["the links carry from_id / to_id in a DIFFERENT numbering than the nodes file used in step 3",
      "node id 6811 = Los Angeles (-118.26, 34.05) to the snap,",
      "but West Texas (-101.77, 32.14) on the links"],
     ["ids = a counter in order of first appearance", "while walking the link table",
      "(faf5_network.py:360-405): positional",
      "measured: 2.9% of counties on own-state links"]),
]

H, GAP, W_MAIN, X0 = 13.0, 3.2, 56.0, 3.0
fig_h = (len(STEPS) * (H + GAP)) * 0.145 + 1.6
fig, ax = plt.subplots(figsize=(15, fig_h))
total = len(STEPS) * (H + GAP) + 6
ax.set_xlim(0, 100); ax.set_ylim(0, total); ax.axis("off")
ax.text(X0, total - 1.5, "How the county freight OD is built, and where it breaks", fontsize=17, fontweight="bold", family="serif", va="center")
ax.text(X0, total - 4.6, "Source: scripts/build_conus_freight_od.py and the June 19 build record (summaries, crosswalk, manifest). Numbers are from those files.",
        fontsize=9.5, color="#555", family="serif", va="center")
y = total - 7.5
prev = None
for title, col, body, evid in STEPS:
    top = y
    box = FancyBboxPatch((X0, top - H), W_MAIN, H, boxstyle="round,pad=0.3,rounding_size=1.2", fc=col, ec=EDGE[col], lw=1.8)
    ax.add_patch(box)
    ax.text(X0 + 1.2, top - 2.0, title, fontsize=12.5, fontweight="bold", family="serif", va="center")
    for i, line in enumerate(body):
        ax.text(X0 + 1.4, top - 4.9 - i * 2.35, line, fontsize=9.6, family="serif", va="center", wrap=True)
    ev = FancyBboxPatch((X0 + W_MAIN + 3, top - H), 100 - X0 - W_MAIN - 6, H, boxstyle="round,pad=0.3,rounding_size=1.0", fc="white", ec="#c9ced4", lw=1.0)
    ax.add_patch(ev)
    ax.text(X0 + W_MAIN + 4.2, top - 2.0, "evidence", fontsize=9, color="#777", style="italic", family="serif", va="center")
    for i, line in enumerate(evid):
        ax.text(X0 + W_MAIN + 4.2, top - 4.5 - i * 2.2, line, fontsize=8.8, family="serif", va="center", color="#333")
    if prev is not None:
        ax.annotate("", xy=(X0 + W_MAIN / 2, top + 0.4), xytext=(X0 + W_MAIN / 2, top + GAP - 0.4), arrowprops=dict(arrowstyle="-|>", lw=1.8, color="#555"))
    prev = top
    y = top - H - GAP

out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("od_build_flowchart.png")
fig.savefig(out, dpi=150, bbox_inches="tight", facecolor="white")
print("wrote", out)
