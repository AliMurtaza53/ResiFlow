"""Flood hazard source: raster discovery for toy and production layouts."""

from __future__ import annotations

import logging
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Iterator

from resiflow.disruption.io import first_existing
from resiflow.hazards.base import HazardEvent, HazardSource

TOY_VARIANT_MAP = {1: "base", 2: "low", 3: "high"}


class FloodHazardSource:
    """Discover flood rasters and resolve per-event HazardEvent records."""

    hazard_type = "flood"

    def __init__(self, base_path: Path) -> None:
        self.base_path = Path(base_path)
        self.raster_path = self.base_path / "hazards" / "completed"
        self._toy_hazard_path = self._resolve_toy_hazard_path()
        self._toy_clip_path = self._resolve_toy_clip_path() if self._toy_hazard_path else None

    def _resolve_toy_hazard_path(self) -> Path | None:
        toy_hazard_dir = self.base_path / "inputs" / "test_17node"
        toy_hazard_50m_dir = self.base_path / "inputs" / "test_141node_50m"
        return first_existing(
            [
                toy_hazard_50m_dir / "va_hazard_class50_141node_base.tif",
                toy_hazard_50m_dir / "va_hazard_class50_141node_low.tif",
                toy_hazard_50m_dir / "va_hazard_class50_141node_high.tif",
                toy_hazard_50m_dir / "va_hazard_class50_141node.tif",
                self.base_path / "inputs" / "test_141node" / "va_hazard_class50_141node_base.tif",
                self.base_path / "inputs" / "test_141node" / "va_hazard_class50_141node_low.tif",
                self.base_path / "inputs" / "test_141node" / "va_hazard_class50_141node_high.tif",
                self.base_path / "inputs" / "test_141node" / "va_hazard_class50_141node.tif",
                toy_hazard_dir / "fairfax_hazard_class50_17node_base.tif",
                toy_hazard_dir / "fairfax_hazard_class50_17node_low.tif",
                toy_hazard_dir / "fairfax_hazard_class50_17node_high.tif",
                toy_hazard_dir / "fairfax_hazard_class50_17node.tif",
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
        try:
            keys = [int(part.strip()) for part in event_key.split(",") if part.strip()]
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "In toy mode, event_key must be one of: 1, 2, 3, all, or a comma-separated list like 2,3"
            ) from exc
        invalid = [key for key in keys if key not in TOY_VARIANT_MAP]
        if invalid:
            raise ValueError(
                f"Invalid toy-mode event_key(s)={invalid}. Use 1=base, 2=low, 3=high, all, or e.g. 2,3."
            )
        return keys

    def _toy_flood_types(self) -> list[str]:
        raw = os.environ.get("NIRD_TOY_FLOOD_TYPES", "flood")
        flood_types = [part.strip().lower() for part in raw.split(",") if part.strip()]
        valid = {"surface", "river", "flood"}
        invalid = [ft for ft in flood_types if ft not in valid]
        if invalid:
            raise ValueError(
                "NIRD_TOY_FLOOD_TYPES may only contain 'surface', 'river', and/or 'flood'. "
                f"Got: {invalid}"
            )
        if not flood_types:
            raise ValueError("NIRD_TOY_FLOOD_TYPES resolved to no flood types.")
        return flood_types

    def _toy_raster_for_variant(self, variant: str) -> Path:
        toy_hazard_dir = self.base_path / "inputs" / "test_17node"
        toy_hazard_50m_dir = self.base_path / "inputs" / "test_141node_50m"
        selected = first_existing(
            [
                toy_hazard_50m_dir / f"va_hazard_class50_141node_{variant}.tif",
                self.base_path / "inputs" / "test_141node" / f"va_hazard_class50_141node_{variant}.tif",
                toy_hazard_dir / f"fairfax_hazard_class50_17node_{variant}.tif",
                self._toy_hazard_path,
            ]
        )
        if selected is None:
            raise FileNotFoundError(f"No toy hazard raster found for variant={variant}")
        return selected

    def _production_event_files(self) -> dict[str, list[str]]:
        event_files: dict[str, list[str]] = {flood_type: [] for flood_type in ("surface", "river")}
        for flood_type in ("surface", "river", "both"):
            folder_path = self.raster_path / flood_type
            if not folder_path.exists():
                continue
            for raster_dir in folder_path.rglob("Raster"):
                for tif_file in raster_dir.rglob("*.tif"):
                    if "RD" not in tif_file.name or "IE" in tif_file.name:
                        continue
                    if flood_type == "both":
                        if "FLSW" in tif_file.name:
                            target_flood_type = "surface"
                        elif "FLRF" in tif_file.name:
                            target_flood_type = "river"
                        else:
                            continue
                    else:
                        target_flood_type = flood_type
                    event_files[target_flood_type].append(str(tif_file))
        return event_files

    @staticmethod
    def _event_id_from_path(event_path: str) -> str:
        path_parts = Path(event_path).parts
        potential_event_folder = path_parts[-3] if len(path_parts) >= 3 else None
        if potential_event_folder not in ("surface", "river", "both", "Raster"):
            return str(potential_event_folder)
        filename = Path(event_path).stem
        numbers = re.findall(r"\d+", filename)
        if numbers:
            for num in numbers:
                if len(num) >= 3:
                    return num
            return numbers[0]
        return filename.split("_")[0]

    def build_event_file_map(self, event_key: str) -> dict[str, dict[str, list[str]]]:
        """Return event_id -> flood_type -> raster paths (legacy pipeline structure)."""
        event_dict: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))

        if self.is_toy_mode:
            flood_types = self._toy_flood_types()
            for event_key_num in self._parse_toy_event_keys(event_key):
                variant = TOY_VARIANT_MAP[event_key_num]
                selected_tif = self._toy_raster_for_variant(variant)
                logging.info(
                    "Toy hazard raster mode enabled: event_key=%s (%s) -> %s",
                    event_key_num,
                    variant,
                    selected_tif,
                )
                event_dict[str(event_key_num)] = {
                    flood_type: [str(selected_tif)] for flood_type in flood_types
                }
            logging.info("Toy flood types enabled: %s", flood_types)
            return event_dict

        for flood_type, list_of_events in self._production_event_files().items():
            for event_path in list_of_events:
                event = self._event_id_from_path(event_path)
                event_dict[event][flood_type].append(event_path)
        return event_dict

    def list_events(self) -> list[str]:
        return sorted(self.build_event_file_map("all").keys())

    def resolve_event(self, event_id: str) -> HazardEvent:
        event_map = self.build_event_file_map(event_id)
        key = str(event_id).strip()
        if key not in event_map:
            raise KeyError(f"Flood event_id={key} not found. Available: {sorted(event_map)}")
        sources = {ft: list(paths) for ft, paths in event_map[key].items()}
        flood_types = tuple(sources.keys())
        clip = str(self._toy_clip_path) if self.is_toy_mode and self._toy_clip_path else None
        return HazardEvent(
            hazard_type="flood",
            event_id=key,
            intensity_unit="m_depth",
            sources=sources,
            clip_path=clip,
            flood_types=flood_types,
        )

    def iter_events_for_run(self, event_key: str) -> Iterator[tuple[str, HazardEvent]]:
        """Yield (flood_key, HazardEvent) pairs matching the Script 2 event filter."""
        event_map = self.build_event_file_map(event_key)
        for flood_key in event_map:
            if not self.is_toy_mode and flood_key != str(event_key).strip():
                continue
            yield flood_key, self.resolve_event(flood_key)

    def clip_path_for_raster(self, flood_path: str, hazard_event: HazardEvent) -> Path | None:
        if self.is_toy_mode:
            return Path(hazard_event.clip_path) if hazard_event.clip_path else None
        clip_path = Path(flood_path.replace("Raster", "Vector").replace(".tif", ".shp"))
        clip_path1 = clip_path.with_name(clip_path.name.replace("_RD_", "_VE_"))
        clip_path2 = clip_path.with_name(clip_path.name.replace("_RD_", "_PR_"))
        if clip_path1.exists():
            return clip_path1
        if clip_path2.exists():
            return clip_path2
        if clip_path.exists():
            return clip_path
        return None
