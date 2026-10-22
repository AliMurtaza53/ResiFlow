import pandas as pd

import importlib.util
import sys
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "inspect_node_catchment",
    Path(__file__).resolve().parents[1] / "scripts" / "inspect_node_catchment.py",
)
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)

direct_edges = _MODULE.direct_edges
one_hop_neighbors = _MODULE.one_hop_neighbors
downstream_edges = _MODULE.downstream_edges


def _sample_road_links() -> pd.DataFrame:
    # n1 is the node of interest; n2/n3 are its direct neighbors;
    # n4/n5 are two hops away (only reachable through n2/n3).
    return pd.DataFrame(
        {
            "e_id": [1, 2, 3, 4],
            "from_id": ["n1", "n1", "n2", "n3"],
            "to_id": ["n2", "n3", "n4", "n5"],
        }
    )


def test_direct_edges_matches_either_endpoint():
    road_links = _sample_road_links()
    result = direct_edges(road_links, "n1")
    assert set(result["e_id"]) == {1, 2}


def test_one_hop_neighbors_excludes_self():
    road_links = _sample_road_links()
    touching = direct_edges(road_links, "n1")
    neighbors = one_hop_neighbors(touching, "n1")
    assert neighbors == {"n2", "n3"}


def test_downstream_edges_excludes_direct_edges():
    road_links = _sample_road_links()
    neighbors = {"n2", "n3"}
    downstream = downstream_edges(road_links, "n1", neighbors)
    # edges 1 and 2 (n1's own direct edges) must be excluded even though
    # they also touch n2/n3; only the genuinely one-hop-further edges 3/4 remain
    assert set(downstream["e_id"]) == {3, 4}
