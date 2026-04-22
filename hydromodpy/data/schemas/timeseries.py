"""pandera contract for tabular time series (date + value)."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pandera.pandas as pa

from hydromodpy.core.exceptions import DataContractViolation

TimeSeriesSchema = pa.DataFrameSchema(
    columns={
        "date": pa.Column(
            pa.DateTime,
            nullable=False,
            description="Observation timestamp (timezone-aware or naive).",
        ),
        "value": pa.Column(
            float,
            nullable=True,
            description="Measured value (NaN encodes missing data).",
        ),
    },
    strict=False,
    coerce=True,
    unique=["date"],
    ordered=False,
)


def validate_timeseries(df: pd.DataFrame, *, context: str | None = None) -> pd.DataFrame:
    """Validate *df* against :data:`TimeSeriesSchema`.

    Raises :class:`DataContractViolation` with a structured message on
    schema mismatch. Returns the coerced DataFrame on success.
    """
    try:
        return TimeSeriesSchema.validate(df, lazy=True)
    except pa.errors.SchemaErrors as exc:
        raise DataContractViolation(
            f"Time series contract violated{f' ({context})' if context else ''}",
            failures=_format_failures(exc),
        ) from exc


def _format_failures(exc: pa.errors.SchemaErrors) -> list[dict[str, Any]]:
    try:
        return exc.failure_cases.to_dict(orient="records")
    except Exception:
        return [{"message": str(exc)}]
