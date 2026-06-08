"""pandera contract for lake stage-volume-area abacus tables.

The abacus drives ``ModflowUtllaktab`` (3 columns ``stage, volume, sarea``)
plus a ``lake_id`` discriminator so one table can serve several lakes. MF6
extrapolates poorly outside the table and assumes a monotone stage axis, so
the contract enforces: strictly increasing ``stage`` per lake, ``volume >= 0``
and ``sarea >= 0``.
"""

from __future__ import annotations

import pandas as pd
import pandera.pandas as pa

from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.data.schemas.timeseries import _format_failures


def _stage_strictly_increasing_per_lake(df: pd.DataFrame) -> bool:
    """True when ``stage`` is strictly increasing within every ``lake_id``."""
    for _, group in df.groupby("lake_id", sort=False):
        if not group["stage"].is_monotonic_increasing or group["stage"].duplicated().any():
            return False
    return True


AbacusTableSchema = pa.DataFrameSchema(
    columns={
        "lake_id": pa.Column(
            str,
            nullable=False,
            description="Lake identifier (string to match the lake_id tag).",
        ),
        "stage": pa.Column(
            float,
            nullable=False,
            description="Water-surface elevation (m). Strictly increasing per lake.",
        ),
        "volume": pa.Column(
            float,
            nullable=False,
            checks=pa.Check.ge(0.0),
            description="Stored volume at the given stage (m3).",
        ),
        "sarea": pa.Column(
            float,
            nullable=False,
            checks=pa.Check.ge(0.0),
            description="Free water surface area at the given stage (m2).",
        ),
    },
    checks=pa.Check(
        _stage_strictly_increasing_per_lake,
        error="stage must be strictly increasing within each lake_id",
    ),
    strict=False,
    coerce=True,
    ordered=False,
)


def validate_abacus(df: pd.DataFrame, *, context: str | None = None) -> pd.DataFrame:
    """Validate a lake stage-volume-area abacus table."""
    try:
        return AbacusTableSchema.validate(df, lazy=True)
    except pa.errors.SchemaErrors as exc:
        raise DataContractViolation(
            f"Abacus contract violated{f' ({context})' if context else ''}",
            failures=_format_failures(exc),
        ) from exc
