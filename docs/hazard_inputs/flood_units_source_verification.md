# Flood depth units — source verification (2026-11-12)

## Verdict

| Event | Native vertical unit | Confidence | Convert to model `m_depth` |
|---|---|---|---|
| **Sandy (305)** | **feet** (water depth above ground, NAVD88) | **Confirmed** — FEMA MOTF item metadata | × **0.3048** |
| **Harvey (304)** | **feet** | **Confirmed** — CUAHSI overview PNG legend `FEMA Harvey 3m Depths (ft)` + FEMA sibling `dgft` products | × **0.3048** |

Aligned GeoTIFFs and raw TIFFs/GDB still carry **no GDAL `units` tag**. Units live in provider docs / filenames / sibling products.

---

## Sandy — confirmed feet

**Source:** FEMA Modeling Task Force (MOTF) / NHRAP ArcGIS Online  
Owner search: `owner:"FEMA_HQ_FIMA_NHRAP"`  
Local raw: `inputs/multihazard_raw/flood/{ct,nj,nys,ri}3m0214c.tif`

Explicit line on FEMA MOTF map-service items (NJ and NY checked first; CT and RI item text read later the same day and state the same line):

> **Vertical: Feet (water depth above ground, NAVD88)**

Example items:
- NJ: https://www.arcgis.com/home/item.html?id=973babe880a147449b2b837aa04ff11d  
- NY: https://www.arcgis.com/home/item.html?id=88ad91324f234cbca9a13855600b7a1f  
- CT: https://www.arcgis.com/home/item.html?id=ddee7f58c532450785a5b3a1c1ceec1d  ("Vertical: Feet (water depth above ground, NAVD88)", 3-meter horizontal, USACE DEM)
- RI: https://www.arcgis.com/home/item.html?id=9363f0a19d214bdeb832eca5e9462b0e  (same line, 3-meter horizontal, USGS 1/9 arc-second NED)

Raw TIFF tags: `units=None` (unit not embedded).

### Aligned values reinterpreted as feet → metres

| Stat | Raw (was mislabeled m) | ×0.3048 → m |
|---|---|---|
| p50 | 5.63 | **1.72** |
| p90 | 9.63 | **2.94** |
| p99 | 13.65 | **4.16** |
| max | 18.11 | **5.52** |

These match known Sandy coastal surge magnitudes; median ~5.6 **metres** does not.

---

## Harvey — feet by strong evidence (Final.gdb untagged)

**Primary source used by prep:** `Harvey_Depths_3m_Final.gdb` → GDAL opens **`Harvey_Depths_3m_v3`**  
HydroShare: https://www.hydroshare.org/resource/e8768f4cb4d5478a96d2b1cbd00d9e85/  
Local: `inputs/multihazard_raw/Harvey_Depths_3m_Final.gdb` (+ CUAHSI package under `Harvey_CUAHSI/`)

### What the HydroShare / README-FEMA Depths Grid.pdf say
- Horizontal resolution **3 metres**
- HWM-based TIN product (Mark English, FEMA Region VIII), Nov 2017
- **Do not state vertical units**

### Evidence that values are feet
1. **CUAHSI overview map** (`3mgrid.zip` → `FEMA-Harvey_zone_depth_grid_3m-Nov2017.png`), packaged with the HydroShare resource: legend title **`FEMA Harvey 3m Depths (ft)`**, bins ≤1 … >30 **ft**, caption “3-meter horiz resolution.” Copied into this audit folder.
2. **NHRAP sibling naming:** `Harris_Mosaic_dgft.zip`, raster `rock_dgftuc` — FEMA **dgft = depth grid feet**. Rockport histogram max ≈ **44.9**.
3. **Coastal modeled DOCX** in CUAHSI package: DEM/surge converted to **feet** (×3.2808); depth = WSEL − DEM.
4. **Value plausibility:** aligned p50 **4.75** / max **148.6** as metres is extreme; as feet → p50 **1.45 m**, max **45.3 m**.

### GDB contents (catalog scan)
Datasets present include: `Harvey_Depths_3m_v3` (default open), `Harvey_EastSide_Final`, `Harvey_WestSide_Final`, extents FCs. Prep did **not** convert units.

### Aligned values reinterpreted as feet → metres

| Stat | Raw (was mislabeled m) | ×0.3048 → m |
|---|---|---|
| p50 | 4.75 | **1.45** |
| p90 | 27.6 | **8.42** |
| p99 | 69.9 | **21.3** |
| max | 148.6 | **45.3** |

After conversion, figure-loader mask `>15` (m) still clips a heavy tail (~p90 was 8.4 m; p99 21 m). Prep currently applies **no** such mask.

### Residual Harvey notes
- HydroShare `README-FEMA Depths Grid.pdf` states **horizontal** 3 m only (no vertical sentence).
- Final.gdb / aligned GeoTIFF still have **no GDAL unit tag**; unit is from the companion overview legend + FEMA convention.
- GDAL default open = `Harvey_Depths_3m_v3` (East/West Final also in GDB).

---

## Pipeline implication (updated 2026-11-12, later)

Both prep scripts now apply `--unit-scale 0.3048` by default (committed), and the aligned rasters were converted:
Harvey by a direct x0.3048 of the aligned raster (checked: same grid/CRS/mask, ratio exactly 0.3048), Sandy by re-running the patched prep
(checked the same way). The first Harvey attempt through `align_hazard_rasters.py --reference <same file>` shifted pixels and was discarded.
Still open: inspect Harvey's deep tail in GIS (29% of valid pixels above 3 m, max 45.3 m), then rerun Harvey stages 2-4 with the PROJ fix.
