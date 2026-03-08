"""Unit tests for time-unit helpers centered on seconds."""

from __future__ import annotations

import pytest

from hydromodpy.units.time import (
    convert_seconds_to_unit,
    convert_to_seconds,
    factor_to_seconds,
    normalize_time_unit,
    to_modflow6_time_units,
    to_modflow_itmuni,
    to_pandas_timedelta_unit,
)


def test_normalize_time_unit_accepts_aliases_and_itmuni() -> None:
    assert normalize_time_unit("s") == "seconds"
    assert normalize_time_unit("day") == "days"
    assert normalize_time_unit(1) == "seconds"
    assert normalize_time_unit("4") == "days"


def test_factor_and_conversion_to_seconds() -> None:
    assert factor_to_seconds("hours") == pytest.approx(3600.0)
    assert convert_to_seconds(2.0, unit="day") == pytest.approx(172800.0)
    assert convert_seconds_to_unit(7200.0, unit="hours") == pytest.approx(2.0)


def test_modflow_time_conversion_helpers() -> None:
    assert to_modflow_itmuni("seconds") == 1
    assert to_modflow_itmuni("d") == 4
    assert to_modflow6_time_units(1) == "seconds"
    assert to_pandas_timedelta_unit("hours") == "h"


def test_to_pandas_timedelta_unit_rejects_years() -> None:
    with pytest.raises(ValueError, match="Unsupported pandas Timedelta conversion"):
        _ = to_pandas_timedelta_unit("years")
