"""ResiFlow configuration helpers with RESIFLOW_* / NIRD_* env aliases."""

from __future__ import annotations

import os


def get_env(
    resiflow_key: str,
    nird_key: str | None = None,
    default: str | None = None,
) -> str | None:
    """Read an environment variable, preferring RESIFLOW_* over NIRD_*."""
    value = os.environ.get(resiflow_key)
    if value is not None and value != "":
        return value
    if nird_key is not None:
        legacy = os.environ.get(nird_key)
        if legacy is not None and legacy != "":
            return legacy
    return default


def config_path() -> str | None:
    """Resolved config.json path from environment."""
    return get_env("RESIFLOW_CONFIG_PATH", "NIRD_CONFIG_PATH")


def max_flow_iterations(default: int = 0) -> int:
    """Cap iterative assignment passes (0 = run to convergence)."""
    raw = get_env("RESIFLOW_MAX_FLOW_ITERATIONS", "NIRD_MAX_FLOW_ITERATIONS")
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def results_variant(default: str = "revision") -> str:
    """Active results subdirectory name for experiment runs."""
    variant = get_env("RESIFLOW_RESULTS_VARIANT", "NIRD_RESULTS_VARIANT", default) or default
    return variant.strip() or default


def results_root() -> str | None:
    """Optional explicit results root override."""
    return get_env("RESIFLOW_RESULTS_ROOT", "NIRD_RESULTS_ROOT")
