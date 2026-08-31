"""Regression test for a silent multi-chunk truncation bug in
realize_paths_streaming().

Root cause: to_arrow_reader()'s RecordBatchReader is tied to the specific
cursor that produced it. Any OTHER conn.execute() call on the SAME
connection while the reader is still being iterated (e.g.
_append_or_create_table()'s writes inside the loop body) silently
truncates it to just its first batch, with no error. Every existing
pipeline test uses toy-scale data that fits in a single chunk, so this
bug was invisible to the full test suite -- it shipped once already
before being caught by cross-checking real-scale convergence numbers
against wall-clock-only benchmarking (see docs/PROJECT_LOG.md).

This test forces multiple chunks over a small, fully-controlled dataset
and asserts the result is identical to a single-chunk run of the same
data -- chunk_size must never change the answer.
"""

from __future__ import annotations

import duckdb
import igraph
import pandas as pd
import pytest

from resiflow.road_revised import realize_paths_streaming


def _build_graph_and_links():
    g = igraph.Graph(directed=True)
    g.add_vertices(4)
    g.add_edges([(0, 1), (1, 2), (2, 3), (3, 0), (0, 2)])
    g.es["e_id"] = ["e0", "e1", "e2", "e3", "e4"]
    g.es["time_cost"] = [1.0, 2.0, 3.0, 4.0, 5.0]
    g.es["operating_cost"] = [0.5, 0.5, 0.5, 0.5, 0.5]
    g.es["average_toll_cost"] = [0.0, 0.0, 0.0, 0.0, 0.0]
    g.es["length_mile"] = [1.0, 1.0, 1.0, 1.0, 1.0]

    road_links = pd.DataFrame(
        {
            "e_id": ["e0", "e1", "e2", "e3", "e4"],
            "acc_capacity": [1000.0, 1000.0, 1000.0, 1000.0, 1000.0],
        }
    )
    return g, road_links


def _make_conn_with_rows(n_rows: int) -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(":memory:")
    rows = []
    paths = [[0, 1], [1, 2], [2, 3], [3, 4], [0, 4]]
    for i in range(n_rows):
        rows.append(
            {
                "od_id": i,
                "origin": f"o{i % 4}",
                "destination": f"d{i % 4}",
                "path": paths[i % len(paths)],
                "flow": 10.0 + i,
            }
        )
    df = pd.DataFrame(rows)
    conn.register("df_tmp", df)
    conn.execute(
        "CREATE TABLE temp_flow_matrix_input AS SELECT * FROM df_tmp"
    )
    conn.unregister("df_tmp")
    return conn


@pytest.mark.parametrize("chunk_size", [1, 2, 3, 1000])
def test_realize_paths_streaming_result_independent_of_chunk_size(chunk_size):
    """Total assigned flow and row counts must not depend on chunk_size."""
    n_rows = 11  # deliberately not a multiple of any tested chunk_size
    network, road_links = _build_graph_and_links()
    conn = _make_conn_with_rows(n_rows)

    realize_paths_streaming(
        network,
        road_links,
        conn,
        chunk_size=chunk_size,
        create_full_temp_flow_matrix=True,
    )

    od_rows = conn.execute("SELECT COUNT(*), SUM(flow) FROM temp_flow_matrix").fetchone()
    edge_rows = conn.execute(
        "SELECT COUNT(*), SUM(total_candidate_flow) FROM temp_edge_flow"
    ).fetchone()

    assert od_rows[0] == n_rows, (
        f"chunk_size={chunk_size}: expected {n_rows} od rows in temp_flow_matrix, "
        f"got {od_rows[0]} -- multi-chunk truncation regression"
    )
    expected_total_flow = sum(10.0 + i for i in range(n_rows))
    assert od_rows[1] == pytest.approx(expected_total_flow), (
        f"chunk_size={chunk_size}: total flow mismatch -- {od_rows[1]} vs "
        f"expected {expected_total_flow}"
    )
    assert edge_rows[0] > 0, f"chunk_size={chunk_size}: no edge flow rows written"
