"""Custom data loader for soil_moisture (CSV directory, NetCDF, or GeoTIFF)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from hydromodpy.data.common.custom_point_loader import load_custom_multiformat


VARIABLE_NAME = "soil_moisture"


def load_custom(
    config,
    *,
    project_period: tuple[datetime, datetime] | None = None,
    internal_unit: str = "%",
) -> list:
    return load_custom_multiformat(
        Path(config.path),
        variable_name=VARIABLE_NAME,
        internal_unit=internal_unit,
        project_period=project_period,
        col_id=config.col_id, col_x=config.col_x,
        col_y=config.col_y, col_crs=config.col_crs,
        default_crs=config.default_crs,
        col_datetime=config.col_datetime,
        col_value=config.col_value,
        station_ids=config.station_ids,
        default_unit="%",
        source_unit=config.source_unit,
    )
