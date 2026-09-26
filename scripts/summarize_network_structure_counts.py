#!/usr/bin/env python3
"""Sanity-count tolls / bridges / tunnels across FAF5, HPMS LRS, NTAD NBI/NTI.

Read-only. Does not overwrite production network artifacts.

Usage::

    python scripts/summarize_network_structure_counts.py \\
      --faf-gdb path/to/FAF5Network.gdb \\
      --hpms-enriched path/to/faf_hpms_lrs_enriched.csv \\
      [--nbi-gpkg path/to/NTAD_National_Bridge_Inventory.gpkg] \\
      [--nti-gpkg path/to/NTAD_National_Tunnel_Inventory.gpkg] \\
      [--nbi-index path/to/faf5_bridge_index.parquet] \\
      [--nti-index path/to/faf5_tunnel_index.parquet] \\
      [--json-out path/to/structure_coverage_compare.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd


def _count_faf_tolls(gdb: Path) -> dict:
    import pyogrio

    df = pyogrio.read_dataframe(
        gdb,
        layer="FAF5_Links",
        columns=["ID", "LENGTH", "Toll_Type", "TRUCKTOLL", "Toll_Link"],
        read_geometry=False,
    )
    truck = pd.to_numeric(df["TRUCKTOLL"], errors="coerce")
    toll_type = pd.to_numeric(df["Toll_Type"], errors="coerce")
    return {
        "faf_links_total": int(len(df)),
        "trucktoll_gt0_links": int((truck > 0).sum()),
        "trucktoll_sum": float(truck.fillna(0).sum()),
        "toll_type_nonnull_links": int(toll_type.notna().sum()),
        "toll_type_value_counts": {
            str(k): int(v) for k, v in toll_type.value_counts(dropna=False).items()
        },
        "toll_link_eq1_links": int(
            (pd.to_numeric(df.get("Toll_Link"), errors="coerce") == 1).sum()
        )
        if "Toll_Link" in df.columns
        else None,
    }


def _count_hpms_keyed(csv_path: Path) -> dict:
    df = pd.read_csv(csv_path)
    struct = pd.to_numeric(df.get("hpms_STRUCTURE_TYPE"), errors="coerce")
    tol = pd.to_numeric(df.get("hpms_TOL_CHARGED"), errors="coerce")
    has_overlap = pd.to_numeric(df.get("has_overlap"), errors="coerce").fillna(0).astype(int)
    tunnel_ids = set(df.loc[struct == 2, "ID"].astype(str))
    bridge_ids = set(df.loc[struct == 1, "ID"].astype(str))
    return {
        "keyed_links": int(len(df)),
        "overlap_links": int((has_overlap == 1).sum()),
        "structure_bridge_1": int((struct == 1).sum()),
        "structure_tunnel_2": int((struct == 2).sum()),
        "structure_causeway_3": int((struct == 3).sum()),
        "structure_null": int(struct.isna().sum()),
        "tol_charged_nonnull": int(tol.notna().sum()),
        "tol_charged_1_or_2": int(tol.isin([1, 2]).sum()),
        "tol_charged_value_counts": {
            str(k): int(v) for k, v in tol.value_counts(dropna=False).items()
        },
        "_tunnel_e_ids": tunnel_ids,
        "_bridge_e_ids": bridge_ids,
        "note": (
            "HPMS STRUCTURE_TYPE / TOL_* only meaningful on LRS-keyed FAF links "
            "(~20% of links). Primary bridge/tunnel sources are NTAD NBI/NTI."
        ),
    }


def _count_index(index_path: Path, flag_col: str, label: str) -> dict:
    df = pd.read_parquet(index_path)
    if "e_id" not in df.columns:
        raise KeyError(f"{label} index {index_path} missing required column 'e_id'")
    e_ids = set(df["e_id"].astype(str))
    out = {
        "index_path": str(index_path),
        f"unique_e_id_flagged_{label}": len(e_ids),
        "index_rows": int(len(df)),
        "_e_ids": e_ids,
    }
    if flag_col in df.columns:
        out[f"{flag_col}_yes"] = int((df[flag_col].astype(str).str.lower() == "yes").sum())
    return out


def _count_nbi_gpkg(path: Path) -> dict:
    import pyogrio

    df = pyogrio.read_dataframe(
        path,
        layer="National_Bridge_Inventory",
        columns=["STATE_CODE_001", "SERVICE_ON_042A", "LATDD", "LONGDD"],
        read_geometry=False,
    )
    lat = pd.to_numeric(df["LATDD"], errors="coerce")
    lon = pd.to_numeric(df["LONGDD"], errors="coerce")
    service = pd.to_numeric(df["SERVICE_ON_042A"], errors="coerce")
    return {
        "path": str(path),
        "inventory_rows": int(len(df)),
        "coords_nonzero": int(((lat != 0) & (lon != 0) & lat.notna() & lon.notna()).sum()),
        "service_on_highway_1": int((service == 1).sum()),
    }


def _count_nti_gpkg(path: Path) -> dict:
    import pyogrio

    df = pyogrio.read_dataframe(
        path,
        layer="National_Tunnel_Inventory",
        columns=[
            "tunnel_number_i1",
            "portal_latitude_i13",
            "portal_longitude_i14",
            "service_in_tunnel_a8",
            "nhs_designation_c5",
        ],
        read_geometry=False,
    )
    lat = pd.to_numeric(df["portal_latitude_i13"], errors="coerce")
    lon = pd.to_numeric(df["portal_longitude_i14"], errors="coerce")
    service = pd.to_numeric(df["service_in_tunnel_a8"], errors="coerce")
    return {
        "path": str(path),
        "inventory_rows": int(len(df)),
        "portal_coords_valid": int(
            ((lat != 0) & (lon != 0) & lat.notna() & lon.notna()).sum()
        ),
        "service_in_tunnel_value_counts": {
            str(k): int(v) for k, v in service.value_counts(dropna=False).items()
        },
        "nhs_yes": int((pd.to_numeric(df["nhs_designation_c5"], errors="coerce") == 1).sum()),
    }


def _cross(hpms: dict, bridge_idx: dict | None, tunnel_idx: dict | None) -> dict:
    hpms_t = hpms.pop("_tunnel_e_ids", set())
    hpms_b = hpms.pop("_bridge_e_ids", set())
    nbi_e = (bridge_idx or {}).pop("_e_ids", set()) if bridge_idx else set()
    nti_e = (tunnel_idx or {}).pop("_e_ids", set()) if tunnel_idx else set()

    out: dict = {
        "hpms_tunnel_links": len(hpms_t),
        "hpms_bridge_links": len(hpms_b),
    }
    if nti_e:
        out["nti_matched_faf_links"] = len(nti_e)
        out["hpms_tunnel_also_nti"] = len(hpms_t & nti_e)
        out["hpms_tunnel_not_in_nti"] = len(hpms_t - nti_e)
        out["nti_outside_hpms_keyed_tunnel"] = len(nti_e - hpms_t)
        out["coverage_gain_note"] = (
            "nti_outside_hpms_keyed_tunnel = FAF links NTI flags that HPMS LRS "
            "STRUCTURE_TYPE=2 did not (includes unkeyed FAF + keyed misses)."
        )
    if nbi_e:
        out["nbi_matched_faf_links"] = len(nbi_e)
        out["hpms_bridge_also_nbi"] = len(hpms_b & nbi_e)
        out["hpms_bridge_not_in_nbi"] = len(hpms_b - nbi_e)
        out["nbi_outside_hpms_keyed_bridge"] = len(nbi_e - hpms_b)
    if nbi_e and nti_e:
        both = nbi_e & nti_e
        out["bridge_and_tunnel_conflict_e_ids"] = len(both)
        out["bridge_and_tunnel_conflict_sample"] = sorted(both)[:20]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--faf-gdb", type=Path, required=True)
    ap.add_argument("--hpms-enriched", type=Path, required=True)
    ap.add_argument("--nbi-gpkg", type=Path, default=None)
    ap.add_argument("--nti-gpkg", type=Path, default=None)
    ap.add_argument("--nbi-index", type=Path, default=None)
    ap.add_argument("--nti-index", type=Path, default=None)
    ap.add_argument("--json-out", type=Path, default=None)
    args = ap.parse_args()

    for label, path in (
        ("--faf-gdb", args.faf_gdb),
        ("--hpms-enriched", args.hpms_enriched),
    ):
        if not path.exists():
            raise FileNotFoundError(f"{label} not found: {path}")

    hpms = _count_hpms_keyed(args.hpms_enriched)
    bridge_idx = None
    tunnel_idx = None
    if args.nbi_index is not None:
        if not args.nbi_index.exists():
            raise FileNotFoundError(f"--nbi-index not found: {args.nbi_index}")
        bridge_idx = _count_index(args.nbi_index, "road_bridge", "bridge")
    if args.nti_index is not None:
        if not args.nti_index.exists():
            raise FileNotFoundError(f"--nti-index not found: {args.nti_index}")
        tunnel_idx = _count_index(args.nti_index, "road_tunnel", "tunnel")

    report = {
        "faf5_full_network": _count_faf_tolls(args.faf_gdb),
        "hpms_lrs_keyed_subset": {k: v for k, v in hpms.items() if not k.startswith("_")},
        "ntad_nbi_inventory": None,
        "ntad_nti_inventory": None,
        "nbi_bridge_index": (
            {k: v for k, v in bridge_idx.items() if not k.startswith("_")}
            if bridge_idx
            else {"status": "not_provided"}
        ),
        "nti_tunnel_index": (
            {k: v for k, v in tunnel_idx.items() if not k.startswith("_")}
            if tunnel_idx
            else {"status": "not_provided"}
        ),
        "cross_checks": None,
    }
    if args.nbi_gpkg is not None:
        if not args.nbi_gpkg.exists():
            raise FileNotFoundError(f"--nbi-gpkg not found: {args.nbi_gpkg}")
        report["ntad_nbi_inventory"] = _count_nbi_gpkg(args.nbi_gpkg)
    if args.nti_gpkg is not None:
        if not args.nti_gpkg.exists():
            raise FileNotFoundError(f"--nti-gpkg not found: {args.nti_gpkg}")
        report["ntad_nti_inventory"] = _count_nti_gpkg(args.nti_gpkg)

    report["cross_checks"] = _cross(hpms, bridge_idx, tunnel_idx)

    text = json.dumps(report, indent=2)
    print(text)
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text + "\n", encoding="utf-8")
        print(f"Wrote {args.json_out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
