"""
Transfer HPMS section attributes onto FAF5 links via LRS measure overlap.

Uses FAF fields HPMS_USA_RouteID + HPMS_Begin_Point + HPMS_End_Point
against HPMS Route_ID + Begin_Point + End_Point (year may differ; expect gaps).

Outputs (under --out-dir):
  faf_hpms_lrs_enriched.csv   - one row per keyed FAF link
  qa_summary.json             - match / coverage metrics
  qa_report.html              - charts + how-to-check guide
  sample_matched.geojson      - small map sample of matched links
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pyogrio
from pyogrio.raw import read


ATTR_FIELDS = [
    "Terrain_Type",
    "STRUCTURE_TYPE",
    "TOL_CHARGED",
    "TOLL_TYPE",
    "THROUGH_LANES",
    "F_SYSTEM",
    "URBAN_CODE",
]

STATE_TO_LAYER = {
    # HPMS layers are HPMS_FULL_{ST}_2020
}


def nonempty(x) -> bool:
    if x is None:
        return False
    if isinstance(x, float) and math.isnan(x):
        return False
    s = str(x).strip()
    return s not in ("", "None", "nan", "NaN", "<NA>")


def as_float(x):
    try:
        v = float(x)
        return v if math.isfinite(v) else np.nan
    except Exception:
        return np.nan


def as_int_or_none(x):
    if x is None:
        return None
    if isinstance(x, float) and math.isnan(x):
        return None
    try:
        # FileGDB null ints sometimes appear as very large/small sentinels
        v = int(x)
        if abs(v) > 10**9:
            return None
        return v
    except Exception:
        return None


def predominance(length_by_val: dict[object, float]):
    """Length-weighted mode; ties -> smaller key for stability."""
    if not length_by_val:
        return None, 0.0, 0.0
    total = sum(length_by_val.values())
    best_val, best_len = None, -1.0
    for val, leng in length_by_val.items():
        if leng > best_len or (leng == best_len and (best_val is None or str(val) < str(best_val))):
            best_val, best_len = val, leng
    return best_val, best_len, total


def load_faf_keyed(faf_gdb: str):
    cols = [
        "ID",
        "STATE",
        "STFIPS",
        "Class",
        "F_Class",
        "Urban_Code",
        "Facility_Type",
        "LENGTH",
        "HPMS_USA_RouteID",
        "HPMS_Begin_Point",
        "HPMS_End_Point",
        "Road_Name",
        "Sign_Rte",
    ]
    meta, _, _, arrays = read(faf_gdb, layer="FAF5_Links", columns=cols, read_geometry=False)
    d = {n: np.asarray(a) for n, a in zip(meta["fields"], arrays)}
    n = len(d["ID"])
    keyed_mask = []
    for i in range(n):
        ok = (
            nonempty(d["HPMS_USA_RouteID"][i])
            and math.isfinite(as_float(d["HPMS_Begin_Point"][i]))
            and math.isfinite(as_float(d["HPMS_End_Point"][i]))
        )
        keyed_mask.append(ok)
    keyed_mask = np.asarray(keyed_mask, dtype=bool)

    rows = []
    for i in np.flatnonzero(keyed_mask):
        rid = str(d["HPMS_USA_RouteID"][i]).strip()
        st = str(d["STATE"][i]).strip()
        # FAF convention: {ST}_{Route_ID}
        if "_" in rid and rid[:2].upper() == st.upper():
            route = rid.split("_", 1)[1]
        elif rid.upper().startswith(st.upper() + "_"):
            route = rid[len(st) + 1 :]
        else:
            route = rid.split("_", 1)[1] if "_" in rid else rid
        b = as_float(d["HPMS_Begin_Point"][i])
        e = as_float(d["HPMS_End_Point"][i])
        if e < b:
            b, e = e, b
        rows.append(
            {
                "ID": int(d["ID"][i]),
                "STATE": st,
                "Class": as_float(d["Class"][i]),
                "F_Class": as_float(d["F_Class"][i]),
                "Urban_Code": str(d["Urban_Code"][i]) if nonempty(d["Urban_Code"][i]) else "",
                "LENGTH": as_float(d["LENGTH"][i]),
                "HPMS_USA_RouteID": rid,
                "route_id": route,
                "beg": b,
                "end": e,
                "meas_len": e - b,
                "Road_Name": str(d["Road_Name"][i]) if nonempty(d["Road_Name"][i]) else "",
                "Sign_Rte": str(d["Sign_Rte"][i]) if nonempty(d["Sign_Rte"][i]) else "",
            }
        )
    return rows, n, int(keyed_mask.sum())


def load_hpms_state(hpms_zip_gdb: str, state: str, needed_routes: set[str]):
    layer = f"HPMS_FULL_{state}_2020"
    layers = {L[0] for L in pyogrio.list_layers(hpms_zip_gdb)}
    if layer not in layers:
        return None, f"missing layer {layer}"

    info = pyogrio.read_info(hpms_zip_gdb, layer=layer)
    available = set(info["fields"])
    cols = ["Route_ID", "Begin_Point", "End_Point"] + [f for f in ATTR_FIELDS if f in available]
    meta, _, _, arrays = read(hpms_zip_gdb, layer=layer, columns=cols, read_geometry=False)
    d = {n: np.asarray(a) for n, a in zip(meta["fields"], arrays)}

    # Index only routes needed by FAF
    by_route: dict[str, list] = defaultdict(list)
    n = len(d["Route_ID"])
    for i in range(n):
        rid = d["Route_ID"][i]
        if not nonempty(rid):
            continue
        rid = str(rid)
        if rid not in needed_routes:
            continue
        b = as_float(d["Begin_Point"][i])
        e = as_float(d["End_Point"][i])
        if not (math.isfinite(b) and math.isfinite(e)):
            continue
        if e < b:
            b, e = e, b
        attrs = {}
        for f in ATTR_FIELDS:
            if f not in d:
                attrs[f] = None
            else:
                attrs[f] = as_int_or_none(d[f][i])
        by_route[rid].append((b, e, attrs))

    for rid in by_route:
        by_route[rid].sort(key=lambda t: t[0])
    return by_route, None


def transfer_state(faf_rows: list[dict], by_route: dict[str, list] | None):
    out = []
    stats = Counter()
    for row in faf_rows:
        rec = dict(row)
        route = row["route_id"]
        if by_route is None:
            stats["hpms_layer_missing"] += 1
            rec.update(_empty_transfer())
            out.append(rec)
            continue
        segs = by_route.get(route)
        if not segs:
            stats["route_not_in_hpms"] += 1
            rec.update(_empty_transfer())
            out.append(rec)
            continue

        fb, fe = row["beg"], row["end"]
        overlap_total = 0.0
        buckets = {f: Counter() for f in ATTR_FIELDS}  # value -> length

        # linear scan; segments sorted, still fine for typical counts
        for hb, he, attrs in segs:
            if he <= fb:
                continue
            if hb >= fe:
                break
            ov = min(fe, he) - max(fb, hb)
            if ov <= 0:
                continue
            overlap_total += ov
            for f in ATTR_FIELDS:
                val = attrs.get(f)
                if val is None:
                    continue
                buckets[f][val] += ov

        meas = row["meas_len"] if row["meas_len"] > 0 else np.nan
        cov = overlap_total / meas if meas and meas > 0 else 0.0
        rec["overlap_miles_meas"] = overlap_total
        rec["measure_coverage"] = cov
        rec["route_found"] = 1
        rec["has_overlap"] = 1 if overlap_total > 0 else 0

        for f in ATTR_FIELDS:
            # Counter as length_by_val
            length_by_val = dict(buckets[f])
            val, best_len, tot = predominance(length_by_val)
            rec[f"hpms_{f}"] = val if tot > 0 else None
            rec[f"hpms_{f}_share"] = (best_len / tot) if tot > 0 else None

        if overlap_total > 0:
            stats["matched_overlap"] += 1
        else:
            stats["route_found_no_overlap"] += 1
        out.append(rec)
    return out, stats


def _empty_transfer():
    rec = {
        "overlap_miles_meas": 0.0,
        "measure_coverage": 0.0,
        "route_found": 0,
        "has_overlap": 0,
    }
    for f in ATTR_FIELDS:
        rec[f"hpms_{f}"] = None
        rec[f"hpms_{f}_share"] = None
    return rec


def write_csv(path: Path, rows: list[dict]):
    if not rows:
        path.write_text("")
        return
    fields = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def svg_bar(items: list[tuple[str, float]], title: str, width=720, bar_h=18, max_n=20) -> str:
    items = items[:max_n]
    if not items:
        return f"<p><b>{title}</b>: no data</p>"
    max_v = max(v for _, v in items) or 1
    height = 40 + len(items) * (bar_h + 6)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">']
    parts.append(f'<text x="8" y="18" font-family="Segoe UI,Arial" font-size="14">{title}</text>')
    y = 32
    for label, val in items:
        w = int(360 * val / max_v)
        parts.append(f'<text x="8" y="{y + bar_h - 4}" font-family="Segoe UI,Arial" font-size="11">{label}</text>')
        parts.append(f'<rect x="120" y="{y}" width="{w}" height="{bar_h}" fill="#2f6fad"/>')
        parts.append(
            f'<text x="{130 + w}" y="{y + bar_h - 4}" font-family="Segoe UI,Arial" font-size="11">{val:,.0f}</text>'
        )
        y += bar_h + 6
    parts.append("</svg>")
    return "\n".join(parts)


def write_sample_geojson(
    faf_gdb: str,
    matched_ids: list[int],
    out_path: Path,
    enrich_by_id: dict[int, dict] | None = None,
    limit=800,
):
    """Write a small GeoJSON sample of matched FAF links for map QA."""
    ids = set(matched_ids[:limit])
    if not ids:
        out_path.write_text('{"type":"FeatureCollection","features":[]}')
        return 0

    # pyogrio.raw.read -> (meta, None, geometry_wkb, field_arrays)
    meta, _, wkb, arrays = read(
        faf_gdb,
        layer="FAF5_Links",
        columns=["ID", "STATE", "Class", "LENGTH", "HPMS_USA_RouteID", "Sign_Rte", "F_Class"],
        read_geometry=True,
    )
    d = {n: np.asarray(a) for n, a in zip(meta["fields"], arrays)}
    features = []
    for i in range(len(d["ID"])):
        fid = int(d["ID"][i])
        if fid not in ids:
            continue
        geom = wkb_to_geojson_geometry(wkb[i])
        if geom is None:
            continue
        props = {
            "ID": fid,
            "STATE": str(d["STATE"][i]),
            "Class": float(d["Class"][i]) if d["Class"][i] == d["Class"][i] else None,
            "F_Class": float(d["F_Class"][i]) if d["F_Class"][i] == d["F_Class"][i] else None,
            "LENGTH": float(d["LENGTH"][i]) if d["LENGTH"][i] == d["LENGTH"][i] else None,
            "HPMS_USA_RouteID": str(d["HPMS_USA_RouteID"][i]),
            "Sign_Rte": str(d["Sign_Rte"][i]) if nonempty(d["Sign_Rte"][i]) else "",
        }
        if enrich_by_id and fid in enrich_by_id:
            er = enrich_by_id[fid]
            props.update(
                {
                    "measure_coverage": er.get("measure_coverage"),
                    "hpms_Terrain_Type": er.get("hpms_Terrain_Type"),
                    "hpms_STRUCTURE_TYPE": er.get("hpms_STRUCTURE_TYPE"),
                    "hpms_TOL_CHARGED": er.get("hpms_TOL_CHARGED"),
                    "hpms_F_SYSTEM": er.get("hpms_F_SYSTEM"),
                    "hpms_THROUGH_LANES": er.get("hpms_THROUGH_LANES"),
                }
            )
        features.append({"type": "Feature", "properties": props, "geometry": geom})
        if len(features) >= limit:
            break
    out_path.write_text(json.dumps({"type": "FeatureCollection", "features": features}))
    return len(features)


def wkb_to_geojson_geometry(wkb_bytes):
    """Minimal WKB reader for LineString/MultiLineString (XY or XYM/XYZM stripped to XY)."""
    if wkb_bytes is None:
        return None
    import struct

    mv = memoryview(wkb_bytes)
    if len(mv) < 5:
        return None
    endian = "<" if mv[0] == 1 else ">"
    gtype = struct.unpack_from(endian + "I", mv, 1)[0]
    # Strip EWKB SRID flag if present
    has_srid = bool(gtype & 0x20000000)
    coord_type = gtype & 0xFFFF
    # Handle ISO WKB Z/M: 1000 Z, 2000 M, 3000 ZM added to type
    base = coord_type % 1000
    dim_code = coord_type // 1000
    dims = {0: 2, 1: 3, 2: 3, 3: 4}.get(dim_code, 2)
    # EWKB style
    if gtype & 0x80000000:
        dims = max(dims, 3)
    if gtype & 0x40000000:
        dims = max(dims, 3 if dims == 2 else 4)

    off = 5
    if has_srid:
        off += 4

    def read_line(offset):
        (npts,) = struct.unpack_from(endian + "I", mv, offset)
        offset += 4
        coords = []
        for _ in range(npts):
            vals = struct.unpack_from(endian + "d" * dims, mv, offset)
            offset += 8 * dims
            coords.append([vals[0], vals[1]])
        return coords, offset

    try:
        if base == 2:  # LineString
            coords, _ = read_line(off)
            return {"type": "LineString", "coordinates": coords}
        if base == 5:  # MultiLineString
            (nlines,) = struct.unpack_from(endian + "I", mv, off)
            off += 4
            lines = []
            for _ in range(nlines):
                # nested endian + type
                off += 1 + 4
                # nested may also have srid/dim flags; assume same dims without srid for ISO
                coords, off = read_line(off)
                lines.append(coords)
            return {"type": "MultiLineString", "coordinates": lines}
    except Exception:
        return None
    return None


def build_html(summary: dict, out_rows: list[dict], sample_geojson_name: str) -> str:
    by_state = summary["by_state"]
    state_items = sorted(
        ((st, v["matched_overlap_links"]) for st, v in by_state.items()),
        key=lambda t: -t[1],
    )
    cov_items = sorted(
        (
            (st, 100.0 * v["matched_overlap_miles"] / v["keyed_miles"] if v["keyed_miles"] else 0)
            for st, v in by_state.items()
            if v["keyed_miles"] > 0
        ),
        key=lambda t: -t[1],
    )
    class_items = sorted(summary["by_class_match_pct"].items(), key=lambda t: t[0])

    attr_fill = summary["attribute_fill_on_overlap"]
    attr_items = [(k, 100.0 * v) for k, v in attr_fill.items()]

    # F_Class agreement where both present
    agree = summary.get("f_class_agreement", {})

    guide = """
<h2>How to visualize &amp; check quality</h2>
<ol>
  <li><b>Start with the summary numbers</b> below: keyed coverage, route-ID hit rate, measure overlap coverage.</li>
  <li><b>Map the sample GeoJSON</b> (<code>{gj}</code>) in QGIS/ArcGIS or the Leaflet map on this page.
      Join/enrich CSV to full FAF on <code>ID</code> for national maps.</li>
  <li><b>Color by</b> <code>measure_coverage</code> (0–1). Good transfers cluster near 1.0 on Interstates.</li>
  <li><b>Color by</b> <code>hpms_Terrain_Type</code> / <code>hpms_STRUCTURE_TYPE</code> and spot-check against imagery
      (bridges/tunnels, mountain corridors).</li>
  <li><b>Compare</b> <code>hpms_F_SYSTEM</code> vs FAF <code>F_Class</code> — agreement rate is a sanity check
      that RouteID/measures landed on the right road.</li>
  <li><b>Flag failures</b>: <code>route_found=0</code> (2018 FAF key absent in 2020 HPMS),
      <code>route_found=1 &amp; has_overlap=0</code> (same RouteID, measures don’t overlap — year/LRS drift).</li>
  <li><b>Don’t expect matches</b> on ramps/centroid connectors — they rarely carry HPMS keys.</li>
</ol>
""".format(gj=sample_geojson_name)

    leaflet = f"""
<h2>Map sample (matched links)</h2>
<div id="map" style="height:480px;border:1px solid #ccc;"></div>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
fetch('{sample_geojson_name}').then(r=>r.json()).then(gj=>{{
  const map = L.map('map');
  L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
    maxZoom: 18, attribution: '&copy; OpenStreetMap'
  }}).addTo(map);
  const layer = L.geoJSON(gj, {{
    style: {{color:'#c0392b', weight:3}},
    onEachFeature: (f,l)=>l.bindPopup(Object.entries(f.properties).map(([k,v])=>k+': '+v).join('<br>'))
  }}).addTo(map);
  if (layer.getBounds().isValid()) map.fitBounds(layer.getBounds(), {{padding:[20,20]}});
}});
</script>
"""

    return f"""<!doctype html>
<html><head><meta charset="utf-8"/><title>HPMS→FAF LRS Transfer QA</title>
<style>
body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;max-width:980px;color:#222}}
table{{border-collapse:collapse;margin:12px 0}}
th,td{{border:1px solid #ddd;padding:6px 10px;font-size:13px}}
th{{background:#f4f6f8;text-align:left}}
.kpi{{display:inline-block;margin:8px 12px 8px 0;padding:10px 14px;background:#f4f6f8;border-radius:8px}}
.kpi b{{display:block;font-size:20px}}
</style></head><body>
<h1>HPMS → FAF5 LRS transfer QA</h1>
<p>Overlap join on <code>HPMS_USA_RouteID</code> / measures → HPMS <code>Route_ID</code> / <code>Begin_Point</code>–<code>End_Point</code>.
Categorical values use <b>length-weighted predominance</b> along the FAF measure interval.</p>
{guide}
<div class="kpi"><span>FAF links total</span><b>{summary['faf_links_total']:,}</b></div>
<div class="kpi"><span>Keyed links</span><b>{summary['faf_keyed_links']:,}</b></div>
<div class="kpi"><span>Overlap matches</span><b>{summary['matched_overlap_links']:,}</b></div>
<div class="kpi"><span>Keyed miles matched</span><b>{summary['matched_overlap_miles']:,.0f}</b></div>
<div class="kpi"><span>% keyed miles matched</span><b>{100*summary['matched_overlap_miles']/max(summary['keyed_miles'],1):.1f}%</b></div>
<div class="kpi"><span>% all USA miles matched</span><b>{100*summary['matched_overlap_miles']/max(summary['usa_miles'],1):.1f}%</b></div>

<h2>Failure breakdown (keyed links)</h2>
<table>
<tr><th>Status</th><th>Links</th></tr>
<tr><td>Matched with measure overlap</td><td>{summary['matched_overlap_links']:,}</td></tr>
<tr><td>RouteID found, no measure overlap</td><td>{summary['route_found_no_overlap']:,}</td></tr>
<tr><td>RouteID not in HPMS 2020</td><td>{summary['route_not_in_hpms']:,}</td></tr>
<tr><td>HPMS state layer missing</td><td>{summary['hpms_layer_missing']:,}</td></tr>
</table>

<h2>Attribute fill among overlap matches</h2>
{svg_bar(attr_items, "Percent of overlap-matched links with non-null HPMS value")}

<h2>F_SYSTEM vs FAF F_Class agreement (overlap matches)</h2>
<p>Compared where both non-null: <b>{agree.get('n',0):,}</b> links;
agree <b>{100*agree.get('rate',0):.1f}%</b>. Useful as a join sanity check.</p>

<h2>Matched links by state</h2>
{svg_bar(state_items, "Overlap-matched FAF links by state")}

<h2>Measure coverage of keyed miles by state (%)</h2>
{svg_bar([(a,b) for a,b in cov_items], "% of keyed FAF miles with HPMS overlap")}

<h2>Match rate by FAF Class (among keyed)</h2>
{svg_bar([(f"Class {k}", v) for k,v in class_items], "% keyed links with overlap match")}

{leaflet}

<h2>STRUCTURE_TYPE / Terrain_Type code reminder</h2>
<ul>
<li>STRUCTURE_TYPE: 1 bridge, 2 tunnel, 3 causeway</li>
<li>Terrain_Type: 0 N/A urban, 1 flat/level, 2 rolling, 3 mountainous</li>
<li>TOL_CHARGED: 1 one direction, 2 both, 3 no toll charged (on toll facility)</li>
</ul>
<p>Outputs: <code>faf_hpms_lrs_enriched.csv</code>, <code>qa_summary.json</code>, <code>{sample_geojson_name}</code></p>
</body></html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--faf-gdb",
        default=r"C:\Users\akothaw\Desktop\data\faf5_data\network_data\FAF5Network.gdb",
    )
    ap.add_argument(
        "--hpms-zip",
        default=r"C:\Users\akothaw\Downloads\HPMS_2020.gdb.zip",
    )
    ap.add_argument(
        "--out-dir",
        default=r"C:\Users\akothaw\Desktop\data\faf5_data\network_data\hpms_transfer",
    )
    ap.add_argument("--states", default="", help="Optional comma list e.g. RI,CT,MA (default: all keyed)")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    hpms_gdb = rf"/vsizip/{args.hpms_zip}/HPMS_2020.gdb"

    t0 = time.time()
    print("Loading keyed FAF links...")
    faf_rows, faf_total, faf_keyed = load_faf_keyed(args.faf_gdb)
    print(f"  FAF total={faf_total:,} keyed={faf_keyed:,}")

    # USA miles from full FAF (quick)
    meta, _, _, arrays = read(
        args.faf_gdb, layer="FAF5_Links", columns=["Country", "LENGTH"], read_geometry=False
    )
    dd = {n: np.asarray(a) for n, a in zip(meta["fields"], arrays)}
    usa_miles = float(
        np.nansum(
            [
                as_float(L)
                for C, L in zip(dd["Country"], dd["LENGTH"])
                if str(C) == "USA"
            ]
        )
    )

    if args.states.strip():
        allow = {s.strip().upper() for s in args.states.split(",") if s.strip()}
        faf_rows = [r for r in faf_rows if r["STATE"].upper() in allow]
        print(f"  Filtered to states {sorted(allow)}: {len(faf_rows):,} keyed links")

    by_state_rows = defaultdict(list)
    for r in faf_rows:
        by_state_rows[r["STATE"].upper()].append(r)

    all_out = []
    global_stats = Counter()
    by_state_summary = {}

    for st in sorted(by_state_rows):
        rows = by_state_rows[st]
        needed = {r["route_id"] for r in rows}
        print(f"[{st}] FAF keyed={len(rows):,} unique routes={len(needed):,} loading HPMS...")
        t1 = time.time()
        by_route, err = load_hpms_state(hpms_gdb, st, needed)
        if err:
            print(f"  WARNING {err}")
        else:
            print(f"  HPMS route hits={len(by_route):,} ({time.time()-t1:.1f}s)")
        transferred, stats = transfer_state(rows, by_route)
        all_out.extend(transferred)
        global_stats.update(stats)

        keyed_miles = sum(r["LENGTH"] for r in transferred if math.isfinite(r["LENGTH"]))
        matched = [r for r in transferred if r["has_overlap"]]
        matched_miles = sum(r["LENGTH"] for r in matched if math.isfinite(r["LENGTH"]))
        by_state_summary[st] = {
            "keyed_links": len(transferred),
            "keyed_miles": keyed_miles,
            "matched_overlap_links": len(matched),
            "matched_overlap_miles": matched_miles,
            "route_not_in_hpms": stats.get("route_not_in_hpms", 0),
            "route_found_no_overlap": stats.get("route_found_no_overlap", 0),
            "hpms_layer_missing": stats.get("hpms_layer_missing", 0),
        }
        print(
            f"  matched={len(matched):,}/{len(transferred):,} "
            f"miles={matched_miles:,.0f}/{keyed_miles:,.0f}"
        )

    # Attribute fill among overlaps
    overlaps = [r for r in all_out if r["has_overlap"]]
    attr_fill = {}
    for f in ATTR_FIELDS:
        key = f"hpms_{f}"
        if not overlaps:
            attr_fill[f] = 0.0
        else:
            attr_fill[f] = sum(1 for r in overlaps if r.get(key) is not None) / len(overlaps)

    # F_Class agreement
    n_agree = n_cmp = 0
    for r in overlaps:
        a = r.get("hpms_F_SYSTEM")
        b = r.get("F_Class")
        if a is None or b is None or (isinstance(b, float) and math.isnan(b)):
            continue
        n_cmp += 1
        if int(a) == int(b):
            n_agree += 1

    # by class match pct among keyed
    by_class = defaultdict(lambda: [0, 0])
    for r in all_out:
        cls = r.get("Class")
        if cls is None or (isinstance(cls, float) and math.isnan(cls)):
            continue
        cls = int(cls)
        by_class[cls][1] += 1
        if r["has_overlap"]:
            by_class[cls][0] += 1
    by_class_match_pct = {
        str(k): (100.0 * v[0] / v[1] if v[1] else 0.0) for k, v in sorted(by_class.items())
    }

    keyed_miles = sum(r["LENGTH"] for r in all_out if math.isfinite(r.get("LENGTH", np.nan)))
    matched_miles = sum(
        r["LENGTH"] for r in all_out if r["has_overlap"] and math.isfinite(r.get("LENGTH", np.nan))
    )

    summary = {
        "faf_links_total": faf_total,
        "faf_keyed_links": faf_keyed,
        "processed_keyed_links": len(all_out),
        "usa_miles": usa_miles,
        "keyed_miles": keyed_miles,
        "matched_overlap_links": sum(1 for r in all_out if r["has_overlap"]),
        "matched_overlap_miles": matched_miles,
        "route_not_in_hpms": global_stats.get("route_not_in_hpms", 0),
        "route_found_no_overlap": global_stats.get("route_found_no_overlap", 0),
        "hpms_layer_missing": global_stats.get("hpms_layer_missing", 0),
        "attribute_fill_on_overlap": attr_fill,
        "f_class_agreement": {"n": n_cmp, "rate": (n_agree / n_cmp if n_cmp else 0.0)},
        "by_state": by_state_summary,
        "by_class_match_pct": by_class_match_pct,
        "elapsed_sec": time.time() - t0,
        "notes": [
            "FAF HPMS keys documented as ~2018; donor is HPMS 2020 — RouteID/measure drift expected.",
            "Transfer applies only to FAF links with HPMS keys (~20% links / ~28% USA miles).",
            "Categorical attributes: length-weighted predominance along overlapping measure range.",
        ],
    }

    csv_path = out_dir / "faf_hpms_lrs_enriched.csv"
    print(f"Writing {csv_path} ...")
    write_csv(csv_path, all_out)

    summary_path = out_dir / "qa_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))

    matched_ids = [r["ID"] for r in all_out if r["has_overlap"]]
    # Prefer a compact northeast sample if present, else first matches
    prefer_states = {"RI", "CT", "MA", "NJ", "DE", "MD", "DC"}
    preferred = [r["ID"] for r in all_out if r["has_overlap"] and r["STATE"] in prefer_states]
    sample_ids = preferred[:600] if preferred else matched_ids[:600]
    gj_name = "sample_matched.geojson"
    print(f"Writing map sample ({len(sample_ids)} ids)...")
    enrich = {r["ID"]: r for r in all_out}
    n_feat = write_sample_geojson(
        args.faf_gdb, sample_ids, out_dir / gj_name, enrich_by_id=enrich, limit=600
    )
    print(f"  GeoJSON features: {n_feat}")

    html_path = out_dir / "qa_report.html"
    html_path.write_text(build_html(summary, all_out, gj_name), encoding="utf-8")

    print("\nDone.")
    print(json.dumps({k: summary[k] for k in summary if k != "by_state"}, indent=2))
    print(f"\nOpen: {html_path}")


if __name__ == "__main__":
    main()
