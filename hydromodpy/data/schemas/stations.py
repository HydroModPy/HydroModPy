"""pandera contract for station collections (hydrometry, piezometry, ...)."""

from __future__ import annotations

import pandas as pd
import pandera.pandas as pa

from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.data.schemas.timeseries import _format_failures


StationCollectionSchema = pa.DataFrameSchema(
    columns={
        "station_id": pa.Column(
            str,
            nullable=False,
            unique=True,
            description="Stable station identifier.",
        ),
        "lat": pa.Column(
            float,
            nullable=False,
            checks=pa.Check.in_range(-90.0, 90.0, include_min=True, include_max=True),
            description="Latitude in decimal degrees (WGS-84).",
        ),
        "lon": pa.Column(
            float,
            nullable=False,
            checks=pa.Check.in_range(-180.0, 180.0, include_min=True, include_max=True),
            description="Longitude in decimal degrees (WGS-84).",
        ),
        "z": pa.Column(
            float,
            nullable=True,
            description="Altitude above sea level (metres).",
        ),
        "name": pa.Column(
            str,
            nullable=True,
            description="Human-readable station label.",
        ),
    },
    strict=False,
    coerce=True,
    ordered=False,
)


def validate_stations(df: pd.DataFrame, *, context: str | None = None) -> pd.DataFrame:
    """Validate a station-metadata DataFrame."""
    try:
        return StationCollectionSchema.validate(df, lazy=True)
    except pa.errors.SchemaErrors as exc:
        raise DataContractViolation(
            f"Station collection contract violated{f' ({context})' if context else ''}",
            failures=_format_failures(exc),
        ) from exc
