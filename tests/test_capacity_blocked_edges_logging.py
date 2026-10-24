import logging

import pandas as pd

from resiflow.road_revised import _log_capacity_blocked_edges


def _fixtures():
    temp_edge_flow = pd.DataFrame({
        "e_id": ["e1", "e2", "e3"],
        "acc_capacity": [500.0, 50.0, 0.5],
        "current_capacity": [1000.0, 1000.0, 1000.0],
    })
    road_links_valid = pd.DataFrame({
        "e_id": ["e1", "e2", "e3"],
        "Road_Name": ["MAIN ST", "ELM ST", "OAK ST"],
        "assignment_tier": ["arterial", "arterial", "local_access"],
        "lanes": [2, 2, 1],
    })
    mask = pd.Series([False, True, True])
    return temp_edge_flow, road_links_valid, mask


def test_capacity_blocked_edges_silent_by_default(caplog, monkeypatch):
    monkeypatch.delenv("RESIFLOW_LOG_CAPACITY_BLOCKED_EDGES", raising=False)
    temp_edge_flow, road_links_valid, mask = _fixtures()
    with caplog.at_level(logging.INFO):
        _log_capacity_blocked_edges(1, temp_edge_flow, road_links_valid, mask)
    assert caplog.text == ""


def test_capacity_blocked_edges_logs_dropped_edges_when_enabled(caplog, monkeypatch):
    monkeypatch.setenv("RESIFLOW_LOG_CAPACITY_BLOCKED_EDGES", "1")
    temp_edge_flow, road_links_valid, mask = _fixtures()
    with caplog.at_level(logging.INFO):
        _log_capacity_blocked_edges(3, temp_edge_flow, road_links_valid, mask)
    assert "ELM ST" in caplog.text
    assert "OAK ST" in caplog.text
    assert "MAIN ST" not in caplog.text  # e1 not dropped (mask is False)
    assert "2 total dropped" in caplog.text


def test_capacity_blocked_edges_ranks_by_acc_capacity_descending(caplog, monkeypatch):
    monkeypatch.setenv("RESIFLOW_LOG_CAPACITY_BLOCKED_EDGES", "1")
    temp_edge_flow, road_links_valid, mask = _fixtures()
    with caplog.at_level(logging.INFO):
        _log_capacity_blocked_edges(3, temp_edge_flow, road_links_valid, mask)
    elm_pos = caplog.text.find("ELM ST")
    oak_pos = caplog.text.find("OAK ST")
    assert 0 <= elm_pos < oak_pos  # higher acc_capacity (50.0) logged before lower (0.5)


def test_capacity_blocked_edges_never_raises_on_bad_input(monkeypatch):
    monkeypatch.setenv("RESIFLOW_LOG_CAPACITY_BLOCKED_EDGES", "1")
    # missing columns, mismatched mask length -- should log an exception, not raise
    _log_capacity_blocked_edges(1, pd.DataFrame(), pd.DataFrame(), pd.Series([True]))
