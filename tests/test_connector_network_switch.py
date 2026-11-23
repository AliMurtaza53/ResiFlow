"""Every stage that loads the FAF5 road links must honour RESIFLOW_FAF5_CONNECTOR_NETWORK.

A stage that silently falls back to the base network drops the 3,795 class-50 connectors: in Stage 1 that isolated 99.6% of demand
(2026-11-23 smoke baseline), and in Stages 2-3 it would hide virtual links from the exemption guards.
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LOADERS = [
    "scripts/1_network_flow_model_revision.py",
    "scripts/3_damage_analysis.py",
    "src/resiflow/disruption/pipeline.py",
    "src/resiflow/disruption/pipeline_intensity.py",
]


@pytest.mark.parametrize("rel", LOADERS)
def test_loader_honours_connector_network_switch(rel):
    text = (ROOT / rel).read_text(encoding="utf-8")
    assert 'os.environ.get("RESIFLOW_FAF5_CONNECTOR_NETWORK")' in text
    assert "import os" in text
