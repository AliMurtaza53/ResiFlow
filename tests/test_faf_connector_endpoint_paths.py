import pickle

import igraph
import pytest

from resiflow import road_revised as road
from resiflow.networks.tntp import read_tntp_links, read_tntp_trips
from resiflow.testbeds import load_testbed


@pytest.mark.parametrize("worker", ["local", "spawn", "refresh"])
def test_faf_connector_paths_use_only_endpoint_centroids(worker, monkeypatch):
    # A and B are road vertices. C has an exit at each road vertex.
    # Traversing C would cost 2 versus 10 for the physical road.
    graph = igraph.Graph(edges=[(0, 1), (0, 2), (1, 2)], directed=False)
    graph.vs["name"] = ["101", "102", "900"]
    graph.vs["faf_centroid"] = [False, False, True]
    graph.es["weight"] = [10.0, 1.0, 1.0]
    monkeypatch.setattr(road, "shared_network", None)
    monkeypatch.setattr(road, "_name_to_idx", {})
    monkeypatch.setattr(road, "_arrival_by_departure", {})
    monkeypatch.setattr(road, "_routing_arc_to_edge", [])

    def install(network):
        if worker == "local":
            road._set_worker_network(network)
        elif worker == "spawn":
            road.worker_init_path(pickle.dumps(network))
        else:
            road.refresh_worker_network(pickle.dumps(network))

    install(graph)
    assert road.find_least_cost_path((101, [102, 900], [1, 1]))[2] == [[0], [1]]
    assert road.find_least_cost_path((102, [101, 900], [1, 1]))[2] == [[0], [2]]
    assert road.find_least_cost_path((900, [101, 102, 900], [1, 1, 1]))[2] == [[1], [2], []]

    # Closure or pruning renumbers physical edges. Both routing directions
    # share one physical index and removed links disappear in both directions.
    graph.delete_edges([0])
    install(graph)
    with pytest.warns(RuntimeWarning, match="Couldn't reach"):
        assert road.find_least_cost_path((101, [102], [1]))[2] == [[]]
    assert road.find_least_cost_path((900, [101, 102], [1, 1]))[2] == [[0], [1]]

    del graph.vs["faf_centroid"]
    install(graph)
    assert road.find_least_cost_path((101, [102], [1]))[2] == [[0, 1]]


@pytest.mark.parametrize("close_origin", [False, True])
def test_anaheim_endpoint_paths(close_origin, monkeypatch):
    spec = load_testbed("anaheim")
    links = read_tntp_links(spec.net_path())
    trips = read_tntp_trips(spec.trips_path())
    monkeypatch.setattr(road, "shared_network", None)
    monkeypatch.setattr(road, "_name_to_idx", {})
    monkeypatch.setattr(road, "_arrival_by_departure", {})
    monkeypatch.setattr(road, "_routing_arc_to_edge", [])
    graph = igraph.Graph.TupleList(
        ((str(a), str(b)) for a, b in zip(links.init_node, links.term_node)), directed=False
    )
    graph.vs["faf_centroid"] = [int(node) <= 38 for node in graph.vs["name"]]
    graph.es["weight"] = [1.0] * graph.ecount()
    if close_origin:
        graph.delete_edges(graph.incident(graph.vs.find(name="1")))
    road._set_worker_network(graph)
    endpoints = graph.get_edgelist()
    delivered = isolated = 0.0
    for origin, rows in trips[trips.Car21.gt(0)].groupby("origin_node"):
        destinations = rows.destination_node.tolist()
        _, _, paths, flows = road.find_least_cost_path((origin, destinations, rows.Car21.tolist()))
        for destination, path, flow in zip(destinations, paths, flows):
            for edge in path:
                for vertex in endpoints[edge]:
                    node = graph.vs[vertex]["name"]
                    assert int(node) > 38 or node in {str(origin), str(destination)}
            if path or str(origin) == str(destination):
                delivered += flow
            else:
                isolated += flow
    assert delivered + isolated == pytest.approx(trips.Car21.sum())
    assert (isolated > 0) == close_origin
