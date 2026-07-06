"""Registered TNTP / toy testbed definitions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_TESTBEDS_DIR = _REPO_ROOT / "parameters" / "testbeds"


@dataclass(frozen=True)
class TestbedSpec:
    testbed_id: str
    description: str
    network_source: str
    data_dir: Path
    net_file: str
    node_file: str
    trips_file: str
    reference_geojson: str | None = None
    node_id_prefix: str = ""
    source_crs: str = "EPSG:4326"
    output_crs: str = "EPSG:9311"
    demand_scale: float = 1.0
    freight_share_of_passenger: float = 0.0
    results_variant: str = ""
    flooded_physical_pair: tuple[str, str] | None = None
    bridge_physical_pairs: tuple[tuple[str, str], ...] = ()

    def node_id_formatter(self):
        prefix = self.node_id_prefix

        def _fmt(raw: str | int) -> str:
            return f"{prefix}{raw}"

        return _fmt

    def net_path(self) -> Path:
        return self.data_dir / self.net_file

    def node_path(self) -> Path:
        return self.data_dir / self.node_file

    def trips_path(self) -> Path:
        return self.data_dir / self.trips_file


def _resolve_data_dir(raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute():
        return path
    return (_REPO_ROOT / path).resolve()


def load_testbed(testbed_id: str, *, testbeds_dir: Path | None = None) -> TestbedSpec:
    root = testbeds_dir or _TESTBEDS_DIR
    path = root / f"{testbed_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Unknown testbed {testbed_id!r}: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    bridge_pairs = tuple(tuple(pair) for pair in raw.get("bridge_physical_pairs", []))
    flooded = raw.get("flooded_physical_pair")
    return TestbedSpec(
        testbed_id=raw["testbed_id"],
        description=raw.get("description", ""),
        network_source=raw.get("network_source", "tntp"),
        data_dir=_resolve_data_dir(raw["data_dir"]),
        net_file=raw["net_file"],
        node_file=raw["node_file"],
        trips_file=raw["trips_file"],
        reference_geojson=raw.get("reference_geojson"),
        node_id_prefix=raw.get("node_id_prefix", ""),
        source_crs=raw.get("source_crs", "EPSG:4326"),
        output_crs=raw.get("output_crs", "EPSG:9311"),
        demand_scale=float(raw.get("demand_scale", 1.0)),
        freight_share_of_passenger=float(raw.get("freight_share_of_passenger", 0.0)),
        results_variant=raw.get("results_variant", f"toy_{testbed_id}"),
        flooded_physical_pair=tuple(flooded) if flooded else None,
        bridge_physical_pairs=bridge_pairs,
    )


def list_testbeds(*, testbeds_dir: Path | None = None) -> list[str]:
    root = testbeds_dir or _TESTBEDS_DIR
    return sorted(path.stem for path in root.glob("*.json"))
