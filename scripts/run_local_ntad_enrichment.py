#!/usr/bin/env python3
"""One-shot local enrichment: convert FAF, load NTAD, build indices, patch siblings.

Does NOT overwrite a production faf5_road_links.gpq elsewhere — writes under
Desktop/data/faf5_data/network_data/enrichment/ only.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import geopandas as gpd

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src"
sys.path.insert(0, str(SRC))

from resiflow.preprocess.faf5_network import convert_faf5_links  # noqa: E402

DATA = Path(r"C:\Users\akothaw\Desktop\data\faf5_data")
NET = DATA / "network_data"
OUT = NET / "enrichment"
GDB = NET / "FAF5Network.gdb"
NBI_GPKG = next(DATA.glob("NTAD_National_Bridge_Inventory_*.gpkg"))
NTI_GPKG = next(DATA.glob("NTAD_National_Tunnel_Inventory_*.gpkg"))
HPMS_CSV = NET / "hpms_transfer" / "faf_hpms_lrs_enriched.csv"
PY = REPO / ".venv" / "Scripts" / "python.exe"


def run(args: list[str]) -> None:
    print("\n>>", " ".join(str(a) for a in args), flush=True)
    subprocess.check_call([str(PY), *args], cwd=str(REPO))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    links_path = OUT / "faf5_road_links.gpq"
    if not links_path.exists():
        print("Converting FAF5 GDB -> assignment gpq (one-time, may take several minutes)...")
        links = gpd.read_file(GDB, layer="FAF5_Links")
        assignment = convert_faf5_links(links, filter_centroids=True)
        assignment.to_parquet(links_path)
        print(f"Wrote {links_path} ({len(assignment)} links)")
    else:
        print(f"Reusing existing {links_path}")

    nbi_parq = OUT / "nbi_bridges_ntad.parquet"
    nti_parq = OUT / "nti_tunnels.parquet"
    bridge_idx = OUT / "faf5_bridge_index.parquet"
    tunnel_idx = OUT / "faf5_tunnel_index.parquet"

    run(
        [
            "scripts/load_ntad_bridge_gdb.py",
            "--input",
            str(NBI_GPKG),
            "--output",
            str(nbi_parq),
        ]
    )
    run(
        [
            "scripts/load_ntad_tunnel_gpkg.py",
            "--input",
            str(NTI_GPKG),
            "--output",
            str(nti_parq),
        ]
    )
    run(
        [
            "scripts/build_nbi_bridge_index.py",
            "--nbi",
            str(nbi_parq),
            "--road-links",
            str(links_path),
            "--output",
            str(bridge_idx),
            "--max-distance",
            "100",
        ]
    )
    run(
        [
            "scripts/build_nti_tunnel_index.py",
            "--nti",
            str(nti_parq),
            "--road-links",
            str(links_path),
            "--output",
            str(tunnel_idx),
            "--max-distance",
            "100",
        ]
    )
    run(
        [
            "scripts/patch_faf5_bridge_attributes.py",
            "--road-links",
            str(links_path),
            "--bridge-index",
            str(bridge_idx),
            "--output",
            str(OUT / "faf5_road_links_bridge_patched.gpq"),
        ]
    )
    run(
        [
            "scripts/patch_faf5_tunnel_attributes.py",
            "--road-links",
            str(OUT / "faf5_road_links_bridge_patched.gpq"),
            "--nti-index",
            str(tunnel_idx),
            "--on-conflict",
            "prefer_tunnel",
            "--conflict-out",
            str(OUT / "bridge_tunnel_conflicts.csv"),
            "--output",
            str(OUT / "faf5_road_links_bridge_tunnel_patched.gpq"),
        ]
    )
    run(
        [
            "scripts/summarize_network_structure_counts.py",
            "--faf-gdb",
            str(GDB),
            "--hpms-enriched",
            str(HPMS_CSV),
            "--nbi-gpkg",
            str(NBI_GPKG),
            "--nti-gpkg",
            str(NTI_GPKG),
            "--nbi-index",
            str(bridge_idx),
            "--nti-index",
            str(tunnel_idx),
            "--json-out",
            str(OUT / "structure_coverage_compare.json"),
        ]
    )
    print("\nDone. Artifacts under", OUT)
    print(json.dumps({"links": str(links_path), "bridge_index": str(bridge_idx), "tunnel_index": str(tunnel_idx)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
