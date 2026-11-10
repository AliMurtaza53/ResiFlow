"""Reproduce LCP pool hang: build igraph from AFTER network, spawn workers, one imap.

Run under nird env on Hopper. Exits 0 if workers return; hangs/zombies = repro.
"""
from __future__ import annotations

import logging
import os
import pickle
import sys
import time
from multiprocessing import Pool, get_start_method, set_start_method
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

sys.path.insert(0, "/scratch/akothaw/multimodal_hazard_data/code/ResiFlow/src")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("diag")

ISO = Path(
    "/scratch/akothaw/multimodal_hazard_data/scratch_tests/hpms_la_challenger/"
    "isolated_base/networks/faf5"
)


def main() -> int:
    try:
        set_start_method("spawn")
    except RuntimeError:
        pass
    log.info("start_method=%s", get_start_method())

    # Minimal path: load links, mimic create_igraph weight cols if already present
    # Prefer reusing the model's create path via a thin import.
    from resiflow import constants as cons

    links = gpd.read_parquet(ISO / "faf5_road_links.gpq")
    log.info("loaded links=%s cols_has_urban=%s", len(links), "urban" in links.columns)
    if "assignment_tier" not in links.columns:
        raise KeyError("links missing required 'assignment_tier'")

    # Lean repro: synthesize acc_speed (model fillna's null Speed_Limit via tier defaults).
    if "acc_speed" not in links.columns:
        # Mirror free_flow fill: observed Speed_Limit else tier default 45
        speed = pd.to_numeric(links["Speed_Limit"], errors="coerce")
        speed = speed.where(speed > 0).fillna(45.0)
        links = links.copy()
        links["acc_speed"] = speed
        links["average_toll_cost"] = pd.to_numeric(
            links.get("average_toll_cost", 0.0), errors="coerce"
        ).fillna(0.0)

    # Cheap weight without full cost tables: length/speed only (enough to stress pickle+pool)
    links = links.copy()
    links["length_mile"] = links.geometry.length * cons.CONV_METER_TO_MILE
    links["time_hr"] = links["length_mile"] / links["acc_speed"].replace(0, np.nan)
    links["time_cost"] = links["time_hr"]
    links["operating_cost"] = 0.0
    links["weight"] = links["time_cost"] + links["operating_cost"] + links["average_toll_cost"]
    w = links["weight"]
    log.info(
        "weight null=%s nonfinite=%s min=%s max=%s",
        int(w.isna().sum()),
        int((~np.isfinite(w)).sum()),
        float(np.nanmin(w.to_numpy())),
        float(np.nanmax(w.to_numpy())),
    )
    if int((~np.isfinite(w)).sum()) > 0:
        log.error("non-finite weights present — this can crash/hang igraph LCP workers")
        bad = links.loc[~np.isfinite(w), ["e_id", "network_source", "Speed_Limit", "length", "acc_speed"]].head(20)
        log.error("sample bad:\n%s", bad)

    import igraph

    graph_df = links[
        [
            "from_id",
            "to_id",
            "e_id",
            "weight",
            "time_cost",
            "operating_cost",
            "average_toll_cost",
            "length_mile",
        ]
    ]
    network = igraph.Graph.TupleList(
        graph_df.itertuples(index=False),
        edge_attrs=list(graph_df.columns)[2:],
        directed=False,
    )
    log.info("igraph v=%s e=%s", network.vcount(), network.ecount())

    pkl_st = time.time()
    pkl = pickle.dumps(network)
    log.info("pickle bytes=%.1f MB in %.2fs", len(pkl) / 1e6, time.time() - pkl_st)

    # Import real worker init
    from resiflow.road_revised import find_least_cost_path, worker_init_path

    # Pick a few origin names that exist
    names = network.vs["name"]
    sample_origins = [names[i] for i in (0, 10, 100, 1000, 2000) if i < len(names)]
    dests = [names[i] for i in (5, 15, 50) if i < len(names)]
    args = [(o, dests, [1.0] * len(dests)) for o in sample_origins]
    log.info("dispatch %s origins x %s dests", len(args), len(dests))

    ncpu = int(os.environ.get("DIAG_NCPU", "4"))
    log.info("spawning Pool ncpu=%s", ncpu)
    spawn_st = time.time()
    with Pool(processes=ncpu, initializer=worker_init_path, initargs=(pkl,)) as pool:
        log.info("Pool ctor returned in %.2fs — starting imap", time.time() - spawn_st)
        t0 = time.time()
        results = list(pool.imap_unordered(find_least_cost_path, args, chunksize=1))
        log.info("imap done in %.2fs results=%s", time.time() - t0, len(results))
    log.info("OK — pool workers survived")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
