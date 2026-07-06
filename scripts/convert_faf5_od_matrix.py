#!/usr/bin/env python3
"""CLI: convert FAF5 regional OD CSV to assignment OD matrix parquet."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
for path in (REPO_ROOT, SRC_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from resiflow.preprocess.faf5_od_matrix import main

if __name__ == "__main__":
    raise SystemExit(main())
