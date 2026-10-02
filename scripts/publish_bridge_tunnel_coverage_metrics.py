#!/usr/bin/env python3
"""Publish bridge/tunnel coverage metrics for an enriched FAF links GeoParquet.

Reports locational flag rates vs inventory structure/tunnel lengths (fractions).
Excludes are already applied by apply_bridge_index / apply_tunnel_index
(null/non-positive inventory length or deck → not flagged).

Usage::

    python scripts/publish_bridge_tunnel_coverage_metrics.py \\
        --road-links /path/to/faf5_road_links_bridge_tunnel_patched.gpq \\
        --output /path/to/bridge_tunnel_coverage_metrics.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import geopandas as gpd
import pandas as pd


def _frac_stats(series: pd.Series) -> dict:
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty:
        return {"n": 0}
    q = s.quantile([0.1, 0.25, 0.5, 0.75, 0.9, 0.95])
    return {
        "n": int(len(s)),
        "mean": float(s.mean()),
        "p10": float(q.loc[0.1]),
        "p25": float(q.loc[0.25]),
        "p50": float(q.loc[0.5]),
        "p75": float(q.loc[0.75]),
        "p90": float(q.loc[0.9]),
        "p95": float(q.loc[0.95]),
        "share_lt_0p05": float((s < 0.05).mean()),
        "share_lt_0p10": float((s < 0.10).mean()),
        "share_lt_0p25": float((s < 0.25).mean()),
        "share_lt_0p50": float((s < 0.50).mean()),
        "share_ge_0p50": float((s >= 0.50).mean()),
    }


def metrics(links: gpd.GeoDataFrame) -> dict:
    n = len(links)
    length = pd.to_numeric(links["length"], errors="coerce")
    total_km = float(length.sum() / 1000.0)

    label = links["road_label"].astype(str).str.lower() if "road_label" in links.columns else None
    if label is None:
        raise KeyError("road_links missing required column 'road_label'")

    is_b = label.eq("bridge")
    is_t = label.eq("tunnel")
    nb, nt = int(is_b.sum()), int(is_t.sum())

    out = {
        "note": (
            "road_bridge / road_tunnel / road_label are locational FAF associations "
            "(nearest NBI/NTI within tolerance), not true facility span. Use "
            "structure_length_m / tunnel_length_m and bridge_fraction / tunnel_fraction "
            "for asset geometry. Matches with null or non-positive inventory length "
            "or deck width are excluded at apply_*_index."
        ),
        "n_links": n,
        "total_length_km": total_km,
        "bridge": {
            "n_links": nb,
            "share_of_links": nb / n if n else 0.0,
            "faf_length_km": float(length[is_b].sum() / 1000.0),
            "share_of_faf_length": float(length[is_b].sum() / length.sum()) if length.sum() else 0.0,
            "inventory_structure_length_km": float(
                pd.to_numeric(links.loc[is_b, "structure_length_m"], errors="coerce").sum() / 1000.0
            )
            if "structure_length_m" in links.columns
            else None,
            "inventory_over_faf_length_ratio": None,
            "bridge_fraction": _frac_stats(links.loc[is_b, "bridge_fraction"])
            if "bridge_fraction" in links.columns
            else None,
            "deck_width_m_positive": int(
                (pd.to_numeric(links.loc[is_b, "averageWidth"], errors="coerce") > 0).sum()
            )
            if "averageWidth" in links.columns
            else None,
        },
        "tunnel": {
            "n_links": nt,
            "share_of_links": nt / n if n else 0.0,
            "faf_length_km": float(length[is_t].sum() / 1000.0),
            "share_of_faf_length": float(length[is_t].sum() / length.sum()) if length.sum() else 0.0,
            "inventory_tunnel_length_km": float(
                pd.to_numeric(links.loc[is_t, "tunnel_length_m"], errors="coerce").sum() / 1000.0
            )
            if "tunnel_length_m" in links.columns
            else None,
            "tunnel_fraction": _frac_stats(links.loc[is_t, "tunnel_fraction"])
            if "tunnel_fraction" in links.columns
            else None,
        },
    }
    b_inv = out["bridge"]["inventory_structure_length_km"]
    b_faf = out["bridge"]["faf_length_km"]
    if b_inv is not None and b_faf and b_faf > 0:
        out["bridge"]["inventory_over_faf_length_ratio"] = b_inv / b_faf
        out["bridge"]["faf_over_inventory_overstatement"] = b_faf / b_inv if b_inv else None
    return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--road-links", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if not args.road_links.exists():
        raise FileNotFoundError(args.road_links)
    m = metrics(gpd.read_parquet(args.road_links))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(m, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(m, indent=2))
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
