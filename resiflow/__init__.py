"""Compatibility shim: import resiflow from repo root."""
from pkgutil import extend_path
from pathlib import Path

__path__ = extend_path(__path__, __name__)  # type: ignore[name-defined]
src_pkg = Path(__file__).resolve().parent.parent / "src" / "resiflow"
if src_pkg.exists():
    __path__.append(str(src_pkg))
