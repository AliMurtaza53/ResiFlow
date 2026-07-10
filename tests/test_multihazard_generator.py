"""Tests for multihazard synthetic raster generator."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATOR = REPO_ROOT / "scripts" / "testbed" / "generate_synthetic_hazards.py"


def test_generate_synthetic_hazards_writes_manifest(tmp_path: Path) -> None:
    out = tmp_path / "toy_data"
    subprocess.run(
        [sys.executable, str(GENERATOR), "--output-dir", str(out)],
        cwd=REPO_ROOT,
        check=True,
    )
    manifest = out / "inputs" / "sioux_falls_multihazard" / "manifest.json"
    assert manifest.exists()
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert "earthquake" in data["hazards"]
    assert (out / "inputs" / "sioux_falls_multihazard" / "earthquake" / "event_1.tif").exists()
