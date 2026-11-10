# HPMS-LA challenger — Hopper status

Updated: 2026-10-29 ~21:10 EDT

## Done

- Isolated tree: `cp -al soge_clusters → …/hpms_la_challenger/isolated_base`, then `rm` of hardlinked `faf5_road_{links,nodes}.gpq` (shared originals untouched).
- Splice (`splice_hpms_la_network.py`): FAF5 + mid-noded HPMS-LA + 11 247 transfer pairs (≤30 m) + 12 unique-segment centroids.
  - Final: **688 544 links**, **429 440 nodes** (from 483 599 / 344 999).
  - OD remaps: 6 home + 6 work FAF nodes → centroid ids `600000+`; Car21 conserved.
- Cheap-checks: **ALL PASSED**.
- SLURM AFTER 2-iter: **job 2962219** on `bigmem` / `amd077` (running).

## Paths

| Artifact | Path |
|---|---|
| Isolated network | `/scratch/akothaw/multimodal_hazard_data/scratch_tests/hpms_la_challenger/isolated_base` |
| OD | `…/hpms_la_challenger/passenger_od_hpms_la.pq` |
| Config | `…/hpms_la_challenger/config_hopper_hpms_la.json` |
| Logs | `/home/akothaw/multimodal_hazard_project/logs_hpms_la_AFTER_2iter_2962219.{out,err}` |
| DuckDB | `/scratch/akothaw/multimodal_hazard_data/dbs/hpms_la_after_2iter.duckdb` |
| BEFORE twin | job `2878530` (`logs_la_conn_BEFORE_2iter_2878530.*`) |

## BEFORE twin (job 2878530, COMPLETED 02:34:31)

- edges: 483 442 · supply: 109 008 763.6
- iter1 pool dispatch ~923 s; streaming pass1 ~3095 s; assigned_fraction ~3.19%
- iter2 pool dispatch ~943 s; streaming pass1 ~3123 s; assigned_fraction ~4.26%
- stop: max iterations (2)

## AFTER (job 2962219) — CANCELLED 19:38 EDT after 6h21m

### Root cause (fixed)

`align_od_node_dtype` casts OD nodes to **int**. python-igraph treats a bare int in `get_shortest_paths` as a vertex **index**, not a name. Centroid ids `600000+` exceed `vcount` (~429k) → `InternalError: invalid vertex ID` in workers → zombies → parent hung on `imap` with no traceback.

- cpu1 repro (pre-fix): crashed ~origin 80 with that InternalError
- After `_igraph_vertex_index` name lookup in `find_least_cost_path`: stride pool progressed past 300+/3154 origins
- Fix synced to Hopper `code/ResiFlow/src/resiflow/road_revised.py`

### LCP regression (agile fix)

Hung/timeout run `2968425` already dead (TIMEOUT 12h). **Root tax:** per-dest `vs.find` (~73–98 s for 3k lookups) vs dict resolve (~0.4 ms) → **~1.8e5×** lookup overhead.

Dict `_name_to_idx` rebuilt in `worker_init_path` **and** `refresh_worker_network`. Bench `2974137` **GATE PASS**: AFTER/BEFORE Pool 200-origin = **1.17×** (edges 1.42×).

### Twin result — AFTER 1-iter `2974193` COMPLETED 01:32:10

| Metric (iter1) | BEFORE `2878530` | AFTER `2974193` | ratio |
|---|---|---|---|
| Pool dispatch | 923 s | 1112 s | **1.20×** |
| Streaming pass1 | 3095 s | 3687 s | 1.19× |
| assigned_fraction | 3.19% | 2.67% | — |
| Wall (1 iter) | ~76 min | 92 min | 1.21× |

Lookup tax fixed (was ~40×). Residual ~1.2× tracks edge growth (1.42×). National assigned_fraction did **not** improve in iter1 — densification did not buy vehicles/hour here.

### LA-local (provisional — 1-iter AFTER vs 2-iter BEFORE)

- Centroids reach 49/50 national FAF sample (connected). Degrees 4–8.
- LA-touch OD Car21 conserved at 8.37M.
- Isolated fraction of LA-touch demand: BEFORE **86.9%** vs AFTER-1iter **96.4%** — **not a fair iter-count match**; rerun after 2-iter twin.

### Twin result — AFTER 2-iter `3022360` COMPLETED 03:00:01

| Metric | BEFORE `2878530` | AFTER `3022360` | ratio |
|---|---|---|---|
| Wall | 02:34:31 | 03:00:01 | **1.17×** |
| Iter1 pool | 923 s | 1076 s | 1.17× |
| Iter2 pool | 943 s | 1092 s | 1.16× |
| assigned_fraction iter1 | 3.19% | 2.67% | worse |
| assigned_fraction iter2 | 4.26% | 3.60% | worse |
| LA-touch isolated frac | **86.9%** | **95.5%** | worse |

Centroids are graph-connected (49/50 national reach). Challenger densification did **not** improve national vehicles/hour or LA-touch isolation vs FAF5 BEFORE. Do **not** claim ~20% without user confirm — evidence points the other way.
