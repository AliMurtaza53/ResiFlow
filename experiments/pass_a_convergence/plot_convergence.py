#!/usr/bin/env python3
"""Plot remain_fraction vs iteration from parsed Pass A logs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt

from parse_assignment_log import parse_log, read_log


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("parsed_json", type=Path, nargs="+", help="Parsed JSON from parse_assignment_log.py")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    fig, ax = plt.subplots(figsize=(8, 4))
    for path in args.parsed_json:
        data = json.loads(path.read_text(encoding="utf-8"))
        iters = data.get("iterations") or []
        if not iters:
            continue
        xs = [row["iteration"] for row in iters]
        ys = [row.get("remain_fraction", 0) for row in iters]
        ax.plot(xs, ys, marker=".", label=path.stem)

    ax.set_xlabel("Iteration")
    ax.set_ylabel("Remain fraction (total_remain / initial_supply)")
    ax.set_yscale("log")
    ax.grid(True, alpha=0.3)
    ax.legend()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(args.out, dpi=120)
    print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
