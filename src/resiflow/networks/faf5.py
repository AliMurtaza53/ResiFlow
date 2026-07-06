"""FAF5 network adapter helpers."""

from __future__ import annotations


def normalize_network_class(raw: str | None) -> str:
    """Normalize a FAF coarse road_classification value."""
    if raw is None:
        return "unclassified"
    text = str(raw).strip().lower()
    if not text or text in {"nan", "none", "null"}:
        return "unclassified"
    return text
