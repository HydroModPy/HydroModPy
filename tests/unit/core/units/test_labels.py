"""Axis labels with their unit, and lengths (m) shown in a requested unit."""

from __future__ import annotations

import pytest

from hydromodpy.core.units.labels import axis_label, format_length_from_m, station_label
from hydromodpy.core.units.quantities import convert_to_m


def test_axis_label():
    assert axis_label("head") == "Hydraulic head (m)"
    assert axis_label("head", "ft") == "Hydraulic head (ft)"
    assert axis_label("custom") == "custom"


# (length in m, unit shown, decimals, text)
DISPLAYED = [
    pytest.param(1500.0, "km", 3, "1.500 km", id="km"),
    pytest.param(0.25, "cm", 1, "25.0 cm", id="cm"),
    pytest.param("2", "mm", 0, "2000 mm", id="a string is read as a number"),
    pytest.param(1.0, "m", 2, "1.00 m", id="m"),
]


@pytest.mark.parametrize(("meters", "unit", "precision", "text"), DISPLAYED)
def test_format_length_from_m(meters, unit, precision, text):
    assert format_length_from_m(meters, unit=unit, precision=precision) == text


def test_a_non_numeric_length_is_refused():
    with pytest.raises(ValueError, match="value_m must be numeric"):
        format_length_from_m("deep")


@pytest.mark.parametrize("unit", ["m", "km", "cm", "mm"])
def test_a_displayed_length_converts_back(unit):
    value, shown_unit = format_length_from_m(123.456, unit=unit, precision=9).split()
    assert convert_to_m(float(value), unit=shown_unit) == pytest.approx(123.456)


def test_a_gauge_keeps_its_own_id():
    assert station_label("J7000610") == "J7000610"
