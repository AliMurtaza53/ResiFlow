"""Export combined event damaged-edge parquet from Script 2 road_links outputs.

Writes one parquet for Pass B Script 1 (NIRD_EVENT_DAMAGED_EDGES_PATH) with
event_id values like ``30_1`` matching Script 4 candidate lookup.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import geopandas as gpd
import pandas as pd

from resiflow.utils import get_results_variant, load_config


def damaged_mask(road_links: gpd.GeoDataFrame) -> pd.Series:
    if "damage_level_max" in road_links.columns:
        return road_links["damage_level_max"].astype(str).str.lower() != "no"
    if "flood_depth_max" in road_links.columns:
        return pd.to_numeric(road_links["flood_depth_max"], errors="coerce").fillna(0) > 0
    raise ValueError(
        "road_links has neither damage_level_max nor flood_depth_max columns"
    )


def export_event_damaged_edges(
    depth_key: int,
    event_keys: list[int],
    output_path: Path,
    results_variant: str | None = None,
) -> pd.DataFrame:
    base_path = Path(load_config()["paths"]["soge_clusters"])
    variant = results_variant or get_results_variant()
    links_dir = (
        base_path.parent
        / "results"
        / "disruption_analysis"
        / variant
        / str(depth_key)
        / "links"
    )
    if not links_dir.exists():
        raise FileNotFoundError(f"Script 2 links directory not found: {links_dir}")

    frames: list[pd.DataFrame] = []
    for event_key in event_keys:
        road_links_path = links_dir / f"road_links_{event_key}.gpq"
        if not road_links_path.exists():
            raise FileNotFoundError(
                f"Missing Script 2 output for event {event_key}: {road_links_path}"
            )
        road_links = gpd.read_parquet(road_links_path)
        road_links["e_id"] = road_links["e_id"].astype(str)
        mask = damaged_mask(road_links)
        damaged = road_links.loc[mask, ["e_id"]].copy()
        if damaged.empty:
            logging.warning(
                "No damaged edges for depth_key=%s event_key=%s in %s",
                depth_key,
                event_key,
                road_links_path,
            )
        damaged["depth_key"] = depth_key
        damaged["flood_key"] = event_key
        damaged["event_id"] = f"{depth_key}_{event_key}"
        if "damage_level_max" in road_links.columns:
            damaged["damage_level"] = (
                road_links.loc[mask, "damage_level_max"].astype(str).values
            )
        elif "road_label" in road_links.columns:
            damaged["road_label"] = road_links.loc[mask, "road_label"].astype(str).values
        frames.append(damaged)
        logging.info(
            "Event %s_%s: %s damaged edges from %s",
            depth_key,
            event_key,
            len(damaged),
            road_links_path,
        )

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=["event_id", "e_id"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(output_path, index=False)
    logging.info(
        "Wrote %s damaged-edge rows across %s events to %s",
        len(combined),
        len(event_keys),
        output_path,
    )
    return combined


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--depth-key", type=int, default=30)
    parser.add_argument(
        "--event-keys",
        type=int,
        nargs="+",
        default=[1, 2, 3],
        help="Flood event keys (1=base, 2=low, 3=high)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output parquet path (default: tables/event_damaged_edges_depth{depth}_toy.pq)",
    )
    parser.add_argument("--results-variant", type=str, default=None)
    args = parser.parse_args()

    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(message)s",
        level=logging.INFO,
    )

    base_path = Path(load_config()["paths"]["soge_clusters"])
    output = args.output or (
        base_path / "tables" / f"event_damaged_edges_depth{args.depth_key}_toy.pq"
    )
    export_event_damaged_edges(
        depth_key=args.depth_key,
        event_keys=args.event_keys,
        output_path=output,
        results_variant=args.results_variant,
    )


if __name__ == "__main__":
    main()
