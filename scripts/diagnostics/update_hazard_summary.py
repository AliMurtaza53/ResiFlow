"""Refresh the hazard input summary files (native grids, data links, local/Hopper paths, unit status).

Canonical files (tracked): docs/hazard_inputs/hazard_raster_specs_summary.csv and hazard_raster_sources_and_units.csv.
Mirror (gitignored): inputs/multihazard_raw/audit_2026-11-12/ (the audit folder with the aligned rasters and reports).
Idempotent: reads the canonical CSVs, rewrites them, then copies them to the mirror.
All facts below come from files read in the 2026-11-12 audit or from links the project owner supplied; a field says
'NOT FOUND' / 'NOT CHECKED' when it is not known. Nothing here is guessed.
"""
import shutil
from pathlib import Path
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
DOCS = REPO / "docs" / "hazard_inputs"
RAWROOT = Path(r"C:\Users\akothaw\Desktop\ResiFlow\inputs\multihazard_raw")
MIRROR = RAWROOT / "audit_2026-11-12"
HOP_AL = "/scratch/akothaw/multimodal_hazard_data/soge_clusters/inputs/multihazard_aligned"
HOP_RAW = "/scratch/akothaw/multimodal_hazard_data/inputs_raw"
RAW = str(RAWROOT)
PKG = str(MIRROR / "rasters")
NOT = "NOT FOUND"

L = {
 "flood_harvey_houston": dict(
    native="3 m, 150074x140878 px (GDB dataset Harvey_Depths_3m_v3), EPSG:4269", basis="MEASURED (Hopper prep log + GDB metadata)",
    raw_hopper=f"{HOP_RAW}/Harvey_Depths_3m_Final.gdb (+ .gdb.zip, 39 GB)",
    raw_local=f"{RAW}\\Harvey_Depths_3m_Final.gdb (+ .zip); CUAHSI package {RAW}\\Harvey_CUAHSI\\",
    prep="scripts/prepare_harvey_depths.py (patched 2026-11-12: --unit-scale 0.3048)",
    link1="https://www.hydroshare.org/resource/e8768f4cb4d5478a96d2b1cbd00d9e85/",
    link2="https://data.femadata.com/FIMA/NHRAP/Harvey/ (FEMA NHRAP; sibling Harris_Mosaic_dgft.zip = depth grid feet)", links="POPULATED"),
 "flood_sandy_northeast": dict(
    native="~3 m (0.0000318 deg), CT 57837x18143 px, EPSG:4269", basis="MEASURED (raw CT file read on Hopper)",
    raw_hopper=f"{HOP_RAW}/flood/{{ct,nj,nys,ri}}3m0214c.tif", raw_local=f"{RAW}\\flood\\{{ct,nj,nys,ri}}3m0214c.tif",
    prep="scripts/prepare_sandy_depths.py (patched 2026-11-12: --unit-scale 0.3048)",
    link1=("CT: https://www.arcgis.com/home/item.html?id=ddee7f58c532450785a5b3a1c1ceec1d ; NJ: https://www.arcgis.com/home/item.html?id=973babe880a147449b2b837aa04ff11d ; "
           "NY: https://www.arcgis.com/home/item.html?id=88ad91324f234cbca9a13855600b7a1f ; RI: https://www.arcgis.com/home/item.html?id=9363f0a19d214bdeb832eca5e9462b0e"),
    link2="FEMA MOTF items; CT and RI item text read 2026-11-12: 'Vertical: Feet (water depth above ground, NAVD88)', 3-meter horizontal", links="POPULATED (CT, NJ, NY, RI)"),
 "earthquake_shakemap_mineral": dict(
    native="1 arcmin, 661x481 px (~1.46 x 1.84 km), EPSG:4326 (assumed, no .prj in download)", basis="MEASURED (local pga_g.tif)",
    raw_hopper=f"{HOP_RAW}/earthquake/mineral_shakemap/pga_g.tif (converted g; original zip not on Hopper)",
    raw_local=f"{RAW}\\earthquake\\mineral_shakemap\\M5_8_ShakeMap_raster.zip (+ pga_g.tif, sa1p0_g.tif)",
    prep="scripts/prepare_shakemap_pga.py + scripts/align_hazard_rasters.py",
    link1="https://earthquake.usgs.gov/earthquakes/eventpage/se609212/shakemap", link2="https://www.usgs.gov/programs/earthquake-hazards/science/m58-august-23-2011-mineral-virginia", links="POPULATED"),
 "earthquake_new_madrid_m75_scenario": dict(
    native="780x637 px at 0.019262 deg (~1.73 x 2.13 km), EPSG:4326, lon -96.52..-81.50, lat 30.10..42.37; identical grid to USGS bssc2014newmadrid_32_m7p5_se",
    basis="MEASURED (downloaded the USGS raster.zip for event 32 and compared with the repo layer: difference exactly 0 for PGA and SA(1.0s))",
    raw_hopper="NOT ON HOPPER",
    raw_local=(RAW + "\\earthquake\\new_madrid_scenario\\bssc2014\\bssc2014newmadrid_{31_m7p3,32_m7p5,33_m7p5}_se\\raster.zip (+ raster_unzipped\\, .fit grids in percent g); "
               "FEMA M7.7 scenario nm19fema_m7p7_mt_se: " + RAW + "\\earthquake\\new_madrid_scenario\\raster.zip, shape.zip; converted pga_g.tif, sa1p0_g.tif in the same folder"),
    prep="scripts/prepare_shakemap_pga.py (percent g / 100) + scripts/align_hazard_rasters.py --own-bounds",
    link1="https://earthquake.usgs.gov/scenarios/eventpage/bssc2014newmadrid_32_m7p5_se/executive (the scenario this layer is)",
    link2=("Alternates: _31_ M7.3 https://earthquake.usgs.gov/scenarios/eventpage/bssc2014newmadrid_31_m7p3_se/executive ; _33_ M7.5 https://earthquake.usgs.gov/scenarios/eventpage/bssc2014newmadrid_33_m7p5_se/executive ; "
           "FEMA M7.7 southern fault https://earthquake.usgs.gov/scenarios/eventpage/nm19fema_m7p7_mt_se/shakemap/intensity . Data service: https://earthquake.usgs.gov/fdsnws/scenario/1/query?eventid=<id>&format=geojson . Catalog https://earthquake.usgs.gov/scenarios/catalog/bssc2014/"),
    links="POPULATED"),
 "earthquake_cascadia_m9_scenario": dict(
    native="552x794 px at 0.01991 deg (~1.58 x 2.20 km), EPSG:4326, lon -127.27..-116.30, lat 36.77..52.56 (matches the HDF's own grid)",
    basis="MEASURED (HDF metadata read on Hopper, prep log, local pga_g.tif)",
    raw_hopper=f"{HOP_RAW}/Cascadia9_shake_result.hdf (+ earthquake/cascadia_m9_scenario/pga_g.tif, sa1p0_g.tif)",
    raw_local=RAW + "\\earthquake\\cascadia_m9_scenario\\ (Cascadia9_shake_result.hdf, raster.zip, shape.zip, converted pga_g.tif, sa1p0_g.tif)",
    prep="scripts/prepare_cascadia_pga.py + scripts/align_hazard_rasters.py --own-bounds",
    link1="https://earthquake.usgs.gov/scenarios/eventpage/cszm9ensemble_se/shakemap/intensity (supplied by project owner)",
    link2="HDF metadata: event_id CSZM9_median, eventsource cszm9, eventsourcecode ensemble_se (matches the link). USGS also publishes 2nd/16th/84th/98th percentile maps for this scenario: https://earthquake.usgs.gov/fdsnws/scenario/1/query?eventid=cszm9ensemble_se&format=geojson", links="POPULATED (matched to the HDF)"),
 "landslide": dict(
    native="USGS n10 susceptibility ~88 m (0.00102 deg, 63722x37866 px, EPSG:4326); displacement driven by the ~1.5 km PGA grid", basis="MEASURED (n10 file read on Hopper)",
    raw_hopper=f"{HOP_RAW}/landslide/n10_susc/n10_conus.tif", raw_local=f"{RAW}\\landslide\\n10_susc.zip",
    prep="scripts/compute_landslide_pgd.py (HAZUS Newmark, M5.8 Mineral)",
    link1="https://www.sciencebase.gov/catalog/item/65ccea5bd34ef4b119cb3bac (USGS Slope-Relief Threshold Landslide Susceptibility Models, CONUS)",
    link2="S3 mirror used: https://prod-is-usgs-sb-prod-publish.s3.amazonaws.com/65ccea5bd34ef4b119cb3bac/n10_susc.zip ; method: https://www.fema.gov/sites/default/files/documents/fema_hazus-earthquake-model-technical-manual-6-1.pdf", links="POPULATED"),
 "landslide_cascadia_m9": dict(
    native="same inputs as above: ~88 m susceptibility, ~1.6 x 2.2 km PGA", basis="MEASURED",
    raw_hopper=f"{HOP_RAW}/landslide/n10_susc/n10_conus.tif + Cascadia9_shake_result.hdf", raw_local=f"{RAW}\\landslide\\n10_susc.zip + earthquake\\cascadia_m9_scenario\\Cascadia9_shake_result.hdf",
    prep="scripts/compute_landslide_pgd.py --magnitude 9.0 (job submit_cascadia_landslide_prep_dumpcode.slurm)",
    link1="https://www.sciencebase.gov/catalog/item/65ccea5bd34ef4b119cb3bac", link2="https://earthquake.usgs.gov/scenarios/eventpage/cszm9ensemble_se/shakemap/intensity (Cascadia shaking input)", links="POPULATED"),
 "winter_storm": dict(
    native="~1 km (SNODAS native ~926 m, 0.0083 deg), EPSG:4326 per docs", basis="DOCS (raw SNODAS files present locally but not read in this audit)",
    raw_hopper="NOT CHECKED (raw SNODAS not in Hopper inputs_raw)",
    raw_local=f"{RAW}\\winter_storm\\{{uri_20210217,elliott_20221224,snowmageddon_20100206,snodas_jan2016}}\\",
    prep="scripts/align_hazard_rasters.py --own-bounds --resolution 1000 (unit scale not confirmed for these three events)",
    link1="https://nsidc.org/data/g02158", link2="https://noaadata.apps.nsidc.org/NOAA/G02158/masked/ ; user guide https://nsidc.org/sites/default/files/g02158-v001-userguide_2_1.pdf", links="POPULATED (product pages; per-event daily files not recorded)"),
}


def key(f):
    f = f.replace("_sa1p0", "").replace("_event_1_metres.tif", "").replace("_event_1.tif", "")
    return "winter_storm" if f.startswith("winter_storm") else f


S = DOCS / "hazard_raster_specs_summary.csv"
d = pd.read_csv(S, encoding="utf-8")
for c in ["native_grid_and_res", "native_basis", "link_primary_data", "link_docs_or_metadata", "links_status", "raw_on_hopper", "raw_local",
          "aligned_on_hopper", "aligned_local_copy", "prep_script", "update_note"]:
    if c not in d.columns:
        d[c] = ""
    d[c] = d[c].astype(object)
for i, r in d.iterrows():
    layer = r["file"].replace("_event_1_metres.tif", "").replace("_event_1.tif", "")
    m = L[key(r["file"])]
    for c, v in (("native_grid_and_res", m["native"]), ("native_basis", m["basis"]), ("link_primary_data", m["link1"]), ("link_docs_or_metadata", m["link2"]),
                 ("links_status", m["links"]), ("raw_on_hopper", m["raw_hopper"]), ("raw_local", m["raw_local"]), ("prep_script", m["prep"])):
        d.at[i, c] = v
    d.at[i, "aligned_on_hopper"] = f"{HOP_AL}/{layer}/event_1.tif"
    d.at[i, "aligned_local_copy"] = f"{PKG}\\{layer}_event_1.tif"

fl = {"flood_harvey_houston": dict(min=0.0026, p50=1.4491, p90=8.4171, p99=21.3194, max=45.3065, was=(4.75, 148.6)),
      "flood_sandy_northeast": dict(min=0.0000, p50=1.7158, p90=2.9366, p99=4.1604, max=5.5192, was=(5.63, 18.11))}
for k, v in fl.items():
    i = d.index[d["file"].str.startswith(k)][0]
    d.at[i, "file"] = f"{k}_event_1_metres.tif"
    for c in ["min", "p50", "p90", "p99", "max"]:
        d.at[i, c] = v[c]
    d.at[i, "intensity_unit_in_code"] = "m_depth (file converted from feet x 0.3048 on 2026-11-12; checked: ratio exactly 0.3048, masks identical)"
    d.at[i, "unit_status"] = "FEET_CONFIRMED_CONVERTED_TO_METRES"
    d.at[i, "gaps"] = "NO_UNIT_TAG_IN_FILE; ROW_STATS_NOW_IN_METRES; " + ("DEEP_TAIL_TO_INSPECT_IN_GIS (29% of valid px > 3 m, max 45 m)" if k == "flood_harvey_houston" else "NONE_OPEN (CT, NJ, NY, RI items all state feet)")
    d.at[i, "update_note"] = f"Previous feet values: p50 {v['was'][0]}, max {v['was'][1]}. Feet file kept as *_feet_unconverted.tif."
    d.at[i, "aligned_local_copy"] = f"{PKG}\\{k}_event_1_metres.tif (feet version: {PKG}\\{k}_event_1_feet_unconverted.tif)"

for i in d.index[d["file"].str.contains("new_madrid")]:
    d.at[i, "unit_status"] = "DOCUMENTED_AND_VERIFIED_PERCENT_G"
    d.at[i, "unit_hypothesis"] = ("Verified 2026-11-12: repo layer equals the USGS bssc2014newmadrid_32_m7p5_se raster pixel for pixel (diff 0.0); raw values are percent g (max 130.89 -> 1.309 g). "
                                  "Scenario facts (USGS service): M7.5, hypocenter -89.62/36.45, depth 15.6 km, max MMI 8.77, median ground motions")
    d.at[i, "gaps"] = "NO_UNIT_TAG_IN_FILE; ALIGNED_50M_IS_AN_UPSAMPLE_OF_A_~2KM_GRID; SCENARIO_CHOICE_OPEN (3 BSSC2014 variants + FEMA M7.7)"
    d.at[i, "update_note"] = ("BSSC2014 variants (all 'New Madrid central fault', median ground motions): _31_ M7.3 hypocenter -89.33/36.93 depth 19.1 km MMI 8.66 PGA max 1.222 g; "
                              "_32_ M7.5 -89.62/36.45 depth 15.6 km MMI 8.77 PGA max 1.309 g (in use); _33_ M7.5 -90.06/35.83 depth 19.4 km MMI 8.62 PGA max 1.192 g. "
                              "FEMA nm19fema_m7p7_mt_se: M7.7 southern fault, hypocenter -90.44/35.54, depth 15 km, ln(g), PGA max 1.42 g, extent lon -95..-85 lat 31..40")
for i in d.index[d["file"].str.contains("cascadia_m9_scenario")]:
    d.at[i, "gaps"] = "NO_UNIT_TAG_IN_FILE; ALIGNED_50M_IS_AN_UPSAMPLE_OF_A_~2KM_GRID; PRODUCT_IS_THE_MEDIAN_MAP_(CSZM9_median)"
    d.at[i, "update_note"] = ("Median map in use (CSZM9_median, max PGA 1.387 g). USGS also publishes 2nd/16th/84th/98th percentile maps (max PGA 0.54/0.73/2.43/3.02 g) and a ground-failure-scenario product; "
                              "median is the standard deterministic basis, percentile maps are the sensitivity band")
for i in d.index[d["file"].str.contains("mineral")]:
    d.at[i, "update_note"] = "Aligned 50 m is an interpolation of a ~1.5-1.8 km native grid"
for i in d.index[d["file"].str.startswith("winter_storm")]:
    d.at[i, "gaps"] = "NO_UNIT_TAG_IN_FILE; SINGLE_DAILY_SNAPSHOT (physical snow depth incl. seasonal pack, by design: hazard kept separate from operational response)"
    d.at[i, "update_note"] = ("SNODAS product 1036 per NSIDC guide: big-endian int16, 'Meters / 1000' so stored integers are mm (matches code); -9999 and 32767 masked; georeferenced from each file's own header "
                              "(handles the 2013 origin shift). Prep: scripts/prepare_snodas_depth.py. Raw files: winter_storm/<event>/snodas_3day and depth_mm.tif")
# ---- decisions and sensitivity options (owner decisions 2026-11-12)
for c in ["decision", "sensitivity_run_option"]:
    if c not in d.columns:
        d[c] = ""
    d[c] = d[c].astype(object)
NM_SENS = ("OPTIONAL SENSITIVITY: rerun scenario 403 with bssc2014newmadrid_33_m7p5_se (M7.5, hypocenter 35.83N near Memphis, PGA max 1.192 g) and/or _31_ (M7.3, 36.93N, 1.222 g); "
           "FEMA nm19fema_m7p7_mt_se (M7.7 southern fault, ln g, PGA max 1.42 g, has a PAGER loss estimate) as a larger-event case. Raster packs are already local under new_madrid_scenario/bssc2014 "
           "(percent g, convert with prepare_shakemap_pga.py then align_hazard_rasters.py --own-bounds); results depend on hypocenter")
CS_SENS = ("OPTIONAL SENSITIVITY: rerun scenario 404 with the 16th and 84th percentile maps (USGS cszm9ensemble_se products 16perct_se and _84perct_se; max PGA 0.73 g and 2.43 g vs median 1.39 g), "
           "optionally 2nd and 98th (0.54 g and 3.02 g) as bounds. Not yet downloaded (fetch each product's raster.zip via the USGS scenario service). "
           "Percentile maps are cell-by-cell, not one consistent event; damage is convex in shaking, so the median can understate expected damage")
for i in d.index:
    f = d.at[i, "file"]
    if "new_madrid" in f:
        d.at[i, "decision"] = "KEEP bssc2014newmadrid_32_m7p5_se (owner decision 2026-11-12)"
        d.at[i, "sensitivity_run_option"] = NM_SENS
    elif "cascadia_m9_scenario" in f:
        d.at[i, "decision"] = "KEEP median map CSZM9_median (owner decision 2026-11-12)"
        d.at[i, "sensitivity_run_option"] = CS_SENS
    elif f.startswith("landslide_cascadia"):
        d.at[i, "decision"] = "Follows the Cascadia median PGA"
        d.at[i, "sensitivity_run_option"] = "Recompute displacement from the 16th/84th percentile PGA if the Cascadia sensitivity is run (compute_landslide_pgd.py --magnitude 9.0)"
    elif f.startswith("winter_storm"):
        d.at[i, "decision"] = ("KEEP the physical SNODAS snow depth unmodified (owner decision 2026-11-12): no baseline subtraction, no mountain masking. "
                               "Direct costs and delays from snowpack are modelled separately from the hazard: clearance priority T33, day-of-reopening by road rank x damage level x region T34, "
                               "post-reopening speed recovery T35, cost function T32. The hazard is not adjusted to stand in for operational response")
        d.at[i, "sensitivity_run_option"] = ("NONE PLANNED. Rejected: a baseline-subtracted storm-increase raster, because it would change the physical hazard that the response tables are keyed on. "
                                             "Verification item (not a change): confirm the T34 region classification covers high-snow mountain regions")
d.to_csv(S, index=False, encoding="utf-8")

# sources_and_units.csv: keep in step for the rows whose status changed
S2 = DOCS / "hazard_raster_sources_and_units.csv"
u = pd.read_csv(S2, encoding="utf-8")
for i, r in u.iterrows():
    n = r["raster"]
    if n.startswith("flood_harvey"):
        u.at[i, "status"] = "FEET CONFIRMED; CONVERTED TO METRES 2026-11-12 (deep tail still to inspect)"
        u.at[i, "native_unit_per_records"] = "feet (FEMA Harvey 3m depth grid legend 'ft'; sibling NHRAP files 'dgft')"
    elif n.startswith("flood_sandy"):
        u.at[i, "status"] = "FEET CONFIRMED (CT, NJ, NY, RI items); CONVERTED TO METRES 2026-11-12"
        u.at[i, "native_unit_per_records"] = "feet ('Vertical: Feet (water depth above ground, NAVD88)')"
    elif n.startswith("earthquake_new_madrid"):
        u.at[i, "status"] = "VERIFIED: layer = USGS bssc2014newmadrid_32_m7p5_se (diff 0); percent g confirmed"
        u.at[i, "source_as_recorded"] = "USGS BSSC2014 scenario bssc2014newmadrid_32_m7p5_se, https://earthquake.usgs.gov/scenarios/eventpage/bssc2014newmadrid_32_m7p5_se/executive"
    elif n.startswith("earthquake_cascadia"):
        u.at[i, "source_as_recorded"] = "USGS ShakeMap scenario cszm9ensemble_se (HDF event CSZM9_median), https://earthquake.usgs.gov/scenarios/eventpage/cszm9ensemble_se/shakemap/intensity"
u.to_csv(S2, index=False, encoding="utf-8")

if MIRROR.exists():
    for f in (S, S2):
        shutil.copy(f, MIRROR / f.name)
print("summary rows", len(d), "cols", len(d.columns), "| mirrored to", MIRROR if MIRROR.exists() else "(mirror missing)")
