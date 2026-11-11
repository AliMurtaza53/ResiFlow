# County <-> node crosswalks

| File | Node numbering | Use with |
|---|---|---|
| `county_node_crosswalk_conus_single_node.csv` | the OLD numbering the original OD files use | the original `faf5_od_matrix.pq` / `lodes_passenger_od_matrix.pq` only. Those ODs do NOT match the current road links (see `notes/perf_findings/OD_NODE_NUMBERING_MISMATCH.md`). |
| `county_node_crosswalk_conterminous.csv` | the CURRENT road network (links, Oct-23 nodes) | the corrected `*_conterminous.pq` ODs made by `scripts/make_conterminous_od.py` |
| `conus_od_node_remap.csv` | old node -> new node, with snap distance | audit of the re-snap |

Check a crosswalk against an OD with `scripts/diagnostics/county_node_crosswalk.py check`; a numbering mismatch shows up as unmatched nodes or a state-match share near 3%.
