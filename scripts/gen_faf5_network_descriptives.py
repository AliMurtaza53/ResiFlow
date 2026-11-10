"""Generate FAF5 network attribute + categorical descriptives.

Sources:
  - Raw GDB: FAF5_Links
  - Model parquet: soge_clusters/.../faf5_road_links.gpq (post-convert / patched)

Writes:
  parameters/tables/FAF5_network_attribute_descriptive_stats.csv
  parameters/tables/FAF5_network_categorical_value_stats.csv
"""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
from pyogrio.raw import read

GDB = Path(r"C:\Users\akothaw\Desktop\data\faf5_data\network_data\FAF5Network.gdb")
GPQ = Path(r"C:\Users\akothaw\Desktop\data\soge_clusters\networks\faf5\faf5_road_links.gpq")
OUT_ATTR = Path("parameters/tables/FAF5_network_attribute_descriptive_stats.csv")
OUT_CAT = Path("parameters/tables/FAF5_network_categorical_value_stats.csv")

MODEL_USE_GDB = {
    "ID": "Mapped to e_id (link ID)",
    "LENGTH": "Mapped to length (miles * 1609.34 -> meters); else geometry.length",
    "DIR": "Not mapped into assignment links",
    "Class": "Mapped via CLASS_MAPPING -> road_classification",
    "Class_Description": "Preferred source for road_classification_detail (if present)",
    "Urban_Code": "urban = 1 if Urban_Code != 99999 else 0",
    "AB_Lanes": "lanes = max(AB_Lanes, BA_Lanes); fillna default 2",
    "BA_Lanes": "lanes = max(AB_Lanes, BA_Lanes); fillna default 2",
    "Toll_Type": "PRESENT but average_toll_cost forced to 0",
    "TRUCKTOLL": "PRESENT; NOT mapped to average_toll_cost",
    "Speed_Limit": "Retained on model parquet (see model_parquet rows)",
    "AB_FinalSpeed": "Retained on model parquet",
    "BA_FinalSpeed": "Retained on model parquet",
    "STATE": "Retained on model parquet",
    "County_Name": "Retained on model parquet",
    "FAFZONE": "Retained on model parquet",
    "Road_Name": "Retained on model parquet",
    "F_Class": "HPMS functional class — on GDB only, not on model parquet",
    "Facility_Type": "On GDB only, not on model parquet",
    "NHS": "On GDB only",
    "NHFN": "On GDB only",
    "Truck": "On GDB only",
    "SHAPE_Length": "Native shape length; model prefers LENGTH",
}

MODEL_USE_GPQ = {
    "e_id": "Link ID (from FAF5 ID)",
    "from_id": "Derived node connectivity",
    "to_id": "Derived node connectivity",
    "geometry": "Reprojected geometry (binary WKB in parquet)",
    "length": "Meters (from LENGTH miles)",
    "road_classification": "Coarse class from FAF5 Class mapping",
    "lanes": "max(AB,BA) with default fill",
    "urban": "1 if Urban_Code != 99999",
    "averageWidth": "lanes * m/lane; NBI override if bridged",
    "average_toll_cost": "Forced default 0.0 (toll fields unused)",
    "road_bridge": "NBI bridge index yes/no",
    "Road_Name": "Carried from GDB (extra vs minimal convert)",
    "STATE": "Carried from GDB",
    "County_Name": "Carried from GDB",
    "FAFZONE": "Carried from GDB",
    "Speed_Limit": "Carried from GDB (mph); assignment free-flow still from class profiles",
    "AB_FinalSpeed": "Carried from GDB",
    "BA_FinalSpeed": "Carried from GDB",
}


def nonempty_mask(a: np.ndarray) -> np.ndarray:
    if np.issubdtype(a.dtype, np.number):
        return np.isfinite(a.astype(float))
    out = np.zeros(len(a), dtype=bool)
    for i, v in enumerate(a):
        if v is None:
            continue
        s = str(v).strip()
        if s and s.lower() not in ("none", "nan", "nat", "null", ""):
            out[i] = True
    return out


def summarize_attr(name, a, n, source, model_use=""):
    if np.issubdtype(a.dtype, np.number):
        finite = np.isfinite(a.astype(float))
        vals = a.astype(float)[finite]
        return {
            "source": source,
            "attribute": name,
            "dtype": str(a.dtype),
            "n": n,
            "n_nonmissing": int(finite.sum()),
            "pct_nonmissing": round(100 * finite.mean(), 3) if n else 0,
            "n_unique": int(len(np.unique(vals))) if len(vals) else 0,
            "min": float(np.min(vals)) if len(vals) else "",
            "p25": float(np.percentile(vals, 25)) if len(vals) else "",
            "median": float(np.median(vals)) if len(vals) else "",
            "p75": float(np.percentile(vals, 75)) if len(vals) else "",
            "max": float(np.max(vals)) if len(vals) else "",
            "mean": float(np.mean(vals)) if len(vals) else "",
            "top_values": "",
            "model_use": model_use,
        }
    mask = nonempty_mask(a)
    c: Counter = Counter()
    for v, m in zip(a, mask):
        if m:
            c[str(v).strip()] += 1
    top = "; ".join(f"{k}:{v}" for k, v in c.most_common(8))
    return {
        "source": source,
        "attribute": name,
        "dtype": "string/object",
        "n": n,
        "n_nonmissing": int(mask.sum()),
        "pct_nonmissing": round(100 * mask.mean(), 3) if n else 0,
        "n_unique": len(c),
        "min": "",
        "p25": "",
        "median": "",
        "p75": "",
        "max": "",
        "mean": "",
        "top_values": top[:500],
        "model_use": model_use,
    }


def category_labels(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values)
    n = len(values)
    mask = nonempty_mask(values)
    cats = np.empty(n, dtype=object)
    cats[:] = "<missing>"
    for i in range(n):
        if not mask[i]:
            continue
        v = values[i]
        if isinstance(v, (float, np.floating)) and np.isfinite(v) and float(v).is_integer():
            cats[i] = str(int(v))
        elif isinstance(v, (int, np.integer)):
            cats[i] = str(int(v))
        else:
            cats[i] = str(v).strip()
    return cats


def categorical_rows(
    source,
    attr,
    values,
    length=None,
    extra_numeric=None,
    max_levels=None,
):
    values = np.asarray(values)
    n = len(values)
    cats = category_labels(values)
    counts = Counter(cats.tolist())
    items = counts.most_common()
    if max_levels is not None and len(items) > max_levels:
        emit = items[:max_levels]
        other_n = sum(v for _, v in items[max_levels:])
        if other_n:
            emit.append(("<other_collapsed>", other_n))
    else:
        emit = items

    length = None if length is None else np.asarray(length, dtype=float)
    extra_numeric = extra_numeric or {}
    rows = []
    for cat, cnt in emit:
        m = cats == cat
        row = {
            "source": source,
            "attribute": attr,
            "category": cat,
            "n": int(cnt),
            "pct_of_links": round(100 * cnt / n, 4) if n else 0,
        }
        if length is not None:
            lv = length[m]
            lv = lv[np.isfinite(lv)]
            row["length_sum"] = float(np.sum(lv)) if len(lv) else ""
            row["length_mean"] = float(np.mean(lv)) if len(lv) else ""
            row["length_median"] = float(np.median(lv)) if len(lv) else ""
        else:
            row["length_sum"] = row["length_mean"] = row["length_median"] = ""
        for ename, earr in extra_numeric.items():
            earr = np.asarray(earr, dtype=float)
            ev = earr[m]
            ev = ev[np.isfinite(ev)]
            row[f"{ename}_mean"] = float(np.mean(ev)) if len(ev) else ""
            row[f"{ename}_median"] = float(np.median(ev)) if len(ev) else ""
        rows.append(row)
    return rows


def main():
    if not GDB.exists():
        raise FileNotFoundError(f"FAF5 GDB not found: {GDB}")
    if not GPQ.exists():
        raise FileNotFoundError(f"Model parquet not found: {GPQ}")

    attr_rows = []
    cat_rows = []

    print("Reading GDB...")
    meta, _, _, arrays = read(str(GDB), layer="FAF5_Links", read_geometry=False)
    gdb_names = list(meta["fields"])
    gdb = {n: np.asarray(a) for n, a in zip(gdb_names, arrays)}
    n_gdb = len(next(iter(gdb.values())))
    print(f"GDB n={n_gdb}")

    for name in gdb_names:
        attr_rows.append(
            summarize_attr(
                name,
                gdb[name],
                n_gdb,
                "gdb_FAF5_Links",
                MODEL_USE_GDB.get(
                    name, "GDB attribute; see model_parquet for assignment mapping"
                ),
            )
        )

    gdb_cats = {
        "DIR": None,
        "Class": None,
        "Class_Description": None,
        "Country": None,
        "STATE": None,
        "Status": None,
        "F_Class": None,
        "Facility_Type": None,
        "NHS": None,
        "STRAHNET": None,
        "NHFN": None,
        "Truck": None,
        "Toll_Type": None,
        "Urban_Code": 30,
        "Rte_Type": None,
        "AdjustReason": None,
        "BorderLink": None,
    }
    length_mi = gdb["LENGTH"].astype(float)
    for attr, max_lv in gdb_cats.items():
        if attr not in gdb:
            continue
        extra = {}
        if attr in (
            "F_Class",
            "Facility_Type",
            "Class",
            "Class_Description",
            "Toll_Type",
            "Truck",
            "NHS",
            "NHFN",
        ):
            extra["Speed_Limit"] = gdb["Speed_Limit"]
            extra["AB_Lanes"] = gdb["AB_Lanes"]
        rows = categorical_rows(
            "gdb_FAF5_Links",
            attr,
            gdb[attr],
            length=length_mi,
            extra_numeric=extra,
            max_levels=max_lv,
        )
        cat_rows.extend(rows)
        print(f"  GDB cat {attr}: {len(rows)} levels")

    print("Reading model parquet...")
    wanted = [c for c in pq.ParquetFile(str(GPQ)).schema_arrow.names if c != "geometry"]
    table = pq.read_table(str(GPQ), columns=wanted)
    gpq = {c: table.column(c).to_numpy(zero_copy_only=False) for c in wanted}
    n_gpq = len(gpq["e_id"])
    print(f"GPQ n={n_gpq} path={GPQ}")

    attr_rows.append(
        {
            "source": "model_parquet",
            "attribute": "geometry",
            "dtype": "binary(WKB)",
            "n": n_gpq,
            "n_nonmissing": n_gpq,
            "pct_nonmissing": 100.0,
            "n_unique": "",
            "min": "",
            "p25": "",
            "median": "",
            "p75": "",
            "max": "",
            "mean": "",
            "top_values": "",
            "model_use": MODEL_USE_GPQ["geometry"] + f" | file={GPQ}",
        }
    )
    for name in wanted:
        attr_rows.append(
            summarize_attr(
                name,
                gpq[name],
                n_gpq,
                "model_parquet",
                MODEL_USE_GPQ.get(name, ""),
            )
        )

    gpq_cats = {
        "road_classification": None,
        "road_bridge": None,
        "urban": None,
        "lanes": None,
        "STATE": None,
        "FAFZONE": 40,
        "Speed_Limit": None,
    }
    length_m = gpq["length"].astype(float)
    for attr, max_lv in gpq_cats.items():
        if attr not in gpq:
            continue
        extra = {}
        if attr in ("road_classification", "road_bridge", "urban", "lanes"):
            if "Speed_Limit" in gpq:
                extra["Speed_Limit"] = gpq["Speed_Limit"]
            if "averageWidth" in gpq:
                extra["averageWidth"] = gpq["averageWidth"]
            if "AB_FinalSpeed" in gpq:
                extra["AB_FinalSpeed"] = gpq["AB_FinalSpeed"]
        rows = categorical_rows(
            "model_parquet",
            attr,
            gpq[attr],
            length=length_m,
            extra_numeric=extra,
            max_levels=max_lv,
        )
        cat_rows.extend(rows)
        print(f"  GPQ cat {attr}: {len(rows)} levels")

    fields = [
        "source",
        "attribute",
        "dtype",
        "n",
        "n_nonmissing",
        "pct_nonmissing",
        "n_unique",
        "min",
        "p25",
        "median",
        "p75",
        "max",
        "mean",
        "top_values",
        "model_use",
    ]
    OUT_ATTR.parent.mkdir(parents=True, exist_ok=True)
    with OUT_ATTR.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(attr_rows)

    cat_fields = [
        "source",
        "attribute",
        "category",
        "n",
        "pct_of_links",
        "length_sum",
        "length_mean",
        "length_median",
    ]
    extras = sorted({k for r in cat_rows for k in r if k not in cat_fields})
    cat_fields = cat_fields + extras
    with OUT_CAT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cat_fields, extrasaction="ignore")
        w.writeheader()
        for r in cat_rows:
            w.writerow({k: r.get(k, "") for k in cat_fields})

    print(f"wrote {OUT_ATTR} attr_rows={len(attr_rows)}")
    print(f"wrote {OUT_CAT} cat_rows={len(cat_rows)}")
    for src, attr in [
        ("gdb_FAF5_Links", "F_Class"),
        ("gdb_FAF5_Links", "Facility_Type"),
        ("model_parquet", "road_classification"),
    ]:
        sub = [r for r in cat_rows if r["source"] == src and r["attribute"] == attr]
        print(f"--- {src}.{attr} ---")
        for r in sorted(sub, key=lambda x: -x["n"]):
            print(
                f"  {r['category']}: n={r['n']} ({r['pct_of_links']}%) "
                f"len_mean={r['length_mean']}"
            )


if __name__ == "__main__":
    main()
