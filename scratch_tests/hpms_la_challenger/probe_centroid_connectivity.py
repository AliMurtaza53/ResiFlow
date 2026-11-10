"""Can each LA centroid reach a sample of national FAF nodes on the AFTER graph?"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import geopandas as gpd
import igraph
import numpy as np
import pandas as pd

sys.path.insert(0, "/scratch/akothaw/multimodal_hazard_data/code/ResiFlow/src")
from resiflow import constants as cons

ROOT = Path("/scratch/akothaw/multimodal_hazard_data/scratch_tests/hpms_la_challenger")
ISO = ROOT / "isolated_base/networks/faf5"
MAN = json.loads((ROOT / "splice_manifest.json").read_text())


def build_g() -> igraph.Graph:
    links = gpd.read_parquet(ISO / "faf5_road_links.gpq")
    speed = (
        pd.to_numeric(links["Speed_Limit"], errors="coerce").where(lambda s: s > 0).fillna(45.0)
    )
    links = links.copy()
    links["weight"] = links.geometry.length * cons.CONV_METER_TO_MILE / speed
    links["weight"] = links["weight"].replace([np.inf, -np.inf], np.nan).fillna(1e6)
    gdf = links[["from_id", "to_id", "e_id", "weight"]]
    return igraph.Graph.TupleList(
        gdf.itertuples(index=False), edge_attrs=["e_id", "weight"], directed=False
    )


def main() -> int:
    g = build_g()
    name_to_idx = {n: i for i, n in enumerate(g.vs["name"])}
    name_to_idx.update({str(n): i for n, i in list(name_to_idx.items())})
    # sample national destinations (FAF ids well below 500k)
    faf_names = [n for n in g.vs["name"] if isinstance(n, (int, np.integer)) and int(n) < 400000]
    rng = np.random.default_rng(0)
    sample = list(rng.choice(faf_names, size=min(50, len(faf_names)), replace=False))
    sample_idx = [name_to_idx[s] for s in sample]

    print(f"graph v={g.vcount()} e={g.ecount()} sample_dests={len(sample)}")
    for label, mp in (("home", MAN["home_map"]), ("work", MAN["work_map"])):
        for old, new in mp.items():
            cid = int(new)
            if cid not in name_to_idx and str(cid) not in name_to_idx:
                print(f"  MISS {label} {old}->{cid} not in graph")
                continue
            oi = name_to_idx.get(cid, name_to_idx.get(str(cid)))
            t0 = time.perf_counter()
            paths = g.get_shortest_paths(oi, to=sample_idx, weights="weight", output="epath")
            reachable = sum(1 for p in paths if len(p) > 0)
            # also degree of centroid
            deg = g.degree(oi)
            print(
                f"  {label} {old}->{cid}: degree={deg} "
                f"reach {reachable}/{len(sample)} national sample "
                f"({time.perf_counter()-t0:.2f}s)"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
