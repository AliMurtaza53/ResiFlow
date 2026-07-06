"""Resolve local FAF5 input directories (regional OD, county factors, processed OD)."""

from __future__ import annotations

import os
from pathlib import Path


def resolve_faf5_data_root(base_path: Path | None = None, repo_root: Path | None = None) -> Path | None:
    """Return the local FAF5 data root when it exists on disk."""
    candidates: list[Path] = []
    env_root = os.getenv("NIRD_FAF5_DATA_ROOT")
    if env_root:
        candidates.append(Path(env_root))
    if base_path is not None:
        candidates.append(base_path.parent / "faf5_data")
        candidates.append(base_path / "faf5_data")
    if repo_root is not None:
        candidates.append(repo_root / "data" / "faf5_data")
    # Hardcoded fallbacks last so local sibling paths win in tests and multi-root setups.
    candidates.extend(
        [
            Path.home() / "Desktop" / "data" / "faf5_data",
            Path(r"C:\Users\akothaw\Desktop\data\faf5_data"),
        ]
    )
    seen: set[str] = set()
    for path in candidates:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        if path.is_dir():
            return path
    return None


def regional_od_candidates(faf5_root: Path) -> list[Path]:
    paths = [
        faf5_root / "regional_od_data" / "FAF5.7.1_2018-2024.csv",
        faf5_root / "regional_od_data" / "FAF5.7.1_2018-2024.parquet",
        faf5_root / "FAF5.7.1" / "FAF5.7.1.csv",
        faf5_root / "FAF5.7.1" / "FAF5.7.1.parquet",
    ]
    for folder in ("regional_od_data", "FAF5.7.1"):
        data_dir = faf5_root / folder
        if data_dir.is_dir():
            paths.extend(sorted(data_dir.glob("FAF5*.csv")))
            paths.extend(sorted(data_dir.glob("*.csv")))
            paths.extend(sorted(data_dir.glob("*.parquet")))
    return paths


def resolve_regional_od_path(faf5_root: Path) -> Path | None:
    env_path = os.getenv("NIRD_FAF_REGIONAL_OD_PATH")
    if env_path:
        path = Path(env_path)
        if path.exists():
            return path
    for path in regional_od_candidates(faf5_root):
        if path.exists():
            return path
    return None


def truck_factor_paths(faf5_root: Path) -> tuple[Path, Path]:
    return (
        faf5_root / "county_disaggregation_factors" / "truck_origin_factors.csv",
        faf5_root / "county_disaggregation_factors" / "truck_destination_factors.csv",
    )


def detailed_county_od_candidates(faf5_root: Path | None, base_path: Path | None = None) -> list[Path]:
    paths: list[Path] = []
    if base_path is not None:
        paths.extend(
            [
                base_path / "census_datasets" / "faf5_county_od.pq",
                base_path / "census_datasets" / "faf5_county_truck_od.pq",
                base_path / "processed" / "faf5_bts_conus_county_od.pq",
            ]
        )
    if faf5_root is None:
        return paths
    processed = faf5_root / "processed"
    if processed.is_dir():
        paths.extend(sorted(processed.glob("faf5_county_truck_od_*by_sctg*.parquet")))
        paths.extend(sorted(processed.glob("faf5_county_truck_od_*by_sctg*.pq")))
        paths.extend(sorted(processed.glob("faf5_county_truck_od_*detail*.parquet")))
        paths.extend(sorted(processed.glob("faf5_county_truck_od_*detail*.pq")))
        paths.extend(sorted(processed.glob("faf5_county_truck_od_*.parquet")))
        paths.extend(sorted(processed.glob("faf5_county_truck_od_*.pq")))
        paths.extend(sorted(processed.glob("faf5_county_od*.parquet")))
        paths.extend(sorted(processed.glob("faf5_county_od*.pq")))
    return paths


def resolve_detailed_county_od_path(
    faf5_root: Path | None,
    base_path: Path | None = None,
    *,
    explicit: str | None = None,
) -> Path | None:
    if explicit:
        path = Path(explicit)
        return path if path.exists() else None
    env_path = os.getenv("NIRD_FAF5_COUNTY_OD_PATH")
    if env_path:
        path = Path(env_path)
        if path.exists():
            return path
    for path in detailed_county_od_candidates(faf5_root, base_path):
        if not path.exists():
            continue
        if "total" in path.stem.lower():
            continue
        return path
    for path in detailed_county_od_candidates(faf5_root, base_path):
        if path.exists():
            return path
    return None
