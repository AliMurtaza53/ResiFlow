"""Assert OD-style node tokens resolve by name via _name_to_idx, not as indices."""
from __future__ import annotations

import pickle
import sys

import igraph

sys.path.insert(0, "src")
import resiflow.road_revised as rr  # noqa: E402
from resiflow.road_revised import (  # noqa: E402
    _igraph_vertex_index,
    _rebuild_name_to_idx,
    refresh_worker_network,
    worker_init_path,
)


def main() -> None:
    # Names deliberately NOT equal to indices: name 600000 at index 0.
    g = igraph.Graph(n=3, directed=False)
    g.vs["name"] = [600000, 42, 7]
    g.add_edges([(0, 1), (1, 2)])
    g.es["weight"] = [1.0, 1.0]

    _rebuild_name_to_idx(g)
    assert rr._name_to_idx[600000] == 0
    assert rr._name_to_idx["600000"] == 0
    assert _igraph_vertex_index(g, 600000) == 0
    assert _igraph_vertex_index(g, "600000") == 0
    assert _igraph_vertex_index(g, 42) == 1

    path = g.get_shortest_paths(
        v=_igraph_vertex_index(g, 600000),
        to=[_igraph_vertex_index(g, 7)],
        weights="weight",
        output="epath",
    )
    assert path == [[0, 1]], path

    # worker_init_path builds the map from a pickled network
    rr._name_to_idx = {}
    worker_init_path(pickle.dumps(g))
    assert rr._name_to_idx[600000] == 0

    # refresh_worker_network must rebuild (assert inside + verify new names)
    g2 = igraph.Graph(n=2, directed=False)
    g2.vs["name"] = [900001, 900002]
    g2.add_edges([(0, 1)])
    g2.es["weight"] = [1.0]
    refresh_worker_network(pickle.dumps(g2))
    assert 900001 in rr._name_to_idx or "900001" in rr._name_to_idx
    assert 600000 not in rr._name_to_idx  # stale map must be gone
    print("check_igraph_name_lookup: OK")


if __name__ == "__main__":
    main()
