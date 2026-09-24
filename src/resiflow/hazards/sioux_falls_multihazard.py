"""Sioux Falls multihazard raster discovery (synthetic testbed layout)."""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path

from resiflow.disruption.io import first_existing
from resiflow.hazards.base import HazardEvent

MULTIHAZARD_DIR = "sioux_falls_multihazard"


class SiouxFallsMultihazardSource:
    """Read event rasters from inputs/<multihazard_dir>/<subtype>/event_<key>.tif.

    ``multihazard_dir`` defaults to the synthetic testbed tree but is a class
    attribute specifically so real-data sources (see hazards/real_events.py) can
    subclass this with a different root instead of duplicating the directory
    scan / event-file-map logic.
    """

    hazard_type: str = "generic"
    hazard_subtype: str = "generic"
    intensity_unit: str = "unitless"
    raster_field: str = "intensity"
    multihazard_dir: str = MULTIHAZARD_DIR
    # Set True on earthquake sources that have a companion Sa(1.0s) raster
    # aligned under inputs/<multihazard_dir>/<hazard_subtype>_sa1p0/ (same
    # event_<id>.tif convention) -- HAZUS bridge ground-shaking fragility
    # (Table 7-6) needs Sa(1.0s), not PGA. See hazards/hazus_bridge.py.
    sa1p0_companion: bool = False
    # Set True on earthquake sources that have a companion liquefaction
    # susceptibility raster aligned under
    # inputs/<multihazard_dir>/<hazard_subtype>_liquefaction/ (same
    # event_<id>.tif convention, uint8 HAZUS Table 4-8 codes 0-5, nodata=255
    # -- see scripts/prepare_cusec_liquefaction_susceptibility.py). Real
    # coverage is regional (8 CUSEC states), not national, so this is only
    # True for RealEarthquakeNewMadridScenarioSource -- see
    # hazards/liquefaction.py and docs/HAZARD_TABLE_INTEGRATION_RUNBOOK.md
    # Track A.
    liquefaction_companion: bool = False
    # Set True on winter-storm sources with companion duration_hours/
    # air_temp_F rasters aligned under inputs/<multihazard_dir>/
    # <hazard_subtype>_duration/ and <hazard_subtype>_airtemp/ (same
    # event_<id>.tif convention) -- T32's direct cleanup cost formula
    # (hazards/winter_storm_cost.py) needs both alongside snow depth. See
    # scripts/prepare_winter_storm_duration_temp.py and
    # docs/HAZARD_TABLE_INTEGRATION_RUNBOOK.md Track B.
    winter_storm_cost_companions: bool = False

    def __init__(self, base_path: Path) -> None:
        self.base_path = Path(base_path)
        self._root = self.base_path / "inputs" / self.multihazard_dir / self.hazard_subtype
        self._clip_path = first_existing(
            [
                self.base_path / "study_area" / "fairfax_study_area.gpkg",
                self.base_path / "study_area" / "fairfax_study_area.geojson",
            ]
        )

    @property
    def is_multihazard_mode(self) -> bool:
        return self._root.is_dir()

    @property
    def is_toy_mode(self) -> bool:
        """Compatibility with flood pipeline clip-path selection."""
        return self.is_multihazard_mode

    @property
    def _toy_clip_path(self) -> Path | None:
        return self._clip_path

    def _parse_event_keys(self, event_key: str) -> list[str]:
        if event_key.lower() == "all":
            keys = sorted(p.stem.replace("event_", "") for p in self._root.glob("event_*.tif"))
            return keys or ["1"]
        return [part.strip() for part in str(event_key).split(",") if part.strip()]

    def build_event_file_map(self, event_key: str) -> dict[str, dict[str, list[str]]]:
        event_dict: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        if not self.is_multihazard_mode:
            return event_dict
        for key in self._parse_event_keys(event_key):
            path = self._root / f"event_{key}.tif"
            if not path.exists():
                logging.warning("Missing multihazard raster: %s", path)
                continue
            event_dict[str(key)][self.raster_field].append(str(path))
            if self.sa1p0_companion:
                sa_root = self.base_path / "inputs" / self.multihazard_dir / f"{self.hazard_subtype}_sa1p0"
                sa_path = sa_root / f"event_{key}.tif"
                if sa_path.exists():
                    event_dict[str(key)]["psa1p0"].append(str(sa_path))
                else:
                    logging.warning(
                        "Sa(1.0s) companion raster not found: %s -- HAZUS bridge "
                        "ground-shaking cost stays $0 for event %s (see "
                        "hazards/hazus_bridge.py)",
                        sa_path,
                        key,
                    )
            if self.liquefaction_companion:
                liq_root = self.base_path / "inputs" / self.multihazard_dir / f"{self.hazard_subtype}_liquefaction"
                liq_path = liq_root / f"event_{key}.tif"
                if liq_path.exists():
                    event_dict[str(key)]["liquefaction_class"].append(str(liq_path))
                else:
                    logging.warning(
                        "Liquefaction susceptibility companion raster not found: %s -- "
                        "earthquake road direct cost stays $0 for event %s (see "
                        "hazards/liquefaction.py)",
                        liq_path,
                        key,
                    )
            if self.winter_storm_cost_companions:
                for suffix, field in (("_duration", "duration_hours"), ("_airtemp", "air_temp_F")):
                    companion_root = self.base_path / "inputs" / self.multihazard_dir / f"{self.hazard_subtype}{suffix}"
                    companion_path = companion_root / f"event_{key}.tif"
                    if companion_path.exists():
                        event_dict[str(key)][field].append(str(companion_path))
                    else:
                        logging.warning(
                            "Winter storm %s companion raster not found: %s -- T32 direct cost "
                            "falls back to its documented default for that input, event %s "
                            "(see hazards/winter_storm_cost.py)",
                            field,
                            companion_path,
                            key,
                        )
        return event_dict

    def resolve_event(self, event_id: str) -> HazardEvent:
        event_map = self.build_event_file_map(event_id)
        key = str(event_id).strip()
        if key not in event_map:
            raise KeyError(f"Event {key} not found under {self._root}")
        sources = {field: list(paths) for field, paths in event_map[key].items()}
        clip = str(self._clip_path) if self._clip_path else None
        return HazardEvent(
            hazard_type=self.hazard_type,
            event_id=key,
            intensity_unit=self.intensity_unit,
            sources=sources,
            clip_path=clip,
            flood_types=tuple(sources.keys()),
        )

    def clip_path_for_raster(self, hazard_event: HazardEvent) -> Path | None:
        if hazard_event.clip_path:
            return Path(hazard_event.clip_path)
        return None


class MultihazardFloodSurfaceSource(SiouxFallsMultihazardSource):
    hazard_type = "flood"
    hazard_subtype = "flood_surface"
    intensity_unit = "m_depth"
    raster_field = "surface"


class MultihazardFloodRiverSource(SiouxFallsMultihazardSource):
    hazard_type = "flood"
    hazard_subtype = "flood_river"
    intensity_unit = "m_depth"
    raster_field = "river"


class MultihazardFloodCoastalSource(SiouxFallsMultihazardSource):
    hazard_type = "flood"
    hazard_subtype = "flood_coastal"
    intensity_unit = "m_depth"
    raster_field = "coastal"


class EarthquakeHazardSource(SiouxFallsMultihazardSource):
    hazard_type = "earthquake"
    hazard_subtype = "earthquake"
    intensity_unit = "g_pga"
    raster_field = "pga"


class LandslideHazardSource(SiouxFallsMultihazardSource):
    hazard_type = "landslide"
    hazard_subtype = "landslide"
    intensity_unit = "mm_displacement"
    raster_field = "landslide"


class WinterStormHazardSource(SiouxFallsMultihazardSource):
    hazard_type = "winter_storm"
    hazard_subtype = "winter_storm"
    intensity_unit = "mm_ice"
    raster_field = "winter_storm"


def resolve_multihazard_flood_source(base_path: Path) -> SiouxFallsMultihazardSource | None:
    """Pick flood sub-type source from RESIFLOW_FLOOD_SUBTYPE when multihazard tree exists."""
    import os

    subtype = os.environ.get("RESIFLOW_FLOOD_SUBTYPE", "flood_surface").strip().lower()
    mapping = {
        "surface": MultihazardFloodSurfaceSource,
        "flood_surface": MultihazardFloodSurfaceSource,
        "river": MultihazardFloodRiverSource,
        "flood_river": MultihazardFloodRiverSource,
        "coastal": MultihazardFloodCoastalSource,
        "flood_coastal": MultihazardFloodCoastalSource,
    }
    cls = mapping.get(subtype, MultihazardFloodSurfaceSource)
    source = cls(base_path)
    return source if source.is_multihazard_mode else None
