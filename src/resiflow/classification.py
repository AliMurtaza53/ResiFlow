"""Road classification helpers (delegates to :mod:`resiflow.networks`)."""

from __future__ import annotations

import pandas as pd

from resiflow.networks.base import FAF_ROAD_CLASSES, MAJOR_ROAD_CLASSES
from resiflow.networks.normalize import is_major_road, normalize_network_links

__all__ = [
    "FAF_ROAD_CLASSES",
    "MAJOR_ROAD_CLASSES",
    "apply_combined_label",
    "is_major_road",
    "normalize_network_links",
]


def apply_combined_label(road_links: pd.DataFrame) -> pd.DataFrame:
    """Normalize links and write legacy combined_label for downstream compatibility."""
    return normalize_network_links(road_links)
