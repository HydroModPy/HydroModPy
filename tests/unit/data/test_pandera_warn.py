"""Unit tests for the warn-only pandera validation helper."""

from __future__ import annotations

import logging
from collections.abc import Iterator

import pandas as pd
import pandera.pandas as pa
import pytest

from hydromodpy.core.logging import get_logger
from hydromodpy.data.schemas.timeseries import TimeSeriesSchema
from hydromodpy.data.schemas.validation import STRICT_ENV_VAR, validate_warn_only


def _invalid_timeseries_df() -> pd.DataFrame:
    """Build a DataFrame that violates :data:`TimeSeriesSchema`.

    The ``date`` column is replaced by a non-datetime string column, which
    triggers a coercion failure (lazy mode collects it without raising
    until ``.validate`` returns).
    """
    return pd.DataFrame(
        {
            "date": ["not-a-date", "still-not"],
            "value": [1.0, 2.0],
        }
    )


def test_validate_warn_only_returns_original_df_on_failure(hmp_log_records):
    df = _invalid_timeseries_df()

    out = validate_warn_only(df, TimeSeriesSchema, schema_name="TimeSeriesSchema[test]")

    assert out is df
    assert any(
        "TimeSeriesSchema[test]" in rec.getMessage() and rec.levelno == logging.WARNING
        for rec in hmp_log_records
    )


def test_validate_warn_only_passthrough_on_valid_df(hmp_log_records):
    df = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-01", periods=3, freq="D"),
            "value": [1.0, 2.0, 3.0],
        }
    )
    out = validate_warn_only(df, TimeSeriesSchema, schema_name="TimeSeriesSchema[ok]")

    assert {"date", "value"}.issubset(out.columns)
    assert not any(rec.levelno == logging.WARNING for rec in hmp_log_records)


def test_validate_warn_only_raises_in_strict_mode(monkeypatch):
    monkeypatch.setenv(STRICT_ENV_VAR, "1")
    df = _invalid_timeseries_df()

    with pytest.raises(pa.errors.SchemaErrors):
        validate_warn_only(df, TimeSeriesSchema, schema_name="TimeSeriesSchema[strict]")


@pytest.mark.parametrize("falsy", ["", "0", "false", "no", "off"])
def test_validate_warn_only_warns_when_strict_envvar_is_falsy(monkeypatch, hmp_log_records, falsy):
    monkeypatch.setenv(STRICT_ENV_VAR, falsy)
    df = _invalid_timeseries_df()

    out = validate_warn_only(df, TimeSeriesSchema, schema_name="TimeSeriesSchema[falsy]")

    assert out is df
    assert any(rec.levelno == logging.WARNING for rec in hmp_log_records)
