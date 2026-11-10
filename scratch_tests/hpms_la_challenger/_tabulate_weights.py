import json
from pathlib import Path

rows = json.loads(
    Path("scratch_tests/hpms_la_challenger/artifacts/enclosing_connector_probe.json").read_text()
)["rows"]
print("endpoint,rank,faf_node,demand_share_pct,n_k4,unique_e_ids,n_dup_e_ids")
for r in rows:
    eids = [c["e_id"] for c in r["connectors_target_k4"]]
    uniq = len(set(eids))
    print(
        f"{r['endpoint']},{r['subarea_rank']},{r['faf5_node_id']},"
        f"{100 * r['weight']:.1f},{r['num_connectors_target_k4']},{uniq},{len(eids) - uniq}"
    )
print("--- HOME #4 ---")
h4 = next(r for r in rows if r["endpoint"] == "home" and r["subarea_rank"] == 4)
for c in h4["connectors_target_k4"]:
    print(c["e_id"], c.get("tier"), round(c["length_m"]), c["mid_lonlat"])
