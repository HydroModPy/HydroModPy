"""pandera contract for zone-based lithology tables."""

from __future__ import annotations

import pandas as pd
import pandera.pandas as pa

from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.data.schemas.timeseries import _format_failures

LithologyTableSchema = pa.DataFrameSchema(
    columns={
        "zone_id": pa.Column(
            str,
            nullable=False,
            unique=True,
            description="Lithology zone identifier (string to match the cell tag).",
        ),
        "conductivity": pa.Column(
            float,
            nullable=False,
            checks=pa.Check.gt(0.0),
            description="Hydraulic conductivity (m/s).",
        ),
        "porosity": pa.Column(
            float,
            nullable=True,
            checks=pa.Check.in_range(0.0, 1.0, include_min=True, include_max=True),
            description="Effective porosity (dimensionless, 0-1).",
        ),
        "layer_thickness": pa.Column(
            float,
            nullable=True,
            checks=pa.Check.gt(0.0),
            description="Layer thickness (m).",
        ),
    },
    strict=False,
    coerce=True,
    ordered=False,
)


def validate_lithology(df: pd.DataFrame, *, context: str | None = None) -> pd.DataFrame:
    """Validate a lithology zone table."""
    try:
        return LithologyTableSchema.validate(df, lazy=True)
    except pa.errors.SchemaErrors as exc:
        raise DataContractViolation(
            f"Lithology contract violated{f' ({context})' if context else ''}",
            failures=_format_failures(exc),
        ) from exc
