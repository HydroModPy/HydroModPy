"""Time units (canonical unit seconds), MODFLOW ITMUNI codes and CF time axes."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pytest

from hydromodpy.core.units.time import (
    cf_time_axis_seconds,
    convert_seconds_to_unit,
    normalize_time_unit,
    timedelta_to_seconds,
    to_modflow6_time_units,
    to_modflow_itmuni,
    to_pandas_timedelta_unit,
)

# MODFLOW ITMUNI codes are 1 seconds, 2 minutes, 3 hours, 4 days, 5 years.
NORMALIZED = [
    pytest.param(1, "seconds", id="code 1"),
    pytest.param("4", "days", id="code as text"),
    pytest.param(2.0, "minutes", id="code as float"),
    pytest.param(" 5 ", "years", id="code with spaces"),
]


@pytest.mark.parametrize(("given", "unit"), NORMALIZED)
def test_normalize_time_unit(given, unit):
    assert normalize_time_unit(given) == unit


def test_time_units_and_modflow_codes():
    assert convert_seconds_to_unit(7200.0, unit="hours") == pytest.approx(2.0)
    assert to_modflow_itmuni("seconds") == 1
    assert to_modflow_itmuni("d") == 4
    assert to_modflow6_time_units(1) == "seconds"
    assert to_pandas_timedelta_unit("hours") == "h"


def test_timedelta_and_cf_axis():
    assert timedelta_to_seconds(dt.timedelta(minutes=2)) == 120.0
    np.testing.assert_array_equal(cf_time_axis_seconds([0.4, 86400.0], None), [0, 86400])
    anchored = cf_time_axis_seconds([0, 60], dt.datetime(1970, 1, 2))
    np.testing.assert_array_equal(anchored, [86400, 86460])


REFUSED = [
    pytest.param(6, "Unsupported ITMUNI code 6. Expected 1..5.", id="code out of range"),
    pytest.param(True, "Unsupported time unit True", id="boolean"),
    pytest.param(2.5, "Unsupported time unit 2.5", id="float that is no code"),
    pytest.param(None, "Unsupported time unit None", id="none"),
]


@pytest.mark.parametrize(("given", "message"), REFUSED)
def test_normalize_time_unit_refusals(given, message):
    with pytest.raises(ValueError, match=message):
        normalize_time_unit(given)


def test_other_refusals():
    with pytest.raises(TypeError, match="value_seconds must be numeric to convert from seconds."):
        convert_seconds_to_unit(True, unit="day")
    with pytest.raises(ValueError, match="Unsupported pandas Timedelta conversion"):
        to_pandas_timedelta_unit("years")
    with pytest.raises(TypeError, match="delta must provide a total_seconds"):
        timedelta_to_seconds(3, label="delta")
