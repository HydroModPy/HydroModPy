"""A constant sea level (m), repeated on every day of the project period."""

from datetime import datetime

import pytest

from hydromodpy.data.variables.oceanic.config import OceanicSourceConfig
from hydromodpy.data.variables.oceanic.constant import generate_constant

pytestmark = pytest.mark.fast


def test_one_value_without_a_period():
    records = generate_constant(OceanicSourceConfig(source="constant", value=2.0))

    assert len(records[0].data) == 1


def test_value_is_kept():
    records = generate_constant(OceanicSourceConfig(source="constant", value=3.5))

    assert records[0].data["value"].iloc[0] == 3.5


def test_value_spans_the_project_period():
    period = (datetime(2003, 1, 1), datetime(2003, 1, 10))

    (record,) = generate_constant(
        OceanicSourceConfig(source="constant", value=1.0), project_period=period
    )

    assert len(record.data) == 10
    assert (record.data["value"] == 1.0).all()
    assert (record.date_start, record.date_end) == period
