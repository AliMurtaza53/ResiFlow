"""Load unified numeric parameters, with per-run override + scale support.

Replacement for the existing ``src/resiflow/parameters.py`` on
``feature/sensitivity-analysis``. Fully backward compatible:

* Same public API: ``load_unified_parameters``, ``get_parameter``,
  ``clear_cache`` — all existing call sites keep working unchanged.
* Same existence-gated fallback: no ``unified_parameters.json`` deployed
  means every ``get_parameter`` returns the caller-supplied default.

"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

try:  # normal path inside the full environment
    from resiflow.networks.profiles import resolve_params_root
except Exception:  # pragma: no cover - light envs without geopandas
    _REPO_PARAMETERS = Path(__file__).resolve().parents[2] / "parameters"

    def resolve_params_root(params_root: Path | str | None = None) -> Path:
        if params_root is not None:
            return Path(params_root)
        env_path = os.environ.get("RESIFLOW_PARAMETERS_ROOT") or os.environ.get(
            "NIRD_PARAMETERS_ROOT"
        )
        return Path(env_path) if env_path else _REPO_PARAMETERS


_FILENAME = "unified_parameters.json"
_OVERRIDES_ENV = "RESIFLOW_PARAM_OVERRIDES"
_SCALES_KEY = "_scales"
_cache: dict[str, dict[str, Any]] = {}


def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``patch`` into a copy of ``base`` (patch wins)."""
    out = copy.deepcopy(base)
    for key, value in patch.items():
        if key == _SCALES_KEY:
            continue  # applied separately, after the merge
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _scale_leaf(node: Any, factor: float) -> Any:
    """Multiply a numeric leaf, or every numeric leaf of a (nested) dict."""
    if isinstance(node, bool):  # bool is int; never scale flags
        return node
    if isinstance(node, (int, float)):
        return node * factor
    if isinstance(node, dict):
        return {k: _scale_leaf(v, factor) for k, v in node.items()}
    return node


def _apply_scales(data: dict[str, Any], scales: dict[str, float]) -> dict[str, Any]:
    out = copy.deepcopy(data)
    for dotted, factor in scales.items():
        parts = dotted.split(".")
        node = out
        for part in parts[:-1]:
            if not isinstance(node, dict) or part not in node:
                node = None
                break
            node = node[part]
        if node is None or not isinstance(node, dict) or parts[-1] not in node:
            raise KeyError(
                f"_scales path {dotted!r} not found in unified parameters; "
                "scales can only multiply values that exist after the merge."
            )
        node[parts[-1]] = _scale_leaf(node[parts[-1]], float(factor))
    return out


def active_overrides_path() -> Path | None:
    """Path of the overrides file currently in force, if any."""
    raw = os.environ.get(_OVERRIDES_ENV, "").strip()
    return Path(raw) if raw else None


def load_unified_parameters(params_root: Path | str | None = None) -> dict[str, Any]:
    """Load unified_parameters.json (+ env-selected overrides), or {} if absent."""
    root = resolve_params_root(params_root)
    ov_path = active_overrides_path()
    cache_key = f"{root}|{ov_path}"
    if cache_key in _cache:
        return _cache[cache_key]

    data: dict[str, Any] = {}
    path = Path(root) / _FILENAME
    if path.exists():
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)

    if ov_path is not None:
        if not ov_path.exists():
            raise FileNotFoundError(
                f"{_OVERRIDES_ENV} points to a missing file: {ov_path}"
            )
        with open(ov_path, encoding="utf-8") as fh:
            patch = json.load(fh)
        data = _deep_merge(data, patch)
        scales = patch.get(_SCALES_KEY, {})
        if scales:
            data = _apply_scales(data, scales)

    _cache[cache_key] = data
    return data


def get_parameter(
    section: str,
    key: str,
    default: Any,
    *,
    params_root: Path | str | None = None,
) -> Any:
    """Return an overridden parameter, or ``default`` if unavailable."""
    data = load_unified_parameters(params_root)
    return data.get(section, {}).get(key, default)


def clear_cache() -> None:
    """Reset the loader cache (test isolation helper)."""
    _cache.clear()
