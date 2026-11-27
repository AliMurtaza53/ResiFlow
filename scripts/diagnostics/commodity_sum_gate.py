"""Gate for the commodity split: the five per-commodity ODs must sum to the frozen freight OD.

Reads <w2>/<sctgG5>/conus/harvey15_gateway_od.pq for the five groups, compares the pair-wise sum with the frozen
freight_od_T29_gateway_conus.pq, and writes <w2>/commodity_od.pq (origin_node, destination_node, sctgG5, Car21) and
<w2>/commodity_gate.json. Exits non-zero if the total or any pair differs by more than the tolerance.
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

GROUPS = ["sctg0109", "sctg1014", "sctg1519", "sctg2033", "sctg3499"]
KEYS = ["origin_node", "destination_node"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--w2", type=Path, required=True)
    ap.add_argument("--frozen", type=Path, required=True)
    ap.add_argument("--rtol", type=float, default=1e-6, help="per-pair relative tolerance on pairs above 1e-6 trips/day")
    a = ap.parse_args()
    parts = []
    for k in GROUPS:
        d = pd.read_parquet(a.w2 / k / "conus" / "harvey15_gateway_od.pq").astype({c: "int64" for c in KEYS})
        parts.append(d.assign(sctgG5=k))
    com = pd.concat(parts, ignore_index=True)
    total = com.groupby(KEYS, as_index=False).Car21.sum()
    frozen = pd.read_parquet(a.frozen).astype({c: "int64" for c in KEYS})
    m = frozen.merge(total, on=KEYS, how="outer", suffixes=("_frozen", "_sum"), indicator=True)
    both = m[m._merge == "both"]
    diff = (both.Car21_frozen - both.Car21_sum).abs()
    big = both.Car21_frozen > 1e-6
    rel = (diff[big] / both.Car21_frozen[big]).max()
    rep = {
        "frozen_rows": int(len(frozen)), "sum_rows": int(len(total)),
        "frozen_only_rows": int((m._merge == "left_only").sum()), "sum_only_rows": int((m._merge == "right_only").sum()),
        "frozen_only_flow": float(m.loc[m._merge == "left_only", "Car21_frozen"].sum()),
        "sum_only_flow": float(m.loc[m._merge == "right_only", "Car21_sum"].sum()),
        "frozen_total": float(frozen.Car21.sum()), "sum_total": float(com.Car21.sum()),
        "total_rel_diff": float(com.Car21.sum() / frozen.Car21.sum() - 1),
        "max_abs_pair_diff": float(diff.max()), "max_rel_pair_diff_above_1e-6": float(rel),
        "by_group_total": com.groupby("sctgG5").Car21.sum().to_dict(),
        "by_group_rows": com.groupby("sctgG5").size().to_dict(),
    }
    ok = abs(rep["total_rel_diff"]) < 1e-9 and rel < a.rtol and rep["frozen_only_flow"] < 1e-3 and rep["sum_only_flow"] < 1e-3
    rep["passed"] = bool(ok)
    com[com.Car21 > 0].to_parquet(a.w2 / "commodity_od.pq", index=False)
    (a.w2 / "commodity_gate.json").write_text(json.dumps(rep, indent=2))
    print(json.dumps(rep, indent=2))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
