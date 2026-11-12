"""Warn-only pandera validation: a failing frame comes back unchanged, with a warning (strict mode raises)."""

from __future__ import annotations

import logging

import pandas as pd
import pandera.pandas as pa
import pytest

from hydromodpy.data.schemas.timeseries import TimeSeriesSchema
from hydromodpy.data.schemas.validation import STRICT_ENV_VAR, validate_warn_only


def invalid_timeseries() -> pd.DataFrame:
    # A date column that is no date fails the coercion of TimeSeriesSchema.
    return pd.DataFrame({"date": ["not-a-date", "still-not"], "value": [1.0, 2.0]})


def test_failure_returns_the_original_frame(hmp_log_records):
    df = invalid_timeseries()

    out = validate_warn_only(df, TimeSeriesSchema, schema_name="TimeSeriesSchema[test]")

    assert out is df
    assert any(
        "TimeSeriesSchema[test]" in rec.getMessage() and rec.levelno == logging.WARNING
        for rec in hmp_log_records
    )


def test_strict_mode_raises(monkeypatch):
    monkeypatch.setenv(STRICT_ENV_VAR, "1")

    with pytest.raises(pa.errors.SchemaErrors):
        validate_warn_only(
            invalid_timeseries(), TimeSeriesSchema, schema_name="TimeSeriesSchema[strict]"
        )


@pytest.mark.parametrize("falsy", ["", "0", "false", "no", "off"])
def test_falsy_strict_variable_warns(monkeypatch, hmp_log_records, falsy):
    monkeypatch.setenv(STRICT_ENV_VAR, falsy)
    df = invalid_timeseries()

    out = validate_warn_only(df, TimeSeriesSchema, schema_name="TimeSeriesSchema[falsy]")

    assert out is df
    assert any(rec.levelno == logging.WARNING for rec in hmp_log_records)
