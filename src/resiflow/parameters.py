"""Load the unified numeric-parameter overrides file, with graceful fallback.

Mirrors the existence-gated pattern used by
``resiflow.networks.profiles.load_assignment_profiles``: if
``unified_parameters.json`` is present under the resolved parameters root, its
values override the hardcoded defaults baked into call sites throughout the
codebase. If absent (e.g. not yet deployed to a production data root),
``get_parameter`` transparently falls back to the caller-supplied default,
which is always the historical hardcoded literal — so nothing breaks when
this file isn't deployed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from resiflow.networks.profiles import resolve_params_root

_FILENAME = "unified_parameters.json"
_cache: dict[str, dict[str, Any]] = {}


def load_unified_parameters(params_root: Path | str | None = None) -> dict[str, Any]:
    """Load unified_parameters.json from the resolved params root, or {} if absent."""
    root = resolve_params_root(params_root)
    cache_key = str(root)
    if cache_key in _cache:
        return _cache[cache_key]
    path = Path(root) / _FILENAME
    data: dict[str, Any] = {}
    if path.exists():
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    _cache[cache_key] = data
    return data


def get_parameter(
    section: str,
    key: str,
    default: Any,
    *,
    params_root: Path | str | None = None,
) -> Any:
    """Return an overridden scalar parameter, or ``default`` if unavailable."""
    data = load_unified_parameters(params_root)
    return data.get(section, {}).get(key, default)


def clear_cache() -> None:
    """Reset the loader cache (test isolation helper)."""
    _cache.clear()
