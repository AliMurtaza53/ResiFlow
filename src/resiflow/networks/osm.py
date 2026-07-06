"""OSM network adapter helpers."""

from __future__ import annotations


def normalize_highway_tag(raw: str | None) -> str:
    """Normalize an OSM ``highway`` tag to a network_class string."""
    if raw is None:
        return "unclassified"
    text = str(raw).strip().lower()
    if not text or text in {"nan", "none", "null"}:
        return "unclassified"
    return text
