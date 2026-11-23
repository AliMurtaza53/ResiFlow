"""Row-level look at the highest-damage links of an event (read-only)."""
import sys, glob, pandas as pd
R = "/scratch/akothaw/multimodal_hazard_data/results/damage_analysis"
pre, ev, n = sys.argv[1], sys.argv[2], int(sys.argv[3])
f = glob.glob(f"{R}/{pre}{ev}/{ev}/*with_damage_values.csv")[0]
d = pd.read_csv(f, low_memory=False)
print("columns:", list(d.columns))
top = d.groupby("e_id").direct_damage_mean_musd.sum().sort_values(ascending=False).head(n).index
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 40)
for e in top:
    x = d[d.e_id == e]
    print(f"\n--- e_id {e}: rows={len(x)} sum={x.direct_damage_mean_musd.sum():,.1f} M USD  per-row mean={x.direct_damage_mean_musd.mean():.2f} max={x.direct_damage_mean_musd.max():.2f}")
    print(x[["length","road_label","road_classification","STATE","structure_length_m","bridge_fraction","main_unit_spans","lanes","averageWidth"]].iloc[0].to_dict())
    cc = [c for c in d.columns if "unit_cost" in c or "damage_level" in c or c in ("landslide_mm","pga_max_g","pga","psa1p0")]
    print(x[cc].describe().loc[["min","mean","max"]].round(3).to_string())
