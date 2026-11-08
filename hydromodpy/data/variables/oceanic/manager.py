"""Oceanic manager: custom files, SHOM tide gauges, or a constant sea level."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from hydromodpy.data.common.source_extent import resolve_source_extent
from hydromodpy.data.managers.base_manager_field import BaseFieldManager
from hydromodpy.data.source.port import FetchRequest, Period


class OceanicManager(BaseFieldManager):
    """Sea level from the user's files, the nearest SHOM gauge, or a constant."""

    VARIABLE_NAME = "oceanic"
    INTERNAL_UNIT = "m"

    def _field_request(
        self,
        source_cfg: Any,
        *,
        out_dir: Path,
        period: tuple[datetime, datetime] | None = None,
    ) -> FetchRequest:
        station_ids = tuple(getattr(source_cfg, "station_ids", None) or ())
        if station_ids:
            extent = None
        else:
            extent = resolve_source_extent(source_cfg, project_extent=self.project_extent)
        if period is None:
            period = self.project_period
        request_period = Period(start=period[0], end=period[1]) if period is not None else None
        return FetchRequest(
            out_dir=out_dir,
            extent=extent,
            station_ids=station_ids,
            period=request_period,
        )
