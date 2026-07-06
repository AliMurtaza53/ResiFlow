"""Tests for RESIFLOW_* / NIRD_* configuration shims."""

from __future__ import annotations

import pytest

from resiflow.config import config_path, get_env, results_variant
from resiflow.utils import get_results_variant, load_config


def test_get_env_prefers_resiflow(monkeypatch) -> None:
    monkeypatch.setenv("RESIFLOW_RESULTS_VARIANT", "from_resiflow")
    monkeypatch.setenv("NIRD_RESULTS_VARIANT", "from_nird")
    assert get_env("RESIFLOW_RESULTS_VARIANT", "NIRD_RESULTS_VARIANT") == "from_resiflow"


def test_get_env_falls_back_to_nird(monkeypatch) -> None:
    monkeypatch.delenv("RESIFLOW_RESULTS_VARIANT", raising=False)
    monkeypatch.setenv("NIRD_RESULTS_VARIANT", "from_nird")
    assert get_env("RESIFLOW_RESULTS_VARIANT", "NIRD_RESULTS_VARIANT") == "from_nird"


def test_config_path_alias(monkeypatch, tmp_path) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text('{"paths": {"soge_clusters": "C:/data"}}', encoding="utf-8")
    monkeypatch.delenv("RESIFLOW_CONFIG_PATH", raising=False)
    monkeypatch.setenv("NIRD_CONFIG_PATH", str(cfg))
    assert config_path() == str(cfg)
    loaded = load_config()
    assert loaded["paths"]["soge_clusters"] == "C:/data"


def test_results_variant_alias(monkeypatch) -> None:
    monkeypatch.delenv("RESIFLOW_RESULTS_VARIANT", raising=False)
    monkeypatch.setenv("NIRD_RESULTS_VARIANT", "toy_sioux_falls")
    assert results_variant() == "toy_sioux_falls"
    assert get_results_variant() == "toy_sioux_falls"
