# HPMS → FAF5 LRS attribute transfer — status note

**Branch intent:** `feature/faf5-network-enrichment` (revived from `feature/hpms-faf-lrs-transfer`)  
**Script:** `scripts/hpms_to_faf_lrs_transfer.py`  
**Date:** 2026-09-22 (updated 2026-09-25)

## Goal

Transfer HPMS inventory attributes onto FAF5 network links where FAF already
carries HPMS LRS keys (`HPMS_USA_RouteID`, `HPMS_Begin_Point`,
`HPMS_End_Point`), so ResiFlow can use terrain / structure / toll / lanes /
urban / F_SYSTEM from HPMS without a full spatial rematch.

## What was run (local)

- **FAF5:** `Desktop/data/faf5_data/network_data/FAF5Network.gdb`
- **HPMS:** `Downloads/HPMS_2020.gdb.zip` (2020 Full Extent state layers)
- **Outputs (not in git; large / local-only):**
  `Desktop/data/faf5_data/network_data/hpms_transfer/`
  - `faf_hpms_lrs_enriched.csv`
  - `qa_summary.json`
  - `qa_report.html` (+ `sample_matched.geojson`)

## Headline results

| Metric | Value |
|--------|------:|
| FAF links | 487,394 |
| With complete HPMS keys | 99,440 (~20% of links; ~28% of USA miles) |
| Overlap matches (RouteID + measure overlap) | 81,806 links / ~128k miles |
| Match rate of **keyed** miles | ~81% |
| Match rate of **all USA** FAF miles | ~22% |
| F_SYSTEM vs FAF `F_Class` agreement (where both present) | ~97.5% |

Transferred fields (length-weighted predominance on measure overlap):
`Terrain_Type`, `STRUCTURE_TYPE`, `TOL_CHARGED`, `TOLL_TYPE`,
`THROUGH_LANES`, `F_SYSTEM`, `URBAN_CODE`.

## Known gaps / pick-up work

1. **Year drift:** FAF keys are documented as ~2018 HPMS; donor was HPMS
   **2020**. Some RouteIDs vanished or measures drifted.
2. **Broken states (0% keyed-mile match):** KS, MT, NM, OK — RouteID schema
   mismatch. Weak: CA (~2%), AZ/IN (~1%), WY (~31%).
3. **Unkeyed FAF (~70–80% of links):** ramps, centroid connectors, etc. Need
   spatial fallback or accept nulls — LRS alone will not cover them.
4. **STRUCTURE_TYPE / Terrain_Type** are sparse by HPMS design (structures
   only where coded; terrain often sample/urban N/A). For bridges/tunnels,
   NBI/NTI overlays are still the better long-term source.
5. **Outputs not committed** — re-run the script after paths are set, or copy
   `hpms_transfer/` from the machine that produced it.

## How to resume

```bash
python scripts/hpms_to_faf_lrs_transfer.py \
  --faf-gdb <path/to/FAF5Network.gdb> \
  --hpms-zip <path/to/HPMS_2020.gdb.zip> \
  --out-dir <path/to/hpms_transfer>
# optional pilot: --states RI,CT,NH
```

Open `qa_report.html` for match charts + sample map. Join enriched CSV to
FAF on `ID` for full-network QA.

## OSM (deferred)

OpenStreetMap is a possible **future** secondary source for tunnels/structures
on FAF links that lack HPMS LRS keys. It is **not** in scope for this branch:
we keep FAF5 as the base network and only attach attributes where NBI (bridges)
or HPMS LRS overlap (tunnels / structure type) provides evidence. Do not replace
FAF with an OSM extract here.

## Enrichment wiring (same branch)

| Attribute | Source | Wire-up |
|-----------|--------|---------|
| Toll $ | FAF5 `TRUCKTOLL` | `faf5_network.convert_faf5_links` → `average_toll_cost` |
| Bridge | NBI index parquet | `nbi_bridge_index_path` / `scripts/patch_faf5_bridge_attributes.py` |
| Tunnel | **NTAD NTI** spatial-join index | `nti_tunnel_index_path` / `scripts/patch_faf5_tunnel_attributes.py` |
| Tunnel QA | HPMS `STRUCTURE_TYPE=2` on LRS-keyed overlap | compare only (`summarize_network_structure_counts.py`) |
| Terrain / lanes | HPMS LRS (2020 pilot; 2024 donor supported) | `scripts/hpms_to_faf_lrs_transfer.py --hpms-gdb-name HPMS2024.gdb` |

Local dry-run artifacts (not production swap):
`Desktop/data/faf5_data/network_data/enrichment/`
(`faf5_road_links_bridge_tunnel_patched.gpq`, indices, `structure_coverage_compare.json`).

On bridge∩tunnel conflicts, patch defaults to `--on-conflict prefer_tunnel`
(same as `derive_road_label` / `convert_faf5_links`). Pass `error` or
`prefer_bridge` explicitly when reviewing. Dry-run wrote
`bridge_tunnel_conflicts.csv`.

**Locational flags (not facility span):** `road_bridge` / `road_tunnel` /
`road_label` mean an NBI/NTI feature is associated with the FAF edge
(nearest within tolerance), not that the whole edge is a bridge or tunnel.
Use `structure_length_m` / `tunnel_length_m` and `bridge_fraction` /
`tunnel_fraction` for asset geometry. Matches with null or non-positive
inventory length or deck width are excluded. Coverage metrics:
`scripts/publish_bridge_tunnel_coverage_metrics.py`. See
`docs/BRIDGE_TUNNEL_JOIN_REVIEW.md`. Splitting long FAF edges into true
bridge/road sub-segments is deferred.

## Related context (not this branch)

Visual-registry multi-geo / affected–neighboring–other work lives under
`docs/visual_registry.csv` and `docs/VISUAL_REGISTRY_NOTES.md` and was edited
separately from this HPMS transfer feature.
