"""Build Desktop/hpms_la_challenger_progress_map.html.

Shows: Voronoi catchments, demand-graduated centroids, unique-segment
connectors (≤1 per HPMS route_id), per-node reasons sidebar.
"""
from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pyogrio
from shapely.geometry import Point

ART = Path(__file__).resolve().parent / "artifacts"
PROBE = ART / "enclosing_connector_probe.json"
CATCH = ART / "la_subarea_catchments.json"
LINKS = ART / "hpms_la_links_noded.parquet"
COUNTY = Path(r"C:/Users/akothaw/Desktop/data/faf5_data/county_shp/tl_2022_us_county.shp")
OUT = Path(r"C:/Users/akothaw/Desktop/hpms_la_challenger_progress_map.html")
NETWORK_CRS = "EPSG:9311"
LOCAL_ROAD_R_M = 1500.0

CATCH_COLORS = [
    "#4e79a7",
    "#f28e2b",
    "#e15759",
    "#76b7b2",
    "#59a14f",
    "#edc948",
]


def _coords_wgs84(geom) -> list:
    g = geom
    while hasattr(g, "geoms"):
        g = g.geoms[0]
    return [[float(x), float(y)] for x, y in g.coords]


def _esc(s: object) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def main() -> None:
    probe = json.loads(PROBE.read_text(encoding="utf-8"))
    catch = json.loads(CATCH.read_text(encoding="utf-8"))
    rows = probe["rows"]
    catch_by = {
        (c["endpoint"], c["subarea_rank"]): c
        for ep in ("home", "work")
        for c in catch[ep]
    }

    links = gpd.read_parquet(LINKS)
    phys = links[~links["e_id"].astype(str).str.endswith("_r")].copy()

    edge_by_id: dict[str, dict] = {}
    for r in rows:
        lon, lat = r["centroid_lonlat"]
        pt = gpd.GeoSeries([Point(lon, lat)], crs="EPSG:4326").to_crs(NETWORK_CRS).iloc[0]
        bbox = (pt.x - LOCAL_ROAD_R_M, pt.y - LOCAL_ROAD_R_M, pt.x + LOCAL_ROAD_R_M, pt.y + LOCAL_ROAD_R_M)
        local = phys.cx[bbox[0]:bbox[2], bbox[1]:bbox[3]].to_crs(4326)
        for _, e in local.iterrows():
            eid = str(e["e_id"])
            if eid in edge_by_id:
                continue
            coords = _coords_wgs84(e.geometry)
            if len(coords) < 2:
                continue
            edge_by_id[eid] = {"e_id": eid, "tier": e.get("assignment_tier"), "coords": coords}

    for r in rows:
        for c in r["connectors_unique_segment"]:
            eid = str(c["e_id"])
            if eid in edge_by_id:
                continue
            hit = phys[phys["e_id"].astype(str) == eid]
            if hit.empty:
                continue
            e = hit.to_crs(4326).iloc[0]
            coords = _coords_wgs84(e.geometry)
            if len(coords) < 2:
                continue
            edge_by_id[eid] = {"e_id": eid, "tier": e.get("assignment_tier"), "coords": coords}

    la = pyogrio.read_dataframe(COUNTY, where="GEOID='06037'", columns=["GEOID"]).to_crs(4326)
    geom = la.geometry.iloc[0]
    polys = list(geom.geoms) if geom.geom_type == "MultiPolygon" else [geom]
    boundary_rings = [
        [[float(x), float(y)] for x, y in poly.simplify(0.002, preserve_topology=True).exterior.coords]
        for poly in polys
    ]

    catch_polys = []
    for ep in ("work", "home"):
        for c in catch[ep]:
            if not c.get("hull_ring"):
                continue
            catch_polys.append(
                {
                    "endpoint": ep,
                    "rank": c["subarea_rank"],
                    "ring": c["hull_ring"],
                    "color": CATCH_COLORS[c["subarea_rank"] % len(CATCH_COLORS)],
                    "area_km2": c["area_km2"],
                    "weight": c["weight"],
                }
            )

    work, home, connectors = [], [], []
    for r in rows:
        cc = catch_by.get((r["endpoint"], r["subarea_rank"]), {})
        n_unique = r["num_connectors_unique_segment"]
        entry = {
            "rank": r["subarea_rank"],
            "lon": r["centroid_lonlat"][0],
            "lat": r["centroid_lonlat"][1],
            "weight": r["weight"],
            "node_id": r["faf5_node_id"],
            "n_uncapped": r["num_connectors_uncapped"],
            "n_unique": n_unique,
            "n_eligible": r["n_eligible_edges_3km"],
            "enclosed": r["enclosed"],
            "area_km2": cc.get("area_km2"),
            "n_blocks": cc.get("n_blocks"),
            "reasons": r["reasons"],
            "connectors_detail": r["connectors_unique_segment"],
            "color": CATCH_COLORS[r["subarea_rank"] % len(CATCH_COLORS)],
        }
        (work if r["endpoint"] == "work" else home).append(entry)
        for c in r["connectors_unique_segment"]:
            connectors.append(
                {
                    "endpoint": r["endpoint"],
                    "rank": r["subarea_rank"],
                    "old_node": r["faf5_node_id"],
                    "centroid": r["centroid_lonlat"],
                    "mid": c["mid_lonlat"],
                    "road_name": c.get("road_name") or c.get("route_id") or "(unnamed)",
                    "route_id": c.get("route_id"),
                    "tier": c.get("tier"),
                    "length_m": c["length_m"],
                    "e_id": c["e_id"],
                }
            )

    data = {
        "work": work,
        "home": home,
        "connectors": connectors,
        "catchments": catch_polys,
        "la_boundary_rings": boundary_rings,
        "meta": {
            "n_road_edges_drawn": len(edge_by_id),
            "corridor_dedup_m": probe.get("corridor_dedup_m"),
            "catchment_note": catch.get("_note"),
        },
    }

    sidebar = []
    for endpoint, pts in (("work", work), ("home", home)):
        for p in sorted(pts, key=lambda x: x["rank"]):
            reason_lis = "".join(f"<li>{_esc(x)}</li>" for x in p["reasons"])
            conn_lis = "".join(
                "<li><code>{}</code> {} ({}) {:.0f} m"
                "{}</li>".format(
                    _esc(c.get("e_id")),
                    _esc(c.get("road_name") or c.get("route_id") or "(unnamed)"),
                    _esc(c.get("tier")),
                    c["length_m"],
                    f" <span style='color:#666'>[{_esc(c.get('route_id'))}]</span>"
                    if c.get("route_id")
                    else "",
                )
                for c in p["connectors_detail"]
            )
            band = "in-band" if 2 <= p["n_unique"] <= 4 else "out-of-band"
            area = p["area_km2"]
            area_s = f"{area:,.0f} km²" if area is not None else "n/a"
            blocks = p["n_blocks"]
            blocks_s = f"{blocks:,}" if blocks is not None else "n/a"
            sidebar.append(
                f"""
<article class="node-card {band}" id="{endpoint}-{p['rank']}">
  <h3 style="border-left:6px solid {p['color']};padding-left:8px">{endpoint.upper()} #{p['rank']} &middot; FAF {p['node_id']}</h3>
  <div class="meta">demand {(p['weight']*100):.1f}% &middot; catchment {area_s} &middot; {blocks_s} LODES blocks &middot; enclosed: {'yes' if p['enclosed'] else 'NO'}</div>
  <div class="counts">
    <span class="pill bad">uncapped rule: {p['n_uncapped']}</span>
    <span class="pill {'ok' if band=='in-band' else 'bad'}">unique-segment: {p['n_unique']}</span>
    <span class="pill">wanted: 2-4</span>
  </div>
  <h4>Why not / how many under unique-segment rules?</h4>
  <ul>{reason_lis}</ul>
  <h4>Connectors (≤1 per HPMS route_id)</h4>
  <ul class="conn">{conn_lis or '<li><i>none</i></li>'}</ul>
</article>"""
            )

    all_edges_json = json.dumps(list(edge_by_id.values()), separators=(",", ":"))
    data_json = json.dumps(data, separators=(",", ":"))

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>HPMS-LA challenger progress map</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
  html, body {{ margin: 0; padding: 0; height: 100%; font-family: -apple-system, Segoe UI, Arial, sans-serif; }}
  #header {{
    position: absolute; top: 0; left: 0; right: 0; height: 52px; z-index: 1000;
    display: flex; flex-direction: column; justify-content: center;
    padding: 0 14px; background: #1b1b1b; color: #fff; font-size: 13px; box-sizing: border-box;
  }}
  #header b {{ font-size: 14px; }}
  #header .sub {{ color: #bbb; font-size: 12px; }}
  #err {{ display: none; position: absolute; top: 52px; left: 0; right: 400px; z-index: 1001;
         background: #8a1f11; color: #fff; padding: 8px 12px; font-size: 13px; }}
  #map {{ position: absolute; top: 52px; bottom: 0; left: 0; right: 400px; background: #e8eef2; }}
  #sidebar {{
    position: absolute; top: 52px; bottom: 0; right: 0; width: 400px; overflow: auto;
    background: #f7f7f5; border-left: 1px solid #ccc; padding: 12px 14px 40px;
    font-size: 13px; line-height: 1.45; box-sizing: border-box;
  }}
  .node-card {{ background: #fff; border: 1px solid #ddd; border-radius: 6px; padding: 10px 12px; margin-bottom: 12px; }}
  .node-card.out-of-band {{ border-left: 4px solid #d62728; }}
  .node-card.in-band {{ border-left: 4px solid #2ca02c; }}
  .node-card h3 {{ margin: 0 0 4px; font-size: 14px; }}
  .node-card h4 {{ margin: 10px 0 4px; font-size: 12px; color: #444; }}
  .node-card .meta {{ color: #666; font-size: 12px; }}
  .counts {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }}
  .pill {{ display: inline-block; padding: 2px 8px; border-radius: 999px; background: #eee; font-size: 11px; font-weight: 600; }}
  .pill.bad {{ background: #fde2e1; color: #8a1f11; }}
  .pill.ok {{ background: #e3f5e1; color: #1a5c16; }}
  .node-card ul {{ margin: 4px 0 0 18px; padding: 0; }}
  .node-card li {{ margin-bottom: 4px; }}
  .legend-box {{ background: rgba(255,255,255,0.95); padding: 10px 14px; border-radius: 4px;
                 font-size: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.3); line-height: 1.7; max-width: 320px; }}
  .sw {{ display: inline-block; width: 18px; height: 3px; margin-right: 6px; vertical-align: middle; background: #333; }}
  .dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 6px;
          vertical-align: middle; border: 1px solid #222; }}
  .leaflet-tooltip.rank-label {{ font-weight: 700; font-size: 11px; background: rgba(255,255,255,0.92);
                                 border: none; box-shadow: 0 1px 3px rgba(0,0,0,0.3); }}
  .popup-table {{ font-size: 12px; border-collapse: collapse; }}
  .popup-table td {{ padding: 2px 8px 2px 0; }}
  .popup-table td.label {{ color: #666; }}
  code {{ font-size: 11px; }}
</style>
</head>
<body>
<div id="header">
  <b>HPMS-LA challenger — catchments + unique-segment connectors</b>
  <span class="sub">Voronoi catchments (clipped to LA County). Connectors: ≤1 per HPMS route_id, eligible edges only. Offline basemap default.</span>
</div>
<div id="err"></div>
<div id="map"></div>
<aside id="sidebar">
  <p style="margin-top:0"><b>Per-node inventory</b> — demand share + catchment km² + unique-segment connectors (wanted 2–4).</p>
  {"".join(sidebar)}
</aside>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
window.onerror = function(msg, src, line) {{
  var el = document.getElementById('err');
  if (!el) return;
  el.style.display = 'block';
  el.textContent = 'JS error: ' + msg + ' (line ' + line + ')';
}};
</script>
<script>
const ALL_EDGES = {all_edges_json};
const DATA = {data_json};

(function() {{
  if (typeof L === 'undefined') {{
    document.getElementById('err').style.display = 'block';
    document.getElementById('err').textContent = 'Leaflet failed to load.';
    return;
  }}
  var map = L.map('map', {{ preferCanvas: true }}).setView([34.05, -118.25], 10);
  var none = L.layerGroup();
  var esri = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{{z}}/{{y}}/{{x}}', {{
    attribution: 'Tiles &copy; Esri', maxZoom: 19
  }});
  none.addTo(map);

  var canvasRenderer = L.canvas({{ padding: 0.5 }});
  var catchLayer = L.layerGroup();
  var roadLayer = L.layerGroup();
  var boundaryLayer = L.layerGroup();
  var workLayer = L.layerGroup();
  var homeLayer = L.layerGroup();
  var connectorLayer = L.layerGroup();

  (DATA.catchments || []).forEach(function(c) {{
    L.polygon(c.ring.map(function(p) {{ return [p[1], p[0]]; }}), {{
      color: c.color, weight: 2, fillColor: c.color, fillOpacity: 0.18
    }}).addTo(catchLayer).bindPopup(
      c.endpoint + ' #' + c.rank + '<br>catchment ' + c.area_km2.toLocaleString() + ' km²<br>demand ' + (c.weight*100).toFixed(1) + '%'
    );
  }});

  var tierColors = {{ freeway: '#c77dab', arterial: '#2ca02c', collector: '#ff7f0e', local_access: '#999' }};
  ALL_EDGES.forEach(function(e) {{
    if (!e.coords || e.coords.length < 2) return;
    L.polyline(e.coords.map(function(c) {{ return [c[1], c[0]]; }}), {{
      renderer: canvasRenderer, color: tierColors[e.tier] || '#bbb',
      weight: e.tier === 'arterial' ? 1.6 : 1.1, opacity: 0.55
    }}).addTo(roadLayer);
  }});

  (DATA.la_boundary_rings || []).forEach(function(ring) {{
    L.polygon(ring.map(function(c) {{ return [c[1], c[0]]; }}), {{
      color: '#1b1b1b', weight: 2.5, fill: false, dashArray: '8 5'
    }}).addTo(boundaryLayer);
  }});

  function addCentroids(label, pts, fallbackColor, layer) {{
    pts.forEach(function(p) {{
      var radius = 6 + 28 * Math.sqrt(p.weight);
      var marker = L.circleMarker([p.lat, p.lon], {{
        radius: radius, color: '#222', weight: 1.5,
        fillColor: fallbackColor, fillOpacity: 0.9
      }}).addTo(layer);
      marker.bindTooltip(label + ' #' + p.rank + ' (' + p.n_unique + ' conn, ' + (p.area_km2||0).toFixed(0) + ' km²)', {{
        permanent: true, direction: 'top', className: 'rank-label', offset: [0, -6]
      }});
      marker.bindPopup(
        '<table class="popup-table">' +
        '<tr><td class="label">Set</td><td>' + label + '</td></tr>' +
        '<tr><td class="label">Rank</td><td>' + p.rank + '</td></tr>' +
        '<tr><td class="label">FAF node</td><td>' + p.node_id + '</td></tr>' +
        '<tr><td class="label">Demand share</td><td>' + (p.weight*100).toFixed(1) + '%</td></tr>' +
        '<tr><td class="label">Catchment</td><td>' + (p.area_km2||0).toLocaleString() + ' km²</td></tr>' +
        '<tr><td class="label">LODES blocks</td><td>' + (p.n_blocks||0).toLocaleString() + '</td></tr>' +
        '<tr><td class="label">Uncapped</td><td>' + p.n_uncapped + '</td></tr>' +
        '<tr><td class="label">Unique-segment</td><td>' + p.n_unique + '</td></tr>' +
        '</table>'
      );
      marker.on('click', function() {{
        var el = document.getElementById(label.toLowerCase() + '-' + p.rank);
        if (el) el.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
      }});
    }});
  }}
  addCentroids('Work', DATA.work, '#d62728', workLayer);
  addCentroids('Home', DATA.home, '#1f77b4', homeLayer);

  DATA.connectors.forEach(function(c) {{
    L.polyline([[c.centroid[1], c.centroid[0]], [c.mid[1], c.mid[0]]], {{
      color: '#9467bd', weight: 3.5, opacity: 0.9, dashArray: '6 4'
    }}).addTo(connectorLayer).bindPopup(
      c.endpoint + ' #' + c.rank + '<br>' + c.road_name + ' (' + c.tier + ')<br>' +
      c.e_id + '<br>' + c.length_m.toFixed(0) + ' m'
    );
    L.circleMarker([c.mid[1], c.mid[0]], {{
      radius: 4, color: '#222', weight: 1, fillColor: '#9467bd', fillOpacity: 1
    }}).addTo(connectorLayer);
  }});

  catchLayer.addTo(map);
  roadLayer.addTo(map);
  boundaryLayer.addTo(map);
  workLayer.addTo(map);
  homeLayer.addTo(map);
  connectorLayer.addTo(map);

  L.control.layers({{
    'No basemap (offline)': none,
    'Esri streets (optional)': esri
  }}, {{
    'Subarea catchments (Voronoi)': catchLayer,
    'HPMS roads near centroids': roadLayer,
    'LA County boundary': boundaryLayer,
    'Work centroids': workLayer,
    'Home centroids': homeLayer,
    'Unique-segment connectors': connectorLayer
  }}, {{ collapsed: false }}).addTo(map);

  var legend = L.control({{ position: 'bottomleft' }});
  legend.onAdd = function() {{
    var div = L.DomUtil.create('div', 'legend-box');
    div.innerHTML =
      '<b>Legend</b><br>' +
      'Colored fills = Voronoi catchments (non-overlapping)<br>' +
      '<span class="dot" style="background:#d62728"></span> Work &nbsp;' +
      '<span class="dot" style="background:#1f77b4"></span> Home &nbsp;(area ∝ demand share)<br>' +
      '<span class="sw" style="background:#9467bd"></span> Connector (≤1 per HPMS route_id)<br>' +
      '<span class="sw" style="background:#2ca02c"></span> arterial &nbsp;' +
      '<span class="sw" style="background:#ff7f0e"></span> collector';
    return div;
  }};
  legend.addTo(map);
  setTimeout(function() {{ map.invalidateSize(); }}, 100);
}})();
</script>
</body>
</html>
"""
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size/1e6:.2f} MB)")


if __name__ == "__main__":
    main()
