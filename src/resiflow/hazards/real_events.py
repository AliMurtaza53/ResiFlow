"""Real hazard rasters (flood/earthquake/landslide/winter_storm), aligned.

Reuses SiouxFallsMultihazardSource's event-file-map/directory-scan logic
(hazards/sioux_falls_multihazard.py) against a different root:
inputs/multihazard_aligned/<hazard_subtype>/event_<id>.tif -- the output
convention align_hazard_rasters.py writes to. See
docs/CONUS_MULTIHAZARD_METHODOLOGY.md for the full data-provenance story.

Holds hazard case studies keyed by their own hazard_subtype, spanning
multiple regions -- e.g. RealFloodHarveyHoustonSource, whose raster covers
Houston/Harris County, TX, alongside VA/CVSZ-region events. The road network
stays CONUS-scale regardless (only the hazard raster is region-sized), so a
new event just needs its own aligned raster under this same directory
convention; nothing about the pipeline is tied to any one region.

Landslide's raw source is a USGS susceptibility model (a score/class), not a
displacement magnitude in mm, which is what fragility/landslide_categorical.py's
thresholds expect. That mismatch is resolved by
scripts/compute_landslide_pgd.py, which combines the aligned susceptibility
raster with the aligned PGA raster via HAZUS's Newmark PGD method
(src/resiflow/hazards/landslide_pgd.py) into a landslide_pgd_mm.tif -- mm
displacement, written to the same event_<id>.tif convention as the other
hazards. RealLandslideSource below reads that derived raster, not the raw
susceptibility score.
"""

from __future__ import annotations

from resiflow.hazards.sioux_falls_multihazard import SiouxFallsMultihazardSource

MULTIHAZARD_ALIGNED_DIR = "multihazard_aligned"


class RealFloodSurfaceSource(SiouxFallsMultihazardSource):
    hazard_type = "flood"
    hazard_subtype = "flood_surface"
    intensity_unit = "m_depth"
    raster_field = "surface"
    multihazard_dir = MULTIHAZARD_ALIGNED_DIR


class RealFloodHarveyHoustonSource(SiouxFallsMultihazardSource):
    """Real Hurricane Harvey flood depths, Houston/Harris County, TX.

    A regional case study -- see docs/CONUS_MULTIHAZARD_METHODOLOGY.md, "Harvey"
    section. Evaluated as a candidate VA flood default and found to have
    zero spatial overlap with the default (VA-origin) reference grid (its extent is lon
    [-97.88,-93.53], lat [27.44,31.52], confirmed via rasterio 2026-08-03);
    wired in instead as its own separate case study, since the road network
    is CONUS-scale regardless of which region's raster is used.

    scripts/prepare_harvey_depths.py produces the aligned input directly
    (streaming reproject from the ~84GB native-3m source, since a full-array
    read the way align_hazard_rasters.py does it for the other hazards isn't
    tractable at this raster's scale).
    """

    hazard_type = "flood"
    hazard_subtype = "flood_harvey_houston"
    intensity_unit = "m_depth"
    raster_field = "surface"
    multihazard_dir = MULTIHAZARD_ALIGNED_DIR


class RealEarthquakeSource(SiouxFallsMultihazardSource):
    """USGS NSHM 2023 (10% in 50yr, ~475yr return period), contour-rasterized.

    A smoothed, probabilistic long-term hazard estimate -- not tied to any
    specific event. Superseded as the default by RealEarthquakeShakeMapSource
    (see docs/CONUS_MULTIHAZARD_METHODOLOGY.md) but kept reachable via
    RESIFLOW_EARTHQUAKE_SUBTYPE=earthquake_nshm for comparison/rollback.
    """

    hazard_type = "earthquake"
    hazard_subtype = "earthquake"
    intensity_unit = "g_pga"
    raster_field = "pga"
    multihazard_dir = MULTIHAZARD_ALIGNED_DIR


class RealEarthquakeShakeMapSource(SiouxFallsMultihazardSource):
    """Real USGS ShakeMap PGA for the 2011 Mineral, VA M5.8 event.

    Default earthquake source as of 2026-08-03. A single-event deterministic
    snapshot (sharp peak near the Mineral epicenter, decaying with distance)
    rather than NSHM's smoothed probabilistic hazard -- matches the "real
    historical CVSZ event" framing landslide's HAZUS PGD calc already uses
    (see docs/CONUS_MULTIHAZARD_METHODOLOGY.md), and covers more of the default (VA-origin) reference grid
    (96.6% vs NSHM's 58.0%, verified locally 2026-08-03) except a sliver west
    of -83.0 degrees longitude the ShakeMap grid doesn't reach.

    scripts/prepare_shakemap_pga.py produces the aligned input: ShakeMap's
    raw _mean grids for PGA/PSA are natural-log(g), not linear g (confirmed
    via USGS's own shakelib.gmice docs), so that conversion has to happen
    upstream of align_hazard_rasters.py's linear --unit-scale.
    """

    hazard_type = "earthquake"
    hazard_subtype = "earthquake_shakemap_mineral"
    intensity_unit = "g_pga"
    raster_field = "pga"
    multihazard_dir = MULTIHAZARD_ALIGNED_DIR
    sa1p0_companion = True


class RealEarthquakeNewMadridScenarioSource(SiouxFallsMultihazardSource):
    """USGS Earthquake Scenarios M7.5 New Madrid central fault (BSSC2014).

    A physically-modeled SCENARIO on a real, well-characterized fault --
    not an instrumentally-recorded historical event (the actual 1811-1812
    New Madrid earthquakes predate ShakeMap-quality instrumentation). Added
    2026-08-20 specifically for a genuinely regional/sub-national-scale
    earthquake footprint: Central/Eastern US crust transmits shaking much
    further than West Coast crust, so even this M7.5 event's damage
    footprint spans 8 states (MO/AR/TN/KY/IL/IN/MS/AL), unlike Mineral VA's
    essentially single-state reach. This is the field-standard reference
    case for this kind of question (used the same way in FEMA/HAZUS
    national risk studies).

    Aligned via --own-bounds (scripts/align_hazard_rasters.py), NOT the
    default reference grid -- using it would silently clip
    this event's multi-state footprint down to just the VA bounding box,
    defeating the entire point of choosing it over Mineral. See
    align_hazard_rasters.grid_from_source_bounds()'s docstring.

    scripts/prepare_shakemap_pga.py produces the aligned input: this
    download's raw grid uses percent-g LINEAR units (confirmed by direct
    inspection: positive values up to ~131, i.e. 1.31g near-fault -- NOT
    natural-log g like the real-time ShakeMap system's Mineral download),
    and a lower-left-corner .hdr convention (XLLCORNER/YLLCORNER/CELLSIZE)
    rather than Mineral's upper-left-corner one (ULXMAP/ULYMAP/XDIM/YDIM) --
    both confirmed by inspecting the actual downloaded files, not assumed
    by analogy with Mineral.
    """

    hazard_type = "earthquake"
    hazard_subtype = "earthquake_new_madrid_m75_scenario"
    intensity_unit = "g_pga"
    raster_field = "pga"
    multihazard_dir = MULTIHAZARD_ALIGNED_DIR
    sa1p0_companion = True


class RealWinterStormSource(SiouxFallsMultihazardSource):
    hazard_type = "winter_storm"
    hazard_subtype = "winter_storm"
    intensity_unit = "mm_ice"
    raster_field = "winter_storm"
    multihazard_dir = MULTIHAZARD_ALIGNED_DIR


class RealWinterStormUriSource(SiouxFallsMultihazardSource):
    """NOAA SNODAS snow depth, 2021-02-17 (Winter Storm Uri peak day).

    Added 2026-08-20 for winter-storm severity/regional diversity alongside
    the existing single day (2016-01-23, Winter Storm Jonas). Aligned at
    FULL CONUS extent via --own-bounds (not clipped to the default reference
    grid, and not clipped to Texas either -- SNODAS's own daily product
    already covers the whole country, so there's no reason to discard any
    of it) -- an initial version clipped to the default reference grid was tried first and rejected:
    clipping to VA specifically would have thrown away Uri's real severity
    center (Texas) for no reason, when the source data already has full
    national coverage for free. Resolution is 1000m (SNODAS's own native
    resolution, ~926m at these latitudes) rather than the default reference grid's
    50m -- full-CONUS at 50m is ~9 billion pixels, both computationally
    intractable (confirmed: timed out past 3 minutes) and fake precision
    for source data that's never finer than ~1km to begin with.
    """

    hazard_type = "winter_storm"
    hazard_subtype = "winter_storm_uri"
    intensity_unit = "mm_ice"
    raster_field = "winter_storm"
    multihazard_dir = MULTIHAZARD_ALIGNED_DIR


class RealWinterStormElliottSource(SiouxFallsMultihazardSource):
    """NOAA SNODAS snow depth, 2022-12-24 (Winter Storm Elliott), full CONUS extent.

    See RealWinterStormUriSource's docstring for the extent/resolution
    reasoning (identical for all three added SNODAS days).
    """

    hazard_type = "winter_storm"
    hazard_subtype = "winter_storm_elliott"
    intensity_unit = "mm_ice"
    raster_field = "winter_storm"
    multihazard_dir = MULTIHAZARD_ALIGNED_DIR


class RealWinterStormSnowmageddonSource(SiouxFallsMultihazardSource):
    """NOAA SNODAS snow depth, 2010-02-06 ("Snowmageddon"), full CONUS extent.

    See RealWinterStormUriSource's docstring for the extent/resolution
    reasoning (identical for all three added SNODAS days).
    """

    hazard_type = "winter_storm"
    hazard_subtype = "winter_storm_snowmageddon"
    intensity_unit = "mm_ice"
    raster_field = "winter_storm"
    multihazard_dir = MULTIHAZARD_ALIGNED_DIR


class RealLandslideSource(SiouxFallsMultihazardSource):
    hazard_type = "landslide"
    hazard_subtype = "landslide"
    intensity_unit = "mm_displacement"
    raster_field = "landslide"
    multihazard_dir = MULTIHAZARD_ALIGNED_DIR


def resolve_real_source(
    base_path,
    hazard_type: str,
    flood_subtype: str | None = None,
    hazard_subtype: str | None = None,
):
    """Return a real-data source if its aligned raster tree exists, else None.

    Callers (disruption/build.py's run_disruption) should try this first and
    fall back to the synthetic testbed source when it returns None -- same
    pattern hazards/sioux_falls_multihazard.py's resolve_multihazard_flood_source
    already uses for flood.

    ``flood_subtype`` (existing param, unchanged) selects among flood's three
    subtypes. ``hazard_subtype`` is the generalization of that same idea to
    other hazard types (currently just earthquake): pass e.g.
    "earthquake_nshm" to opt into the pre-2026-08-03 default instead of the
    new ShakeMap-based one. Omitting it resolves to each hazard_type's
    current default, same as before this param existed.
    """
    mapping = {
        "flood": RealFloodSurfaceSource,
        "flood_surface": RealFloodSurfaceSource,
        "flood_harvey_houston": RealFloodHarveyHoustonSource,
        "earthquake": RealEarthquakeShakeMapSource,
        "earthquake_shakemap_mineral": RealEarthquakeShakeMapSource,
        "earthquake_nshm": RealEarthquakeSource,
        "earthquake_new_madrid_m75_scenario": RealEarthquakeNewMadridScenarioSource,
        "winter_storm": RealWinterStormSource,
        "winter_storm_uri": RealWinterStormUriSource,
        "winter_storm_elliott": RealWinterStormElliottSource,
        "winter_storm_snowmageddon": RealWinterStormSnowmageddonSource,
        "landslide": RealLandslideSource,
    }
    if hazard_type == "flood" and flood_subtype:
        key = flood_subtype
    elif hazard_subtype:
        key = hazard_subtype
    else:
        key = hazard_type
    cls = mapping.get(key)
    if cls is None:
        return None
    source = cls(base_path)
    return source if source.is_multihazard_mode else None
