"""Warn-only Pandera validation helper used by ingestion adapters.

V1 wires the existing :mod:`hydromodpy.data.schemas` contracts into the
ingestion path in *warn-only* mode: a failed validation logs a warning
and the original DataFrame is returned unchanged. V2 will switch to
strict-raise by default; an opt-in escape hatch is already provided via
the ``HMP_PANDERA_STRICT=1`` environment variable.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, TypeVar

import pandera.pandas as pa

from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    import pandas as pd

logger = get_logger(__name__)

STRICT_ENV_VAR = "HMP_PANDERA_STRICT"

T = TypeVar("T", bound="pd.DataFrame")


def _strict_mode_enabled() -> bool:
    """Return ``True`` when ``HMP_PANDERA_STRICT`` opts into raising."""
    return os.environ.get(STRICT_ENV_VAR, "").strip().lower() in {"1", "true", "yes", "on"}


def validate_warn_only(
    df: T,
    schema: pa.DataFrameSchema,
    *,
    schema_name: str,
) -> T:
    """Validate ``df`` against ``schema`` and log a warning on failure.

    Parameters
    ----------
    df:
        The DataFrame produced by an ingestion adapter.
    schema:
        The :class:`pandera.pandas.DataFrameSchema` to apply.
    schema_name:
        Human-readable schema label used in the warning message.

    Returns
    -------
    The validated (and possibly coerced) DataFrame on success, or the
    original ``df`` when validation fails in warn-only mode.

    Raises
    ------
    pandera.errors.SchemaErrors:
        Re-raised when ``HMP_PANDERA_STRICT=1`` is set.
    """
    try:
        return schema.validate(df, lazy=True)
    except pa.errors.SchemaErrors as exc:
        if _strict_mode_enabled():
            raise
        try:
            failures = exc.failure_cases.to_dict(orient="records")
        except Exception:
            failures = [{"message": str(exc)}]
        summary = ", ".join(
            f"{f.get('check') or 'check'}: {f.get('failure_case')}" for f in failures[:3]
        )
        if len(failures) > 3:
            summary += ", ..."
        logger.warning(
            "pandera contract '%s' failed in warn-only mode (%d failure(s)): %s "
            "- returning original DataFrame unchanged, details in the debug log",
            schema_name,
            len(failures),
            summary,
        )
        logger.debug("pandera failures for '%s': %s", schema_name, failures)
        return df
