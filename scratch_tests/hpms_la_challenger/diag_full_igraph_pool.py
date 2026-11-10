"""Build igraph the production way (edge_init + create_igraph_network), then pool-test.

Uses RESIFLOW_CONFIG_PATH / same isolated soge as AFTER arm.
"""
from __future__ import annotations

import logging
import os
import pickle
import sys
import time
from multiprocessing import Pool, set_start_method
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

sys.path.insert(0, "/scratch/akothaw/multimodal_hazard_data/code/ResiFlow/src")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("diag_full")

# Match AFTER SLURM env (caller should export these; set defaults for safety)
os.environ.setdefault(
    "RESIFLOW_CONFIG_PATH",
    "/scratch/akothaw/multimodal_hazard_data/scratch_tests/hpms_la_challenger/config_hopper_hpms_la.json",
)
os.environ.setdefault("NIRD_CONFIG_PATH", os.environ["RESIFLOW_CONFIG_PATH"])


def main() -> int:
    try:
        set_start_method("spawn")
    except RuntimeError:
        pass

    from resiflow.parameters import get_parameter, load_profiles
    from resiflow.road_revised import (
        create_igraph_network,
        edge_init,
        edge_initial_speed_func,
        find_least_cost_path,
        worker_init_path,
    )

    soge = Path(get_parameter("paths", "soge_clusters"))
    links_path = soge / "networks/faf5/faf5_road_links.gpq"
    log.info("loading %s", links_path)
    road_links = gpd.read_parquet(links_path)
    log.info(
        "links=%s urban_null=%s speed_null=%s tier_null=%s",
        len(road_links),
        int(road_links["urban"].isna().sum()) if "urban" in road_links.columns else "NOCOL",
        int(road_links["Speed_Limit"].isna().sum()),
        int(road_links["assignment_tier"].isna().sum()),
    )

    profiles = load_profiles()
    free_flow = profiles["free_flow_speed"]
    urban_speed = profiles["urban_speed_cap"]
    min_flow = profiles["min_flow_speed"]
    flow_bp = profiles["flow_breakpoint"]
    # edge_initial_speed_func signature from road_revised
    road_links, _ = edge_initial_speed_func(
        road_links, free_flow, urban_speed, min_flow, flow_bp
    )
    road_links = edge_init(road_links)
    log.info(
        "after edge_init: free_flow null=%s acc_speed null=%s",
        int(pd.to_numeric(road_links.get("free_flow_speeds"), errors="coerce").isna().sum()),
        int(pd.to_numeric(road_links.get("acc_speed"), errors="coerce").isna().sum())
        if "acc_speed" in road_links.columns
        else "no acc_speed yet",
    )

    network, road_links = create_igraph_network(road_links, vehicle_type="car")
    w = np.asarray(network.es["weight"], dtype=float)
    log.info(
        "igraph v=%s e=%s weight null/nonfinite=%s min=%s max=%s",
        network.vcount(),
        network.ecount(),
        int((~np.isfinite(w)).sum()),
        float(np.nanmin(w)),
        float(np.nanmax(w)),
    )
    if int((~np.isfinite(w)).sum()) > 0:
        log.error("NON-FINITE WEIGHTS — likely LCP worker killer")
        return 2

    pkl = pickle.dumps(network)
    log.info("pickle=%.1f MB", len(pkl) / 1e6)

    # Use real OD origins sample from patched OD
    od = pd.read_parquet(
        "/scratch/akothaw/multimodal_hazard_data/scratch_tests/hpms_la_challenger/passenger_od_hpms_la.pq"
    )
    # Also include a remapped centroid origin if present
    origins = od["origin_node"].astype(str).value_counts().head(20).index.tolist()
    # add centroids
    for c in ["600000", "600024", "600045"]:
        if c not in origins:
            origins.append(c)
    # destinations: first 50 unique
    dests = od["destination_node"].astype(str).drop_duplicates().head(50).tolist()
    # filter to vertices that exist
    vnames = set(map(str, network.vs["name"]))
    origins = [o for o in origins if o in vnames][:10]
    dests = [d for d in dests if d in vnames][:30]
    if not origins or not dests:
        # fall back to raw vertex names
        names = [str(x) for x in network.vs["name"][:100]]
        origins, dests = names[:5], names[5:15]
    args = [(o, dests, [1.0] * len(dests)) for o in origins]
    log.info("pool test origins=%s dests=%s", len(args), len(dests))

    ncpu = int(os.environ.get("DIAG_NCPU", "4"))
    t0 = time.time()
    with Pool(processes=ncpu, initializer=worker_init_path, initargs=(pkl,)) as pool:
        log.info("pool up in %.2fs", time.time() - t0)
        t1 = time.time()
        results = list(pool.imap_unordered(find_least_cost_path, args, chunksize=1))
        log.info("imap done in %.2fs n=%s", time.time() - t1, len(results))
    log.info("OK full-path pool survived")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
