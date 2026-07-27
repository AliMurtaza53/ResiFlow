"""Real VA hazard rasters (flood/earthquake/landslide/winter_storm), aligned.

Reuses SiouxFallsMultihazardSource's event-file-map/directory-scan logic
(hazards/sioux_falls_multihazard.py) against a different root:
inputs/va_multihazard_aligned/<hazard_subtype>/event_<id>.tif -- the output
convention align_hazard_rasters.py writes to. See
docs/VA_MULTIHAZARD_COMPARISON.md for the full data-provenance story.

Landslide is intentionally NOT included here yet: the real data source is a
USGS susceptibility model (a score/class), not a displacement magnitude in
mm, which is what fragility/landslide_categorical.py's thresholds expect --
a semantic mismatch, not just a unit one. Wire it in once that's resolved
(see the alignment SLURM script's landslide comment).
"""

from __future__ import annotations

from resiflow.hazards.sioux_falls_multihazard import SiouxFallsMultihazardSource

REAL_VA_DIR = "va_multihazard_aligned"


class RealFloodSurfaceSource(SiouxFallsMultihazardSource):
    hazard_type = "flood"
    hazard_subtype = "flood_surface"
    intensity_unit = "m_depth"
    raster_field = "surface"
    multihazard_dir = REAL_VA_DIR


class RealEarthquakeSource(SiouxFallsMultihazardSource):
    hazard_type = "earthquake"
    hazard_subtype = "earthquake"
    intensity_unit = "g_pga"
    raster_field = "pga"
    multihazard_dir = REAL_VA_DIR


class RealWinterStormSource(SiouxFallsMultihazardSource):
    hazard_type = "winter_storm"
    hazard_subtype = "winter_storm"
    intensity_unit = "mm_ice"
    raster_field = "winter_storm"
    multihazard_dir = REAL_VA_DIR


def resolve_real_source(base_path, hazard_type: str, flood_subtype: str | None = None):
    """Return a real-data source if its aligned raster tree exists, else None.

    Callers (disruption/build.py's run_disruption) should try this first and
    fall back to the synthetic testbed source when it returns None -- same
    pattern hazards/sioux_falls_multihazard.py's resolve_multihazard_flood_source
    already uses for flood.
    """
    mapping = {
        "flood": RealFloodSurfaceSource,
        "flood_surface": RealFloodSurfaceSource,
        "earthquake": RealEarthquakeSource,
        "winter_storm": RealWinterStormSource,
    }
    key = flood_subtype if hazard_type == "flood" and flood_subtype else hazard_type
    cls = mapping.get(key)
    if cls is None:
        return None
    source = cls(base_path)
    return source if source.is_multihazard_mode else None
