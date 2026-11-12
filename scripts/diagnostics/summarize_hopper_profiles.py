"""Summarise per-stage profiles written by experiments/common/profile_stage.sh.

Usage: python summarize_hopper_profiles.py [profile_root]      (default ~/multimodal_hazard_project/profiles)
Flags stages that look wasteful: CPU efficiency under 0.30 on 4+ cores, or peak memory under 25% of the request.
"""
import sys
from pathlib import Path

import pandas as pd

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "multimodal_hazard_project" / "profiles"
rows = []
for d in sorted(p for p in root.glob("*_*") if p.is_dir()):
    f = d / "stages.tsv"
    if not f.exists():
        continue
    t = pd.read_csv(f, sep="\t")
    t.insert(0, "run", d.name)
    rows.append(t)
if not rows:
    sys.exit(f"no profiles under {root}")
df = pd.concat(rows, ignore_index=True)
df["wall_min"] = (pd.to_numeric(df["wall_s"], errors="coerce") / 60).round(1)
df["flag"] = ""
eff = pd.to_numeric(df["cpu_eff"], errors="coerce")
df.loc[(eff < 0.30) & (df["cpus"] >= 4), "flag"] += "LOW_CPU_EFFICIENCY "
df.loc[df["exit"] != 0, "flag"] += "NONZERO_EXIT "
print(df[["run", "label", "wall_min", "max_rss_gb", "cpus", "cpu_eff", "duckdb_tmp_gb", "exit", "flag"]].to_string(index=False))
