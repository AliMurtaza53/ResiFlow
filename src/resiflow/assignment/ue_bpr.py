"""BPR user-equilibrium traffic assignment (Frank-Wolfe)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable

import numpy as np
import pandas as pd

from resiflow.networks.tntp import read_tntp_links, read_tntp_trips


@dataclass
class UELink:
    tail: str
    head: str
    capacity: float
    free_flow_time: float
    alpha: float = 0.15
    beta: float = 4.0
    flow: float = 0.0
    cost: float = 0.0

    @property
    def key(self) -> tuple[str, str]:
        return (self.tail, self.head)

    def travel_time(self, flow: float | None = None) -> float:
        x = max(0.0, self.flow if flow is None else flow)
        if self.capacity <= 0:
            return self.free_flow_time
        ratio = x / self.capacity
        if ratio <= 0:
            return self.free_flow_time
        return self.free_flow_time * (1.0 + self.alpha * (ratio**self.beta))

    def update_cost(self) -> float:
        self.cost = self.travel_time()
        return self.cost


@dataclass
class UEResult:
    link_flows: pd.DataFrame
    relative_gap: float
    iterations: int
    converged: bool
    history: list[float] = field(default_factory=list)


def _build_graph(links: Iterable[UELink]) -> tuple[dict[str, list[UELink]], dict[tuple[str, str], UELink]]:
    outgoing: dict[str, list[UELink]] = defaultdict(list)
    link_by_key: dict[tuple[str, str], UELink] = {}
    for link in links:
        outgoing[link.tail].append(link)
        link_by_key[link.key] = link
    return outgoing, link_by_key


def _dijkstra(origin: str, outgoing: dict[str, list[UELink]]) -> tuple[dict[str, float], dict[str, str | None]]:
    dist: dict[str, float] = {origin: 0.0}
    prev: dict[str, str | None] = {origin: None}
    visited: set[str] = set()
    while len(visited) < len(dist):
        node = min((n for n in dist if n not in visited), key=dist.get)
        visited.add(node)
        for link in outgoing.get(node, []):
            alt = dist[node] + link.cost
            if link.head not in dist or alt < dist[link.head]:
                dist[link.head] = alt
                prev[link.head] = node
    return dist, prev


def _aon_assignment(
    od: pd.DataFrame,
    outgoing: dict[str, list[UELink]],
    link_by_key: dict[tuple[str, str], UELink],
    *,
    flow_col: str = "Car21",
) -> dict[tuple[str, str], float]:
    aux: dict[tuple[str, str], float] = defaultdict(float)
    for row in od.itertuples(index=False):
        origin = str(row.origin_node)
        dest = str(row.destination_node)
        demand = float(getattr(row, flow_col))
        if demand <= 0 or origin == dest:
            continue
        dist, prev = _dijkstra(origin, outgoing)
        if dest not in dist:
            continue
        node = dest
        while prev[node] is not None:
            parent = prev[node]
            assert parent is not None
            aux[(parent, node)] += demand
            node = parent
    return aux


def _relative_gap(links: list[UELink], od: pd.DataFrame, *, flow_col: str = "Car21") -> float:
    total_travel = sum(link.flow * link.cost for link in links)
    if total_travel <= 0:
        return 0.0
    outgoing, _ = _build_graph(links)
    min_cost_sum = 0.0
    for row in od.itertuples(index=False):
        origin = str(row.origin_node)
        dest = str(row.destination_node)
        demand = float(getattr(row, flow_col))
        if demand <= 0 or origin == dest:
            continue
        dist, _ = _dijkstra(origin, outgoing)
        if dest in dist:
            min_cost_sum += demand * dist[dest]
    return max(0.0, 1.0 - min_cost_sum / total_travel)


def links_from_tntp(links_df: pd.DataFrame) -> list[UELink]:
    return [
        UELink(
            tail=str(row.init_node),
            head=str(row.term_node),
            capacity=float(row.capacity),
            free_flow_time=float(row.free_flow_time),
            alpha=float(row.b),
            beta=float(row.power),
        )
        for row in links_df.itertuples(index=False)
    ]


def solve_user_equilibrium(
    links: list[UELink],
    od: pd.DataFrame,
    *,
    flow_col: str = "Car21",
    max_iterations: int = 500,
    target_gap: float = 1e-4,
) -> UEResult:
    """Frank-Wolfe user-equilibrium assignment with BPR travel times."""
    outgoing, link_by_key = _build_graph(links)
    history: list[float] = []

    for link in links:
        link.flow = 0.0
        link.update_cost()

    converged = False
    iterations = 0
    for iteration in range(1, max_iterations + 1):
        iterations = iteration
        aux = _aon_assignment(od, outgoing, link_by_key, flow_col=flow_col)

        if iteration == 1:
            for key, link in link_by_key.items():
                link.flow = aux.get(key, 0.0)
                link.update_cost()
        else:
            # Frank-Wolfe step size via fixed step 2/(k+2) (MSA-style) for stability on test nets.
            step = 2.0 / (iteration + 2.0)
            for key, link in link_by_key.items():
                target = aux.get(key, 0.0)
                link.flow = (1.0 - step) * link.flow + step * target
                link.update_cost()

        gap = _relative_gap(links, od, flow_col=flow_col)
        history.append(gap)
        if gap <= target_gap:
            converged = True
            break

    rows = [
        {
            "init_node": link.tail,
            "term_node": link.head,
            "ue_flow": link.flow,
            "ue_cost": link.cost,
            "capacity": link.capacity,
            "free_flow_time": link.free_flow_time,
        }
        for link in links
    ]
    return UEResult(
        link_flows=pd.DataFrame(rows),
        relative_gap=history[-1] if history else 0.0,
        iterations=iterations,
        converged=converged,
        history=history,
    )


def solve_tntp_user_equilibrium(
    net_path: str,
    trips_path: str,
    *,
    demand_scale: float = 1.0,
    node_id_formatter=None,
    **kwargs,
) -> UEResult:
    """Convenience: TNTP net + trips files → UE link flows."""
    links = links_from_tntp(read_tntp_links(net_path))
    od = read_tntp_trips(trips_path, node_id_formatter=node_id_formatter)
    if demand_scale != 1.0:
        od = od.copy()
        od["Car21"] = od["Car21"] * float(demand_scale)
    return solve_user_equilibrium(links, od, **kwargs)
