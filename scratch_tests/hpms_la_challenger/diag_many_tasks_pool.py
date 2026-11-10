"""Does Pool+imap hang with ~3154 tiny tasks on the AFTER network pickle?

Isolates 'many tasks' vs 'bad OD content'.
"""
from __future__ import annotations

import logging
import pickle
import sys
import time
from multiprocessing import Pool, set_start_method
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

sys.path.insert(0, "/scratch/akothaw/multimodal_hazard_data/code/ResiFlow/src")
from resiflow import constants as cons
from resiflow.road_revised import find_least_cost_path, worker_init_path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("many")

ISO = Path(
    "/scratch/akothaw/multimodal_hazard_data/scratch_tests/hpms_la_challenger/"
    "isolated_base/networks/faf5"
)


def main() -> int:
    try:
        set_start_method("spawn")
    except RuntimeError:
        pass

    links = gpd.read_parquet(ISO / "faf5_road_links.gpq")
    speed = pd.to_numeric(links["Speed_Limit"], errors="coerce").where(lambda s: s > 0).fillna(45.0)
    links = links.copy()
    links["acc_speed"] = speed
    links["average_toll_cost"] = pd.to_numeric(links["average_toll_cost"], errors="coerce").fillna(0.0)
    links["length_mile"] = links.geometry.length * cons.CONV_METER_TO_MILE
    links["time_cost"] = links["length_mile"] / links["acc_speed"]
    links["operating_cost"] = 0.0
    links["weight"] = links["time_cost"] + links["average_toll_cost"]

    import igraph

    graph_df = links[
        ["from_id", "to_id", "e_id", "weight", "time_cost", "operating_cost", "average_toll_cost", "length_mile"]
    ]
    network = igraph.Graph.TupleList(
        graph_df.itertuples(index=False), edge_attrs=list(graph_df.columns)[2:], directed=False
    )
    pkl = pickle.dumps(network)
    log.info("igraph v=%s e=%s pickle=%.1fMB", network.vcount(), network.ecount(), len(pkl) / 1e6)

    names = [str(x) for x in network.vs["name"][:4000]]
    dests = names[100:130]
    # 3154 origins, each with 30 dests (tiny vs production but same task count)
    origins = names[:3154]
    args = [(o, dests, [1.0] * len(dests)) for o in origins]
    log.info("tasks=%s dests/task=%s", len(args), len(dests))

    ncpu = 8
    t0 = time.time()
    with Pool(processes=ncpu, initializer=worker_init_path, initargs=(pkl,)) as pool:
        log.info("pool up %.2fs — imap starting", time.time() - t0)
        t1 = time.time()
        n = 0
        for _ in pool.imap_unordered(find_least_cost_path, args, chunksize=1):
            n += 1
            if n == 1 or n % 100 == 0:
                log.info("completed %s / %s (%.1fs)", n, len(args), time.time() - t1)
        log.info("ALL %s done in %.1fs", n, time.time() - t1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
