"""Shared base for variable and field data managers.

Private to the ``hydromodpy.data`` package: provides the constructor,
``SourceConfigProtocol``, and the spatial helpers that both manager
families share. ``BaseVariableManager`` and ``BaseFieldManager`` both
inherit from :class:`BaseManagerCommon`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from hydromodpy.data.contracts.timeseries import PointRecord


@runtime_checkable
class SourceConfigProtocol(Protocol):
    """Minimal interface expected from source config objects."""

    source: str
    mask_path: Path | None
    extent: str | None


class BaseManagerCommon(ABC):
    """Shared state and spatial helpers for data managers."""

    VARIABLE_NAME: str = ""

    def __init__(
        self,
        *,
        config: Any,
        catalog: Any,
        project_extent: tuple | None = None,
        project_period: tuple[datetime, datetime] | None = None,
        data_dir: Path | None = None,
    ):
        self.config = config
        self.catalog = catalog
        self.project_extent = project_extent
        self.project_period = project_period
        self.data_dir = Path(data_dir) if data_dir else None

    # ------------------------------------------------------------------
    # Bbox resolution and spatial mask
    # ------------------------------------------------------------------

    def _resolve_bbox(self, source_cfg) -> tuple | None:
        """Resolve bbox from mask geometry or fall back to project extent."""
        if source_cfg.mask_path:
            from hydromodpy.data.common.geo_helpers import geometry_to_bbox

            geom = self._load_mask_geometry(source_cfg.mask_path)
            return geometry_to_bbox(geom)
        if source_cfg.extent and self.project_extent:
            return self.project_extent
        return None

    @abstractmethod
    def _load_mask_geometry(self, mask_path: Path):
        """Load a mask geometry. Variable managers reproject to WGS84."""
        ...

    def _apply_mask(
        self,
        records: list[PointRecord],
        source_cfg,
    ) -> list[PointRecord]:
        """Filter records by spatial mask (WGS84)."""
        if not source_cfg.mask_path:
            return records
        from hydromodpy.data.common.geo_helpers import (
            filter_locations_by_geometry,
            load_mask_geometry_wgs84,
        )

        geom = load_mask_geometry_wgs84(source_cfg.mask_path)
        locs_to_check = [r.location for r in records if r.location is not None]
        inside = filter_locations_by_geometry(locs_to_check, geom)
        valid_ids = {loc.id for loc in inside}
        return [r for r in records if r.location is None or r.station_id in valid_ids]
