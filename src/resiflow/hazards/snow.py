"""Snow hazard source: toy synthetic rasters and optional production layouts."""

from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path

from resiflow.disruption.io import first_existing
from resiflow.hazards.base import HazardEvent

TOY_VARIANT_MAP = {1: "base", 2: "low", 3: "high"}


class SnowHazardSource:
    """Discover snow depth rasters for disruption analysis."""

    hazard_type = "snow"

    def __init__(self, base_path: Path) -> None:
        self.base_path = Path(base_path)
        self._toy_hazard_path = self._resolve_toy_hazard_path()
        self._toy_clip_path = self._resolve_toy_clip_path() if self._toy_hazard_path else None

    def _resolve_toy_hazard_path(self) -> Path | None:
        toy_hazard_50m_dir = self.base_path / "inputs" / "test_141node_50m"
        return first_existing(
            [
                toy_hazard_50m_dir / "snow_hazard_141node_base.tif",
                toy_hazard_50m_dir / "snow_hazard_141node_low.tif",
                toy_hazard_50m_dir / "snow_hazard_141node_high.tif",
                toy_hazard_50m_dir / "va_snow_class50_141node_base.tif",
            ]
        )

    def _resolve_toy_clip_path(self) -> Path | None:
        return first_existing(
            [
                self.base_path / "study_area" / "fairfax_study_area.gpkg",
                self.base_path / "study_area" / "fairfax_study_area.geojson",
                self.base_path / "study_area" / "va_study_area.gpkg",
                self.base_path / "study_area" / "va_study_area.geojson",
            ]
        )

    @property
    def is_toy_mode(self) -> bool:
        return self._toy_hazard_path is not None

    def _parse_toy_event_keys(self, event_key: str) -> list[int]:
        if event_key.lower() == "all":
            return sorted(TOY_VARIANT_MAP)
        keys = [int(part.strip()) for part in event_key.split(",") if part.strip()]
        invalid = [key for key in keys if key not in TOY_VARIANT_MAP]
        if invalid:
            raise ValueError(f"Invalid toy snow event_key(s)={invalid}")
        return keys

    def _toy_raster_for_variant(self, variant: str) -> Path:
        toy_hazard_50m_dir = self.base_path / "inputs" / "test_141node_50m"
        selected = first_existing(
            [
                toy_hazard_50m_dir / f"snow_hazard_141node_{variant}.tif",
                toy_hazard_50m_dir / f"va_snow_class50_141node_{variant}.tif",
                self._toy_hazard_path,
            ]
        )
        if selected is None:
            raise FileNotFoundError(f"No toy snow raster found for variant={variant}")
        return selected

    def build_event_file_map(self, event_key: str) -> dict[str, dict[str, list[str]]]:
        event_dict: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        if not self.is_toy_mode:
            snow_root = self.base_path / "hazards" / "snow" / "completed"
            if snow_root.exists():
                for tif in snow_root.rglob("*.tif"):
                    event_id = tif.parent.name if tif.parent.name.isdigit() else tif.stem
                    event_dict[str(event_id)]["snow"].append(str(tif))
            return event_dict

        for event_key_num in self._parse_toy_event_keys(event_key):
            variant = TOY_VARIANT_MAP[event_key_num]
            selected = self._toy_raster_for_variant(variant)
            logging.info("Toy snow raster: event_key=%s (%s) -> %s", event_key_num, variant, selected)
            event_dict[str(event_key_num)] = {"snow": [str(selected)]}
        return event_dict

    def list_events(self) -> list[str]:
        return sorted(self.build_event_file_map("all").keys())

    def resolve_event(self, event_id: str) -> HazardEvent:
        event_map = self.build_event_file_map(event_id)
        key = str(event_id).strip()
        if key not in event_map:
            raise KeyError(f"Snow event_id={key} not found. Available: {sorted(event_map)}")
        sources = {field: list(paths) for field, paths in event_map[key].items()}
        clip = str(self._toy_clip_path) if self.is_toy_mode and self._toy_clip_path else None
        return HazardEvent(
            hazard_type="snow",
            event_id=key,
            intensity_unit="mm_snow",
            sources=sources,
            clip_path=clip,
            flood_types=tuple(sources.keys()),
        )

    def clip_path_for_raster(self, hazard_event: HazardEvent) -> Path | None:
        if self.is_toy_mode and hazard_event.clip_path:
            return Path(hazard_event.clip_path)
        return None
