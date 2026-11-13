"""Unit tables and conversions, one row per (quantity, unit, factor).

The factors below are written out by hand, as they were before the quantities
were merged into one table. A change to any factor must fail here.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.core.units import quantities as q
from hydromodpy.core.units.time import (
    TIME_CANONICAL_UNITS,
    cf_time_axis_seconds,
    convert_seconds_to_unit,
    convert_to_seconds,
    factor_to_seconds,
    normalize_time_unit,
    timedelta_to_seconds,
    to_modflow6_time_units,
    to_modflow_itmuni,
    to_pandas_timedelta_unit,
)

# quantity: (normalize, factor, convert, parse or None, canonical units, SI unit, error label)
API = {
    "length": (
        q.normalize_length_unit,
        q.factor_to_m,
        q.convert_to_m,
        q.parse_to_m,
        q.LENGTH_CANONICAL_UNITS,
        "m",
        "length",
    ),
    "hydraulic_conductivity": (
        q.normalize_m_per_s_unit,
        q.factor_to_m_per_s,
        q.convert_to_m_per_s,
        q.parse_to_m_per_s,
        q.M_PER_S_CANONICAL_UNITS,
        "m/s",
        "hydraulic-conductivity",
    ),
    "hydraulic_conductance": (
        q.normalize_m2_per_s_unit,
        q.factor_to_m2_per_s,
        q.convert_to_m2_per_s,
        q.parse_to_m2_per_s,
        q.M2_PER_S_CANONICAL_UNITS,
        "m2/s",
        "hydraulic-conductance",
    ),
    "volumetric_flow": (
        q.normalize_m3_per_s_unit,
        q.factor_to_m3_per_s,
        q.convert_to_m3_per_s,
        q.parse_to_m3_per_s,
        q.M3_PER_S_CANONICAL_UNITS,
        "m3/s",
        "volumetric-flow",
    ),
    "leakance": (
        q.normalize_per_s_unit,
        q.factor_to_per_s,
        q.convert_to_per_s,
        q.parse_to_per_s,
        q.PER_S_CANONICAL_UNITS,
        "1/s",
        "leakance",
    ),
    "radiation": (
        q.normalize_radiation_unit,
        q.factor_to_w_per_m2,
        q.convert_to_w_per_m2,
        None,
        q.RADIATION_CANONICAL_UNITS,
        "W/m2",
        "radiation",
    ),
    "time": (
        normalize_time_unit,
        factor_to_seconds,
        convert_to_seconds,
        None,
        TIME_CANONICAL_UNITS,
        "seconds",
        "time",
    ),
}

# (quantity, unit, factor to SI), copied from the tables before the merge.
FACTORS = [
    ("length", "m", 1.0),
    ("length", "km", 1000.0),
    ("length", "cm", 1.0e-2),
    ("length", "mm", 1.0e-3),
    ("time", "seconds", 1.0),
    ("time", "minutes", 60.0),
    ("time", "hours", 3600.0),
    ("time", "days", 86400.0),
    ("time", "years", 365.25 * 86400.0),
    ("hydraulic_conductivity", "m/s", 1.0),
    ("hydraulic_conductivity", "m/day", 1.0 / 86400.0),
    ("hydraulic_conductivity", "m/h", 1.0 / 3600.0),
    ("hydraulic_conductivity", "cm/s", 1.0e-2),
    ("hydraulic_conductivity", "cm/day", 1.0e-2 / 86400.0),
    ("hydraulic_conductivity", "cm/h", 1.0e-2 / 3600.0),
    ("hydraulic_conductivity", "mm/s", 1.0e-3),
    ("hydraulic_conductivity", "mm/day", 1.0e-3 / 86400.0),
    ("hydraulic_conductivity", "mm/h", 1.0e-3 / 3600.0),
    ("hydraulic_conductance", "m2/s", 1.0),
    ("hydraulic_conductance", "m2/day", 1.0 / 86400.0),
    ("hydraulic_conductance", "m2/h", 1.0 / 3600.0),
    ("hydraulic_conductance", "cm2/s", 1.0e-4),
    ("hydraulic_conductance", "cm2/day", 1.0e-4 / 86400.0),
    ("hydraulic_conductance", "cm2/h", 1.0e-4 / 3600.0),
    ("hydraulic_conductance", "mm2/s", 1.0e-6),
    ("hydraulic_conductance", "mm2/day", 1.0e-6 / 86400.0),
    ("hydraulic_conductance", "mm2/h", 1.0e-6 / 3600.0),
    ("volumetric_flow", "m3/s", 1.0),
    ("volumetric_flow", "m3/day", 1.0 / 86400.0),
    ("volumetric_flow", "m3/h", 1.0 / 3600.0),
    ("volumetric_flow", "m3/min", 1.0 / 60.0),
    ("volumetric_flow", "l/s", 1.0e-3),
    ("volumetric_flow", "l/day", 1.0e-3 / 86400.0),
    ("volumetric_flow", "l/h", 1.0e-3 / 3600.0),
    ("volumetric_flow", "l/min", 1.0e-3 / 60.0),
    ("leakance", "1/s", 1.0),
    ("leakance", "1/day", 1.0 / 86400.0),
    ("leakance", "1/h", 1.0 / 3600.0),
    ("leakance", "1/min", 1.0 / 60.0),
    ("radiation", "W/m2", 1.0),
    ("radiation", "J/m2/s", 1.0),
    ("radiation", "MJ/m2/day", 1.0e6 / 86400.0),
    ("radiation", "kWh/m2/day", 3.6e6 / 86400.0),
    ("radiation", "J/cm2/day", 1.0e4 / 86400.0),
    ("radiation", "cal/cm2/day", 4.184e4 / 86400.0),
]
IDS = [f"{name}-{unit}" for name, unit, _ in FACTORS]


@pytest.mark.parametrize("quantity", API)
def test_canonical_units_are_the_table_rows(quantity: str) -> None:
    published = {unit for name, unit, _ in FACTORS if name == quantity}
    assert API[quantity][4] == tuple(q.QUANTITIES[quantity][2])
    assert set(API[quantity][4]) == published


ALIASES = [
    ("length", "meter", "m"),
    ("length", "kilometres", "km"),
    ("length", "cm", "cm"),
    ("length", "millimeters", "mm"),
    ("hydraulic_conductivity", "m.s-1", "m/s"),
    ("hydraulic_conductivity", "m/d", "m/day"),
    ("hydraulic_conductivity", "cm/hr", "cm/h"),
    ("hydraulic_conductivity", "mm/day", "mm/day"),
    ("hydraulic_conductance", "m^2/s", "m2/s"),
    ("hydraulic_conductance", "m2/d", "m2/day"),
    ("hydraulic_conductance", "cm2/hr", "cm2/h"),
    ("hydraulic_conductance", "mm2/day", "mm2/day"),
    ("volumetric_flow", "m3/d", "m3/day"),
    ("volumetric_flow", "m3/hr", "m3/h"),
    ("volumetric_flow", "L/s", "l/s"),
    ("volumetric_flow", "l/min", "l/min"),
    ("volumetric_flow", "m3 s-1", "m3/s"),
    ("leakance", "1/d", "1/day"),
    ("leakance", "min-1", "1/min"),
    ("radiation", "W/m²", "W/m2"),
    ("radiation", "Langley/day", "cal/cm2/day"),
    ("time", "s", "seconds"),
    ("time", "day", "days"),
    ("time", "m", "minutes"),
]


@pytest.mark.parametrize(("quantity", "alias", "canonical"), ALIASES)
def test_aliases_resolve_to_the_canonical_unit(quantity: str, alias: str, canonical: str) -> None:
    assert API[quantity][0](alias) == canonical
    assert q.normalize_unit(quantity, alias) == canonical


CONVERSIONS = [
    ("length", 150.0, "cm", 1.5),
    ("length", 2.0, "km", 2000.0),
    ("hydraulic_conductivity", 8.64, "m/day", 1.0e-4),
    ("hydraulic_conductivity", 1.0, "cm/s", 1.0e-2),
    ("hydraulic_conductance", 8.64, "m2/day", 1.0e-4),
    ("hydraulic_conductance", 1.0, "cm2/s", 1.0e-4),
    ("volumetric_flow", 86400.0, "m3/day", 1.0),
    ("volumetric_flow", 1000.0, "l/s", 1.0),
    ("time", 2.0, "day", 172800.0),
]


@pytest.mark.parametrize(("quantity", "value", "unit", "expected"), CONVERSIONS)
def test_convert_to_si(quantity: str, value: float, unit: str, expected: float) -> None:
    assert API[quantity][2](value, unit=unit) == pytest.approx(expected)


PARSES = [
    ("length", "125 cm", "m", "cm", 1.25),
    ("hydraulic_conductivity", "8.64 m/day", "m/s", "m/day", 1.0e-4),
    ("hydraulic_conductance", "8.64 m2/day", "m2/s", "m2/day", 1.0e-4),
    ("volumetric_flow", "3600 m3/h", "m3/s", "m3/h", 1.0),
    ("leakance", "1 1/day", "1/s", "1/day", 1.0 / 86400.0),
]


@pytest.mark.parametrize(("quantity", "text", "default", "unit", "expected"), PARSES)
def test_parse_with_inline_unit(
    quantity: str, text: str, default: str, unit: str, expected: float
) -> None:
    value_si, canonical = API[quantity][3](text, location="test.value", default_unit=default)
    assert canonical == unit
    assert value_si == pytest.approx(expected)


@pytest.mark.parametrize(
    ("quantity", "text"),
    [
        ("length", "10 furlong"),
        ("hydraulic_conductivity", "10 foo/bar"),
        ("hydraulic_conductance", "10 foo/day"),
        ("volumetric_flow", "10 foo/day"),
        ("leakance", "10 m"),
    ],
)
def test_parse_rejects_an_unknown_unit(quantity: str, text: str) -> None:
    with pytest.raises(ValueError, match=f"Unsupported {API[quantity][6]} unit"):
        API[quantity][3](text, location="test.value")


@pytest.mark.parametrize("quantity", [name for name in API if API[name][3] is not None])
def test_parse_default_unit(quantity: str) -> None:
    value_si, canonical = API[quantity][3](5, location="test.value")
    assert (value_si, canonical) == (5.0, API[quantity][5])
    explicit = API[quantity][3](2, location="test.value", explicit_unit=API[quantity][4][1])
    assert explicit == (2.0 * q.factor_to_si(quantity, API[quantity][4][1]), API[quantity][4][1])


@pytest.mark.parametrize("quantity", API)
def test_error_messages(quantity: str) -> None:
    normalize, factor_to, convert, _, units, _, label = API[quantity]
    with pytest.raises(ValueError, match=f"{label.capitalize()} unit cannot be empty."):
        normalize("  ")
    with pytest.raises(ValueError, match=f"Unsupported {label} unit .*Allowed units: {units[0]}"):
        factor_to("furlong")
    with pytest.raises(TypeError, match="lbl must be numeric to convert to "):
        convert(True, unit=units[0], label="lbl")
    with pytest.raises(TypeError, match="depth must be numeric"):
        convert("3", unit=units[0], label="depth")
    with pytest.raises(TypeError, match="value must be numeric to convert to "):
        convert("1", unit=units[0])


def test_unit_text_is_quoted() -> None:
    with pytest.raises(ValueError, match=r"unit 'M'/S'\."):
        q.factor_to_m3_per_s("M'/S")
    with pytest.raises(ValueError, match=r"""time unit "M'/S"\."""):
        factor_to_seconds("M'/S")


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (2, 2000.0),
        (None, None),
        ([1, 2.5], [1000.0, 2500.0]),
        ((1, 2), [1000.0, 2000.0]),
        ({"a": 1, "b": [2, {"c": 3}]}, {"a": 1000.0, "b": [2000.0, {"c": 3000.0}]}),
    ],
    ids=["scalar", "none", "list", "tuple", "nested"],
)
def test_payload_km_to_m(payload, expected) -> None:
    assert q.convert_payload_to_m(payload, unit="km") == expected


def test_payload_cm_s_to_m_s() -> None:
    nested = {"a": 1, "b": [2, (3.0,)]}
    assert q.convert_payload_to_m_per_s(nested, unit="cm/s") == {
        "a": 1.0e-2,
        "b": [2.0e-2, [3.0e-2]],
    }
    scaled = q.convert_payload_to_m_per_s(nested, unit="cm/s", scale=2.0)
    assert scaled == {"a": 2.0e-2, "b": [4.0e-2, [6.0e-2]]}
    assert q.convert_payload_to_m_per_s(None, unit="cm/s", scale=2.0) is None
    np.testing.assert_allclose(
        q.convert_payload_to_m_per_s(np.array([1, 2]), unit="m/day", scale=86400.0), [1.0, 2.0]
    )


def test_array_payload_not_mutated() -> None:
    array = np.array([1.0, 2.0])
    np.testing.assert_allclose(q.convert_payload_to_m(array, unit="cm"), [0.01, 0.02])
    assert array.tolist() == [1.0, 2.0]


@pytest.mark.parametrize("convert_payload", [q.convert_payload_to_m, q.convert_payload_to_m_per_s])
@pytest.mark.parametrize("payload", [True, "12", object(), {"a": True}, [True], np.array(["x"])])
def test_non_numeric_payload_refused(convert_payload, payload) -> None:
    unit = "m" if convert_payload is q.convert_payload_to_m else "m/s"
    with pytest.raises(TypeError, match="must be numeric, a sequence, or a mapping"):
        convert_payload(payload, unit=unit, label="depth")


def test_refused_payload_names_path() -> None:
    with pytest.raises(TypeError, match=r"depth\['a'\]\[1\]"):
        q.convert_payload_to_m({"a": [1, "x"]}, unit="m", label="depth")
    with pytest.raises(TypeError, match=r"L\['a'\]"):
        q.convert_payload_to_m({"a": True}, unit="m", label="L")
    with pytest.raises(TypeError, match=r"L\[0\]"):
        q.convert_payload_to_m_per_s([True], unit="m/s", label="L")


@pytest.mark.parametrize("convert_payload", [q.convert_payload_to_m, q.convert_payload_to_m_per_s])
def test_payload_unit_refused(convert_payload) -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        convert_payload(None, unit="foo")


@pytest.mark.parametrize("unit", ["", "  ", "mile", "ft"])
def test_bad_length_unit(unit: str) -> None:
    with pytest.raises(ValueError, match="cannot be empty|Unsupported length unit"):
        q.normalize_length_unit(unit)


class _CopyScalable:
    """A container with no ``astype`` that a unit factor can still scale."""

    def __init__(self, value):
        self.value = value

    def copy(self):
        return _CopyScalable(self.value)

    def __mul__(self, factor):
        return _CopyScalable(self.value * factor)


class _Unscalable:
    def astype(self, _):
        raise RuntimeError("no")

    def copy(self):
        raise RuntimeError("no")

    def __mul__(self, _):
        raise RuntimeError("no")


def test_container_scaled_on_copy() -> None:
    original = _CopyScalable(3.0)
    assert q.convert_payload_to_m(original, unit="km").value == pytest.approx(3000.0)
    assert original.value == 3.0


def test_unscalable_container() -> None:
    with pytest.raises(TypeError, match="must be numeric"):
        q.convert_payload_to_m(_Unscalable(), unit="km")


@pytest.mark.parametrize(
    ("values", "units", "expected"),
    [
        (2.0, "m", [2.0]),
        ([100.0, 250.0], "cm", [1.0, 2.5]),
        (np.array([1000.0]), "mm", [1.0]),
        ([3.0], "  ", [3.0]),
    ],
)
def test_length_series_in_m(values, units, expected) -> None:
    out = q.coerce_length_series_to_m(values=values, units=units, label="forcing")
    assert out.dtype == float
    np.testing.assert_allclose(np.atleast_1d(out), expected)


def test_length_series_bad_unit() -> None:
    with pytest.raises(ValueError, match="furlong"):
        q.coerce_length_series_to_m(values=[1.0], units="furlong", label="forcing")


@pytest.mark.parametrize(
    ("forcing", "expected"),
    [
        ({"units": "cm"}, "cm"),
        ({}, "fallback"),
        (SimpleNamespace(units="mm"), "mm"),
        (SimpleNamespace(), "fallback"),
    ],
)
def test_forcing_units(forcing, expected) -> None:
    assert q.forcing_units(forcing, fallback="fallback") == expected
