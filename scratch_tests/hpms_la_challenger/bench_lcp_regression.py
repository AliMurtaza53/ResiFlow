"""Minute-scale BEFORE vs AFTER LCP microbench (lookup tax, Dijkstra, Pool e2e, gate).

Runs under nird on Hopper. Uses real Pool(spawn)+worker_init_path for e2e/gate
so per-worker pickle unpickle + _name_to_idx rebuild cost is included.
"""
from __future__ import annotations

import logging
import pickle
import sys
import time
from multiprocessing import Pool, set_start_method
from pathlib import Path

import geopandas as gpd
import igraph
import numpy as np
import pandas as pd

sys.path.insert(0, "/scratch/akothaw/multimodal_hazard_data/code/ResiFlow/src")
from resiflow import constants as cons
from resiflow.road_revised import (  # noqa: E402
    _rebuild_name_to_idx,
    find_least_cost_path,
    refresh_worker_network,
    worker_init_path,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("bench")

BEFORE = Path("/scratch/akothaw/multimodal_hazard_data/soge_clusters/networks/faf5")
AFTER = Path(
    "/scratch/akothaw/multimodal_hazard_data/scratch_tests/hpms_la_challenger/"
    "isolated_base/networks/faf5"
)
OD_AFTER = Path(
    "/scratch/akothaw/multimodal_hazard_data/scratch_tests/hpms_la_challenger/"
    "passenger_od_hpms_la.pq"
)


def _build_igraph(links_path: Path) -> igraph.Graph:
    links = gpd.read_parquet(links_path)
    speed = (
        pd.to_numeric(links["Speed_Limit"], errors="coerce")
        .where(lambda s: s > 0)
        .fillna(45.0)
    )
    links = links.copy()
    links["acc_speed"] = speed
    links["average_toll_cost"] = pd.to_numeric(
        links.get("average_toll_cost", 0.0), errors="coerce"
    ).fillna(0.0)
    links["length_mile"] = links.geometry.length * cons.CONV_METER_TO_MILE
    links["weight"] = links["length_mile"] / links["acc_speed"] + links["average_toll_cost"]
    graph_df = links[
        [
            "from_id",
            "to_id",
            "e_id",
            "weight",
            "average_toll_cost",
            "length_mile",
        ]
    ]
    # pad attrs expected by production TupleList shape loosely
    graph_df = graph_df.assign(time_cost=graph_df["weight"], operating_cost=0.0)
    graph_df = graph_df[
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
    g = igraph.Graph.TupleList(
        graph_df.itertuples(index=False),
        edge_attrs=list(graph_df.columns)[2:],
        directed=False,
    )
    return g


def _lookup_tax(g: igraph.Graph, tokens: list, label: str) -> None:
    names = list(g.vs["name"])
    # vs.find baseline
    t0 = time.perf_counter()
    for tok in tokens:
        try:
            g.vs.find(name=tok)
        except ValueError:
            g.vs.find(name=int(tok) if not isinstance(tok, int) else str(tok))
    find_ms = (time.perf_counter() - t0) * 1e3
    # dict
    t0 = time.perf_counter()
    _rebuild_name_to_idx(g)
    build_ms = (time.perf_counter() - t0) * 1e3
    import resiflow.road_revised as rr

    t0 = time.perf_counter()
    for tok in tokens:
        _ = rr._name_to_idx[tok] if tok in rr._name_to_idx else rr._name_to_idx[str(tok)]
    dict_ms = (time.perf_counter() - t0) * 1e3
    log.info(
        "LOOKUP_TAX[%s] n=%s find_ms=%.1f dict_build_ms=%.1f dict_resolve_ms=%.1f "
        "find/dict=%.0fx",
        label,
        len(tokens),
        find_ms,
        build_ms,
        dict_ms,
        find_ms / max(dict_ms, 1e-9),
    )


def _dijkstra_and_paths(g: igraph.Graph, origin_name, dest_names: list, label: str) -> None:
    _rebuild_name_to_idx(g)
    import resiflow.road_revised as rr

    o = rr._name_to_idx[origin_name] if origin_name in rr._name_to_idx else rr._name_to_idx[str(origin_name)]
    dest_idx = []
    for d in dest_names:
        if d in rr._name_to_idx:
            dest_idx.append(rr._name_to_idx[d])
        elif str(d) in rr._name_to_idx:
            dest_idx.append(rr._name_to_idx[str(d)])
    t0 = time.perf_counter()
    paths = g.get_shortest_paths(v=o, to=dest_idx, weights="weight", mode="out", output="epath")
    dij_ms = (time.perf_counter() - t0) * 1e3
    lengths = [len(p) for p in paths]
    log.info(
        "DIJKSTRA[%s] dests=%s dij_ms=%.1f mean_path_edges=%.1f max_path_edges=%s",
        label,
        len(dest_idx),
        dij_ms,
        float(np.mean(lengths)) if lengths else 0.0,
        max(lengths) if lengths else 0,
    )


def _pool_e2e(g: igraph.Graph, args: list, label: str, ncpu: int = 4) -> float:
    """Real spawn Pool + worker_init_path (pickle + _name_to_idx rebuild in workers)."""
    pkl = pickle.dumps(g)
    log.info("POOL_E2E[%s] pickle_mb=%.1f tasks=%s ncpu=%s", label, len(pkl) / 1e6, len(args), ncpu)
    t0 = time.perf_counter()
    with Pool(processes=ncpu, initializer=worker_init_path, initargs=(pkl,)) as pool:
        # also exercise refresh path once (persistent-pool analogue)
        pool.map(refresh_worker_network, [pkl] * ncpu)
        n = 0
        for _ in pool.imap_unordered(find_least_cost_path, args, chunksize=1):
            n += 1
    sec = time.perf_counter() - t0
    log.info("POOL_E2E[%s] tasks=%s wall_s=%.2f per_task_s=%.3f", label, n, sec, sec / max(n, 1))
    return sec


def main() -> int:
    try:
        set_start_method("spawn")
    except RuntimeError:
        pass

    log.info("Building BEFORE igraph...")
    t0 = time.perf_counter()
    g_b = _build_igraph(BEFORE / "faf5_road_links.gpq")
    log.info("BEFORE v=%s e=%s build_s=%.1f", g_b.vcount(), g_b.ecount(), time.perf_counter() - t0)

    log.info("Building AFTER igraph...")
    t0 = time.perf_counter()
    g_a = _build_igraph(AFTER / "faf5_road_links.gpq")
    log.info("AFTER v=%s e=%s build_s=%.1f", g_a.vcount(), g_a.ecount(), time.perf_counter() - t0)

    # Shared CONUS origin present in both: use a mid-range FAF name in BEFORE
    names_b = set(g_b.vs["name"])
    names_b_str = {str(x) for x in names_b}
    # pick origin 100024 if present else first common
    origin = 100024 if 100024 in names_b else next(iter(names_b))
    dests = [n for n in list(g_b.vs["name"])[100:3100]]
    dests = [d for d in dests if (d in names_b or str(d) in names_b_str)][:3000]
    log.info("bench origin=%s n_dests=%s", origin, len(dests))

    # --- 1 lookup tax ---
    tokens = [origin] + dests
    _lookup_tax(g_b, tokens, "BEFORE")
    # AFTER: same tokens that exist there
    names_a = set(g_a.vs["name"])
    tokens_a = [t for t in tokens if t in names_a or str(t) in {str(x) for x in names_a}]
    _lookup_tax(g_a, tokens_a, "AFTER")

    # --- 2+3 dijkstra + path size ---
    dests_both = [d for d in dests if d in names_a or str(d) in {str(x) for x in names_a}][:2000]
    _dijkstra_and_paths(g_b, origin, dests_both, "BEFORE")
    _dijkstra_and_paths(g_a, origin, dests_both, "AFTER")

    # --- 4 Pool e2e: 20 origins x dest fanout through real worker_init ---
    od = pd.read_parquet(OD_AFTER)
    od["origin_node"] = od["origin_node"].astype(str)
    od["destination_node"] = od["destination_node"].astype(str)
    # FAF-only origins (no centroids) that exist on BEFORE
    grp = (
        od[~od["origin_node"].str.startswith("600")]
        .groupby("origin_node")["destination_node"]
        .apply(list)
    )
    args_20 = []
    for o, ds in grp.items():
        oi = int(o) if o.isdigit() else o
        if oi not in names_b and o not in names_b_str:
            continue
        ds_f = []
        for d in ds[:500]:
            di = int(d) if d.isdigit() else d
            if di in names_b or d in names_b_str:
                ds_f.append(di if di in names_b else d)
        if len(ds_f) < 10:
            continue
        args_20.append((oi if oi in names_b else o, ds_f, [1.0] * len(ds_f)))
        if len(args_20) >= 20:
            break
    log.info("e2e args_20 origins=%s mean_dests=%.0f", len(args_20), np.mean([len(a[1]) for a in args_20]))
    _pool_e2e(g_b, args_20, "BEFORE_20", ncpu=4)
    # AFTER args: same origins/dests that exist on AFTER
    args_20_a = []
    for o, ds, fl in args_20:
        ds_a = [d for d in ds if d in names_a or str(d) in {str(x) for x in names_a}]
        if ds_a:
            args_20_a.append((o, ds_a, fl[: len(ds_a)]))
    _pool_e2e(g_a, args_20_a, "AFTER_20", ncpu=4)

    # --- GATE: 200 origins via real Pool ---
    args_200 = []
    for o, ds in grp.items():
        oi = int(o) if o.isdigit() else o
        if oi not in names_b and o not in names_b_str:
            continue
        ds_f = []
        for d in ds[:800]:
            di = int(d) if d.isdigit() else d
            if di in names_b or d in names_b_str:
                ds_f.append(di if di in names_b else d)
        if len(ds_f) < 5:
            continue
        args_200.append((oi if oi in names_b else o, ds_f, [1.0] * len(ds_f)))
        if len(args_200) >= 200:
            break
    log.info("GATE args_200=%s", len(args_200))
    sec_b = _pool_e2e(g_b, args_200, "GATE_BEFORE_200", ncpu=8)
    args_200_a = []
    for o, ds, fl in args_200:
        ds_a = [d for d in ds if d in names_a or str(d) in {str(x) for x in names_a}]
        if ds_a:
            args_200_a.append((o, ds_a, fl[: len(ds_a)]))
    sec_a = _pool_e2e(g_a, args_200_a, "GATE_AFTER_200", ncpu=8)
    ratio = sec_a / max(sec_b, 1e-9)
    log.info(
        "GATE_RATIO AFTER/BEFORE=%.2fx (pass if <=2.0; edges ratio=%.2f)",
        ratio,
        g_a.ecount() / max(g_b.ecount(), 1),
    )
    if ratio <= 2.0:
        log.info("GATE PASS")
        return 0
    log.error("GATE FAIL — densification scope / residual regression")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
