#!/usr/bin/env python3
"""Write Leaflet conflict map (OSM/Esri basemaps) + NBI type/size breakdowns."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd
import pyogrio

OUT = Path(r"C:\Users\akothaw\Desktop\data\faf5_data\network_data\enrichment")
DATA = Path(r"C:\Users\akothaw\Desktop\data\faf5_data")

KIND_LABELS = {
    "0": "Other",
    "1": "Concrete",
    "2": "Concrete continuous",
    "3": "Steel",
    "4": "Steel continuous",
    "5": "Prestressed concrete",
    "6": "Prestressed concrete continuous",
    "7": "Wood or timber",
    "8": "Masonry",
    "9": "Aluminum / wrought or cast iron",
}

TYPE_LABELS = {
    "01": "Slab",
    "02": "Stringer / multi-beam or girder",
    "03": "Girder and floorbeam system",
    "04": "Tee beam",
    "05": "Box beam/girders – multiple",
    "06": "Box beam/girders – single or spread",
    "07": "Frame (except frame culverts)",
    "08": "Orthotropic",
    "09": "Truss – deck",
    "10": "Truss – thru",
    "11": "Arch – deck",
    "12": "Arch – thru",
    "13": "Suspension",
    "14": "Stayed girder",
    "15": "Movable – lift",
    "16": "Movable – bascule",
    "17": "Movable – swing",
    "18": "Tunnel",
    "19": "Culvert",
    "20": "Mixed types",
    "21": "Segmental box girder",
    "22": "Channel beam",
}

LENGTH_BINS = [
    ("< 6 m (short / culvert-scale)", 0, 6),
    ("6–15 m", 6, 15),
    ("15–30 m", 15, 30),
    ("30–60 m", 30, 60),
    ("60–150 m", 60, 150),
    ("≥ 150 m", 150, None),
]

DECK_BINS = [
    ("missing / 0 (NBI unrecorded)", None, None),  # special
    ("< 8 m", 0, 8),
    ("8–12 m", 8, 12),
    ("12–16 m", 12, 16),
    ("16–24 m", 16, 24),
    ("≥ 24 m", 24, None),
]


def _vc_table(series: pd.Series, labels: dict[str, str], *, zfill: int | None = None) -> list[dict]:
    s = series.astype(str).str.strip()
    if zfill:
        s = s.str.zfill(zfill)
    counts = s.value_counts(dropna=False)
    rows = []
    for code, n in counts.items():
        code_s = str(code)
        rows.append(
            {
                "code": code_s,
                "label": labels.get(code_s, f"code {code_s}"),
                "n": int(n),
            }
        )
    return rows


def _bin_length(series: pd.Series) -> list[dict]:
    x = pd.to_numeric(series, errors="coerce")
    rows = []
    for label, lo, hi in LENGTH_BINS:
        if hi is None:
            mask = x >= lo
        else:
            mask = (x >= lo) & (x < hi)
        rows.append({"bin": label, "n": int(mask.fillna(False).sum())})
    rows.append({"bin": "missing / non-numeric", "n": int(x.isna().sum())})
    return rows


def _bin_deck(series: pd.Series) -> list[dict]:
    x = pd.to_numeric(series, errors="coerce")
    # NBI uses 0 as unrecorded for deck width
    missing = x.isna() | (x == 0)
    rows = [{"bin": "missing / 0 (NBI unrecorded)", "n": int(missing.sum())}]
    for label, lo, hi in DECK_BINS:
        if lo is None:
            continue
        if hi is None:
            mask = (~missing) & (x >= lo)
        else:
            mask = (~missing) & (x >= lo) & (x < hi)
        rows.append({"bin": label, "n": int(mask.sum())})
    return rows


def build_type_size_breakdowns() -> dict:
    gpkg = next(DATA.glob("NTAD_National_Bridge_Inventory_*.gpkg"))
    nbi = pyogrio.read_dataframe(
        gpkg,
        layer="National_Bridge_Inventory",
        columns=[
            "STRUCTURE_KIND_043A",
            "STRUCTURE_TYPE_043B",
            "STRUCTURE_LEN_MT_049",
            "DECK_WIDTH_MT_052",
            "MAX_SPAN_LEN_MT_048",
            "MAIN_UNIT_SPANS_045",
        ],
        read_geometry=False,
    )

    bridge_idx = pd.read_parquet(OUT / "faf5_bridge_index.parquet")
    # Dominant-structure fields already on index when built from NTAD load
    for col in ("structure_kind_code", "structure_type_code", "structure_length_m", "deck_width_m"):
        if col not in bridge_idx.columns:
            raise KeyError(
                f"faf5_bridge_index.parquet missing {col}; rebuild with "
                "scripts/build_nbi_bridge_index.py after load_ntad_bridge_gdb.py"
            )

    inv = {
        "total": int(len(nbi)),
        "by_structure_kind": _vc_table(nbi["STRUCTURE_KIND_043A"], KIND_LABELS),
        "by_structure_type": _vc_table(nbi["STRUCTURE_TYPE_043B"], TYPE_LABELS, zfill=2),
        "by_structure_length_m": _bin_length(nbi["STRUCTURE_LEN_MT_049"]),
        "by_deck_width_m": _bin_deck(nbi["DECK_WIDTH_MT_052"]),
        "by_main_unit_spans": _vc_table(
            pd.to_numeric(nbi["MAIN_UNIT_SPANS_045"], errors="coerce")
            .fillna(-1)
            .astype(int)
            .clip(upper=10)
            .astype(str)
            .replace({"-1": "missing", "10": "10+"}),
            {},
        ),
    }
    # nicer span labels
    for row in inv["by_main_unit_spans"]:
        if row["code"] == "missing":
            row["label"] = "missing"
        elif row["code"] == "10+":
            row["label"] = "10+ spans"
        else:
            row["label"] = f"{row['code']} span(s)"

    joined = {
        "total_links": int(len(bridge_idx)),
        "by_structure_kind": _vc_table(bridge_idx["structure_kind_code"], KIND_LABELS),
        "by_structure_type": _vc_table(
            bridge_idx["structure_type_code"], TYPE_LABELS, zfill=2
        ),
        "by_structure_length_m": _bin_length(bridge_idx["structure_length_m"]),
        "by_deck_width_m": _bin_deck(bridge_idx["deck_width_m"]),
    }
    return {"nbi_inventory": inv, "faf_joined_bridges": joined}


def write_csvs(breakdown: dict) -> None:
    pairs = [
        ("nbi_by_structure_kind.csv", breakdown["nbi_inventory"]["by_structure_kind"], ["code", "label", "n"]),
        ("nbi_by_structure_type.csv", breakdown["nbi_inventory"]["by_structure_type"], ["code", "label", "n"]),
        ("nbi_by_structure_length_m.csv", breakdown["nbi_inventory"]["by_structure_length_m"], ["bin", "n"]),
        ("nbi_by_deck_width_m.csv", breakdown["nbi_inventory"]["by_deck_width_m"], ["bin", "n"]),
        ("faf_joined_by_structure_kind.csv", breakdown["faf_joined_bridges"]["by_structure_kind"], ["code", "label", "n"]),
        ("faf_joined_by_structure_type.csv", breakdown["faf_joined_bridges"]["by_structure_type"], ["code", "label", "n"]),
        ("faf_joined_by_structure_length_m.csv", breakdown["faf_joined_bridges"]["by_structure_length_m"], ["bin", "n"]),
        ("faf_joined_by_deck_width_m.csv", breakdown["faf_joined_bridges"]["by_deck_width_m"], ["bin", "n"]),
    ]
    for name, rows, fields in pairs:
        path = OUT / name
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)


def export_faf_network_js(
    road_links_path: Path | None = None,
    *,
    simplify_m: float = 75.0,
    force: bool = False,
) -> Path:
    """Write simplified full FAF network as window.FAF_NETWORK_GEOJSON for the map.

    Uses a separate .js file (script-tag load works for local file:// pages).
    Geometries are simplified in EPSG:9311 then emitted as WGS84 LineStrings
    with ~5-decimal precision. Each feature carries e_id (and Class/state when
    present) for click identify.
    """
    out_js = OUT / "faf_network_layer.js"
    if out_js.exists() and not force and out_js.stat().st_size > 1_000_000:
        print(f"Reusing existing {out_js} ({out_js.stat().st_size / 1e6:.1f} MB)")
        return out_js

    import geopandas as gpd
    from shapely.geometry import MultiLineString

    path = road_links_path
    if path is None:
        patched = OUT / "faf5_road_links_bridge_tunnel_patched.gpq"
        path = patched if patched.exists() else (OUT / "faf5_road_links.gpq")
    if not path.exists():
        raise FileNotFoundError(f"FAF road links not found: {path}")

    print(f"Building full FAF network layer from {path} ...")
    import pyarrow.parquet as pq

    schema_names = set(pq.read_schema(path).names)
    if "e_id" not in schema_names or "geometry" not in schema_names:
        raise KeyError(f"{path} must contain e_id and geometry")
    cols = ["e_id", "geometry"] + [
        c
        for c in ("faf5_class", "STATE", "road_label", "road_bridge", "road_tunnel")
        if c in schema_names
    ]
    links = gpd.read_parquet(path, columns=cols)
    if links.crs is None:
        raise ValueError(f"{path} has no CRS")

    # Simplify in metres, then WGS84 for Leaflet
    geoms_9311 = links.geometry.to_crs(9311).simplify(simplify_m, preserve_topology=False)
    geoms_wgs = gpd.GeoSeries(geoms_9311, crs=9311).to_crs(4326)

    features: list[dict] = []
    for i, geom in enumerate(geoms_wgs):
        if geom is None or geom.is_empty:
            continue
        row = links.iloc[i]
        props: dict = {"e_id": str(row["e_id"])}
        if "faf5_class" in links.columns and pd.notna(row.get("faf5_class")):
            props["faf5_class"] = int(row["faf5_class"])
        if "STATE" in links.columns and pd.notna(row.get("STATE")):
            props["STATE"] = str(row["STATE"])
        if "road_label" in links.columns and pd.notna(row.get("road_label")):
            props["road_label"] = str(row["road_label"])
        if "road_bridge" in links.columns and pd.notna(row.get("road_bridge")):
            props["road_bridge"] = str(row["road_bridge"])
        if "road_tunnel" in links.columns and pd.notna(row.get("road_tunnel")):
            props["road_tunnel"] = str(row["road_tunnel"])

        parts = geom.geoms if isinstance(geom, MultiLineString) else [geom]
        for part in parts:
            if part is None or part.is_empty or len(part.coords) < 2:
                continue
            coords = [
                [round(float(x), 5), round(float(y), 5)] for x, y in part.coords
            ]
            dedup = [coords[0]]
            for c in coords[1:]:
                if c != dedup[-1]:
                    dedup.append(c)
            if len(dedup) < 2:
                continue
            features.append(
                {
                    "type": "Feature",
                    "properties": props,
                    "geometry": {"type": "LineString", "coordinates": dedup},
                }
            )

    geojson = {"type": "FeatureCollection", "features": features}
    out_js.write_text(
        "window.FAF_NETWORK_GEOJSON=" + json.dumps(geojson, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    print(f"Wrote {out_js} ({out_js.stat().st_size / 1e6:.1f} MB, {len(features):,} line parts)")
    return out_js


def write_map_html(data: dict) -> Path:
    payload = json.dumps(data)
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>FAF bridge∩tunnel conflicts (n={data['n_conflicts']})</title>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css"/>
<style>
  html, body, #map {{ height: 100%; margin: 0; }}
  .banner {{
    position: absolute; z-index: 1000; top: 12px; left: 56px; right: 12px;
    max-width: 480px; background: #fff; border: 1px solid #ccc;
    padding: 10px 14px; font-family: system-ui, sans-serif; font-size: 13px;
  }}
  .banner h1 {{ margin: 0 0 4px; font-size: 15px; }}
  .banner p {{ margin: 0; color: #444; line-height: 1.35; }}
  .legend span {{ display: inline-block; width: 12px; height: 12px; margin-right: 4px; vertical-align: middle; }}
</style>
</head>
<body>
<div class="banner">
  <h1>FAF links flagged as both bridge (NBI) and tunnel (NTI)</h1>
  <p>n = {data['n_conflicts']} conflict links. Red = conflict FAF links (on top). Gray = full FAF network underlay (toggle). Blue = NTI portals. Dry-run used <code>prefer_tunnel</code>.</p>
  <p class="legend" style="margin-top:6px">
    <span style="background:#9e9e9e"></span>Full FAF network &nbsp;
    <span style="background:#c62828"></span>Conflict FAF link &nbsp;
    <span style="background:#42a5f5"></span>NTI portal
  </p>
  <p style="margin-top:6px;font-size:11px;color:#666">Basemap: Esri World Street. Click gray FAF network lines for e_id / Class / state. Red conflict links stay on top.</p>
</div>
<div id="map"></div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
<script src="https://unpkg.com/leaflet.vectorgrid@1.3.0/dist/Leaflet.VectorGrid.bundled.js"></script>
<script src="faf_network_layer.js"></script>
<script>
const DATA = {payload};
const map = L.map('map').setView([39.5, -98.35], 4);

// Panes: network under conflict overlays
map.createPane('fafNetworkPane');
map.getPane('fafNetworkPane').style.zIndex = 350;
map.createPane('conflictPane');
map.getPane('conflictPane').style.zIndex = 450;

const esriStreet = L.tileLayer(
  'https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{{z}}/{{y}}/{{x}}',
  {{
    attribution: 'Tiles &copy; Esri — Source: Esri, TomTom, Garmin, FAO, NOAA, USGS, &amp; others',
    maxZoom: 19
  }}
);
const esriImagery = L.tileLayer(
  'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',
  {{
    attribution: 'Tiles &copy; Esri — Source: Esri, Maxar, Earthstar Geographics, &amp; others',
    maxZoom: 19
  }}
);
const esriTopo = L.tileLayer(
  'https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{{z}}/{{y}}/{{x}}',
  {{
    attribution: 'Tiles &copy; Esri — Source: Esri, TomTom, Garmin, USGS, &amp; others',
    maxZoom: 19
  }}
);
esriStreet.addTo(map);

// Full FAF network (underlay) — VectorGrid slicer; clickable for e_id
let fafNetwork = null;
if (window.FAF_NETWORK_GEOJSON && window.FAF_NETWORK_GEOJSON.features) {{
  fafNetwork = L.vectorGrid.slicer(window.FAF_NETWORK_GEOJSON, {{
    rendererFactory: L.canvas.tile,
    vectorTileLayerStyles: {{
      sliced: {{
        weight: 1.2,
        color: '#616161',
        opacity: 0.65,
        fill: false
      }}
    }},
    maxZoom: 18,
    interactive: true,
    getFeatureId: (f) => f.properties && f.properties.e_id,
    pane: 'fafNetworkPane'
  }});
  fafNetwork.on('click', (e) => {{
    const p = (e.layer && e.layer.properties) ? e.layer.properties : {{}};
    const eid = p.e_id != null ? p.e_id : '(no e_id)';
    const klass = p.faf5_class != null ? p.faf5_class : '—';
    const st = p.STATE != null ? p.STATE : '—';
    const label = p.road_label != null ? p.road_label : '—';
    const bridge = p.road_bridge != null ? p.road_bridge : '—';
    const tunnel = p.road_tunnel != null ? p.road_tunnel : '—';
    L.popup({{ maxWidth: 320 }})
      .setLatLng(e.latlng)
      .setContent(
        '<b>FAF link</b><br>' +
        '<b>e_id</b> ' + eid + '<br>' +
        '<b>State</b> ' + st + '<br>' +
        '<b>FAF Class</b> ' + klass + '<br>' +
        '<b>road_label</b> ' + label + '<br>' +
        '<b>road_bridge</b> ' + bridge + '<br>' +
        '<b>road_tunnel</b> ' + tunnel
      )
      .openOn(map);
  }});
  fafNetwork.addTo(map);
}} else {{
  console.warn('FAF_NETWORK_GEOJSON missing — run build_conflict_map.py to generate faf_network_layer.js');
}}

const links = L.geoJSON(DATA.geojson, {{
  pane: 'conflictPane',
  style: () => ({{ color: '#c62828', weight: 4, opacity: 0.95 }}),
  onEachFeature: (f, layer) => {{
    const p = f.properties;
    layer.bindPopup(
      '<b>e_id</b> ' + p.e_id + '<br>' +
      '<b>State</b> ' + p.STATE + '<br>' +
      '<b>FAF Class</b> ' + p.faf5_class + ' — ' + p.faf5_class_label + '<br>' +
      '<i>Both NBI bridge and NTI tunnel within 100 m</i>'
    );
    layer.bindTooltip(p.e_id + ' | ' + p.STATE + ' | Class ' + p.faf5_class);
  }}
}}).addTo(map);

const centroids = L.markerClusterGroup({{ maxClusterRadius: 40, pane: 'conflictPane' }});
DATA.centroids.forEach(p => {{
  const m = L.circleMarker([p.lat, p.lon], {{
    radius: 5, color: '#b71c1c', fillColor: '#ef5350', fillOpacity: 0.9, weight: 1,
    pane: 'conflictPane'
  }});
  m.bindPopup('<b>e_id</b> ' + p.e_id + '<br><b>State</b> ' + p.STATE +
    '<br><b>FAF Class</b> ' + p.faf5_class + ' — ' + p.faf5_class_label);
  m.bindTooltip(p.e_id + ' (' + p.STATE + ')');
  centroids.addLayer(m);
}});
map.addLayer(centroids);

const nti = L.layerGroup();
DATA.nti_portals.forEach(p => {{
  const m = L.circleMarker([p.lat, p.lon], {{
    radius: 4, color: '#1565c0', fillColor: '#42a5f5', fillOpacity: 0.85, weight: 1,
    pane: 'conflictPane'
  }});
  m.bindPopup('<b>NTI</b> ' + p.tunnel_number + '<br><b>Name</b> ' + p.tunnel_name +
    '<br><b>Matched FAF e_id</b> ' + p.e_id + '<br><b>Distance</b> ' + p.dist_m.toFixed(1) + ' m');
  m.bindTooltip('tunnel ' + p.tunnel_number + ' → ' + p.e_id);
  nti.addLayer(m);
}});
map.addLayer(nti);

const overlays = {{
  'Full FAF network': fafNetwork || L.layerGroup(),
  'Conflict FAF links': links,
  'Conflict centroids (clustered)': centroids,
  'NTI portals on conflict links': nti
}};

L.control.layers(
  {{
    'Esri World Street': esriStreet,
    'Esri Imagery': esriImagery,
    'Esri Topo': esriTopo
  }},
  overlays,
  {{ collapsed: false }}
).addTo(map);

if (DATA.centroids.length) {{
  const b = L.latLngBounds(DATA.centroids.map(p => [p.lat, p.lon]));
  map.fitBounds(b.pad(0.15));
}}
</script>
</body>
</html>
"""
    out = OUT / "bridge_tunnel_conflicts_map.html"
    out.write_text(html, encoding="utf-8")
    return out


def main() -> int:
    export_faf_network_js(force=True)
    data = json.loads((OUT / "conflict_map_data.json").read_text(encoding="utf-8"))
    out_html = write_map_html(data)
    print(f"Wrote map {out_html} ({out_html.stat().st_size / 1e6:.2f} MB)")

    breakdown = build_type_size_breakdowns()
    (OUT / "bridge_type_size_breakdown.json").write_text(
        json.dumps(breakdown, indent=2) + "\n", encoding="utf-8"
    )
    write_csvs(breakdown)
    print(
        "NBI kinds top:",
        breakdown["nbi_inventory"]["by_structure_kind"][:3],
    )
    print(
        "FAF-joined kinds top:",
        breakdown["faf_joined_bridges"]["by_structure_kind"][:3],
    )
    print(f"Wrote breakdowns under {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
