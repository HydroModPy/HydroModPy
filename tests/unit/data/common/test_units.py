"""Unit conversion of station records: flow, length, temperature, radiation, concentration.

Values convert by a factor, or by an offset for temperature. Radiation goes to
W/m2 through its daily energy (86400 s per day). Units of different families
are refused.
"""

import numpy as np
import pytest

from hydromodpy.data.common.units import convert_array, convert_value

CONVERSIONS = [
    pytest.param(5.0, "m3/s", "m3/s", 5.0, id="identity"),
    pytest.param(1000.0, "L/s", "m3/s", 1.0, id="ls to m3s"),
    pytest.param(1000.0, "l/s", "m3/s", 1.0, id="lowercase ls to m3s"),
    pytest.param(1.0, "m3/s", "L/s", 1000.0, id="m3s to ls"),
    pytest.param(100.0, "cm", "m", 1.0, id="cm to m"),
    pytest.param(12.5, "C", "degC", 12.5, id="bare C alias"),
    pytest.param(2500.0, "ug/l", "mg/L", 2.5, id="ug l alias to mg l"),
    # Temperature is affine.
    pytest.param(273.15, "K", "degC", 0.0, id="kelvin to degc"),
    pytest.param(0.0, "degC", "K", 273.15, id="degc to kelvin"),
    pytest.param(373.15, "K", "degC", 100.0, id="kelvin to degc boiling"),
    pytest.param(32.0, "degF", "degC", 0.0, id="fahrenheit to degc freezing"),
    pytest.param(212.0, "degF", "degC", 100.0, id="fahrenheit to degc boiling"),
    pytest.param(100.0, "degC", "degF", 212.0, id="degc to fahrenheit"),
    pytest.param(273.15, "K", "degF", 32.0, id="kelvin to fahrenheit"),
    # Radiation: 1 MJ/m2/day = 1e6 / 86400 W/m2 = 11.5741 W/m2.
    pytest.param(1.0, "MJ/m2/day", "W/m2", 1.0e6 / 86400.0, id="mj m2 day to w m2"),
    pytest.param(1.0e6 / 86400.0, "W/m2", "MJ/m2/day", 1.0, id="w m2 to mj m2 day"),
    # 1 J/cm2/day = 1e4 / 86400 W/m2 = 0.115741 W/m2.
    pytest.param(1.0, "J/cm2/day", "W/m2", 1.0e4 / 86400.0, id="j cm2 day to w m2"),
    # 1 cal/cm2/day = 4.184e4 / 86400 W/m2 = 0.484259 W/m2.
    pytest.param(1.0, "cal/cm2/day", "W/m2", 4.184e4 / 86400.0, id="cal cm2 day to w m2"),
    pytest.param(1.0, "kWh/m2/day", "W/m2", 3.6e6 / 86400.0, id="kwh m2 day to w m2"),
    pytest.param(10.0, "W/m^2", "W/m2", 10.0, id="caret alias"),
    pytest.param(1.0, "ly/day", "cal/cm2/day", 1.0, id="langley alias"),
    pytest.param(0.5, "fraction", "%", 50.0, id="fraction to percent"),
    pytest.param(75.0, "%", "fraction", 0.75, id="percent to fraction"),
    pytest.param(1.0, "ratio", "%", 100.0, id="ratio to percent"),
    pytest.param(1.0, "g/L", "mg/L", 1000.0, id="g l to mg l"),
    pytest.param(1.0e6, "ng/L", "mg/L", 1.0, id="ng l to mg l"),
    pytest.param(1.0e6, "ug/L", "g/L", 1.0, id="ug l to g l"),
    # CF names: "kg m-2 s-1" is a precipitation mass flux, read as mm/s.
    pytest.param(1.0, "kg m-2 s-1", "mm/s", 1.0, id="cf mass flux to mm s"),
    pytest.param(0.01, "kg/kg", "fraction", 0.01, id="kg kg to fraction"),
    pytest.param(0.5, "kg/kg", "%", 50.0, id="kg kg to percent"),
]


@pytest.mark.parametrize(("value", "from_unit", "to_unit", "expected"), CONVERSIONS)
def test_value_conversions(value, from_unit, to_unit, expected):
    assert convert_value(value, from_unit, to_unit) == pytest.approx(expected)


ARRAYS = [
    pytest.param([1.0, 2.0, 3.0], "cm", "m", [0.01, 0.02, 0.03], id="multiplicative"),
    pytest.param([273.15, 373.15], "K", "degC", [0.0, 100.0], id="affine kelvin"),
]


@pytest.mark.parametrize(("values", "from_unit", "to_unit", "expected"), ARRAYS)
def test_array_conversions(values, from_unit, to_unit, expected):
    result = convert_array(np.array(values), from_unit, to_unit)
    np.testing.assert_allclose(result, expected)


REFUSALS = [
    pytest.param(1.0, "gallons", "m3/s", "Unknown unit", id="unknown unit"),
    pytest.param(1.0, "m", "m3/s", "Incompatible", id="length vs flow"),
    pytest.param(1.0, "degC", "%", "Incompatible", id="temperature vs percent"),
]


@pytest.mark.parametrize(("value", "from_unit", "to_unit", "message"), REFUSALS)
def test_refusals(value, from_unit, to_unit, message):
    with pytest.raises(ValueError, match=message):
        convert_value(value, from_unit, to_unit)
