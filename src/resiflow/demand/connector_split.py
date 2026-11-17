"""Same-share split of county OD demand across a county's official FAF5 connector road ends.

The converted FAF5 network has no centroid connectors and loads each county at one
snapped node. 257 counties have 2+ official connectors. This spreads such a county's
origin and destination demand equally over the road-side end of each connector,
leaving every other county at its current node. Conserves total flow.
"""

from __future__ import annotations

import pandas as pd


def main_component_nodes(from_ids, to_ids) -> set[str]:
    """Node ids in the largest WEAKLY connected component of the road network.

    Weak, not strong: link direction flags make strong components over-reject
    (56 of 57 split ends outside the largest strong component loaded fine in the
    pax_cty1 runs); a node outside the weak component is a true island.
    """
    import numpy as np
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    f = pd.Series(from_ids).astype(str)
    t = pd.Series(to_ids).astype(str)
    ids = pd.Index(pd.unique(pd.concat([f, t])))
    a, b = ids.get_indexer(f), ids.get_indexer(t)
    g = coo_matrix((np.ones(len(a)), (a, b)), shape=(len(ids), len(ids))).tocsr()
    _, lab = connected_components(g, directed=False)
    return set(ids[lab == np.bincount(lab).argmax()])


def build_node_targets(
    county_nodes: pd.DataFrame,
    connectors: pd.DataFrame,
    valid_nodes: set[str] | None = None,
) -> pd.DataFrame:
    """Return (node, target, weight): where the demand loaded at ``node`` is spread.

    county_nodes: columns county_fips, node_id (current single loading node).
    connectors:   columns centroid_id, road_node (one row per official connector;
                  a county's own centroid_id equals its integer FIPS).
    A node shared by two counties is left unsplit (it cannot be attributed).
    Connectors ending on the same road node count once each (same share per connector).
    """
    cn = county_nodes.copy()
    cn["county_int"] = cn["county_fips"].astype(int)
    cn["node_id"] = cn["node_id"].astype(str)
    shared = cn["node_id"].duplicated(keep=False)

    conn = connectors.loc[connectors["centroid_id"].astype(int) < 100000].copy()
    conn["county_int"] = conn["centroid_id"].astype(int)
    conn["target"] = conn["road_node"].astype(str)
    if valid_nodes is not None:
        # Drop connector ends that are not in the road network's main component
        # (stub islands); their share goes to the remaining ends. A county with
        # no valid end keeps all of its ends (and its current single node).
        ok = conn["target"].isin(valid_nodes)
        has_ok = ok.groupby(conn["county_int"]).transform("any")
        conn = conn[ok | ~has_ok]
    k = conn.groupby("county_int").size().rename("k")
    per = conn.groupby(["county_int", "target"]).size().rename("n").reset_index().merge(k, on="county_int")
    per["weight"] = per["n"] / per["k"]

    split = cn.loc[~shared].merge(per[per["k"] >= 2], on="county_int")
    split_nodes = set(split["node_id"])
    out = split[["node_id", "target", "weight"]].rename(columns={"node_id": "node"})

    keep = cn[~cn["node_id"].isin(split_nodes)][["node_id"]].drop_duplicates()
    keep = keep.rename(columns={"node_id": "node"})
    keep["target"] = keep["node"]
    keep["weight"] = 1.0
    return pd.concat([out, keep], ignore_index=True)


def split_od(
    od: pd.DataFrame,
    targets: pd.DataFrame,
    flow_col: str = "Car21",
    intrazonal: str = "keep",
) -> pd.DataFrame:
    """Spread OD flow over targets at both ends. intrazonal='keep' leaves origin==destination
    rows at their original node (dropped later by the assignment, as before); 'split'
    routes them between a county's connector ends."""
    od = od.copy()
    od["origin_node"] = od["origin_node"].astype(str)
    od["destination_node"] = od["destination_node"].astype(str)
    same = od["origin_node"] == od["destination_node"]
    held = od[same] if intrazonal == "keep" else od.iloc[0:0]
    work = od[~same] if intrazonal == "keep" else od

    o = targets.rename(columns={"node": "origin_node", "target": "o_t", "weight": "o_w"})
    d = targets.rename(columns={"node": "destination_node", "target": "d_t", "weight": "d_w"})
    x = work.merge(o, on="origin_node", how="left").merge(d, on="destination_node", how="left")
    x["o_t"] = x["o_t"].fillna(x["origin_node"])
    x["d_t"] = x["d_t"].fillna(x["destination_node"])
    x[["o_w", "d_w"]] = x[["o_w", "d_w"]].fillna(1.0)
    x[flow_col] = x[flow_col] * x["o_w"] * x["d_w"]
    x = x.groupby(["o_t", "d_t"], as_index=False)[flow_col].sum()
    x = x.rename(columns={"o_t": "origin_node", "d_t": "destination_node"})
    return pd.concat([x, held[["origin_node", "destination_node", flow_col]]], ignore_index=True)
