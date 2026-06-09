"""pandera contract for lake stage-volume-area abacus tables.

The abacus drives ``ModflowUtllaktab`` (3 columns ``stage, volume, sarea``)
plus a ``lake_id`` discriminator so one table can serve several lakes. MF6
extrapolates poorly outside the table, assumes a monotone stage axis, and needs
at least two rows to bracket the stage range, so the contract enforces, per lake:
strictly increasing ``stage``, non-decreasing ``volume`` (``dV/dz >= 0``),
``volume >= 0``, ``sarea >= 0`` and at least two rows. Moving every check into the
contract makes it the single gate: a bad abacus is rejected at import time, before
the Parquet write and the DuckDB register, not late at solver build.
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


def _volume_non_decreasing_per_lake(df: pd.DataFrame) -> bool:
    """True when ``volume`` never decreases with ``stage`` within each lake."""
    for _, group in df.groupby("lake_id", sort=False):
        ordered = group.sort_values("stage")
        if not ordered["volume"].is_monotonic_increasing:
            return False
    return True


def _at_least_two_rows_per_lake(df: pd.DataFrame) -> bool:
    """True when every ``lake_id`` carries at least two stage rows."""
    return bool(df.groupby("lake_id", sort=False).size().ge(2).all())


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
    checks=[
        pa.Check(
            _stage_strictly_increasing_per_lake,
            error="stage must be strictly increasing within each lake_id",
        ),
        pa.Check(
            _volume_non_decreasing_per_lake,
            error="volume must not decrease with stage (dV/dz >= 0) within each lake_id",
        ),
        pa.Check(
            _at_least_two_rows_per_lake,
            error="each lake_id needs at least two rows to bracket the stage range",
        ),
    ],
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
