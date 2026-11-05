"""Unit tests for strict length conversions to meters."""

from __future__ import annotations

import pytest

from hydromodpy.core.units.length import (
    convert_to_m,
    factor_to_m,
    normalize_length_unit,
    parse_to_m,
)


def test_normalize_length_unit_accepts_aliases() -> None:
    assert normalize_length_unit("meter") == "m"
    assert normalize_length_unit("kilometres") == "km"
    assert normalize_length_unit("cm") == "cm"
    assert normalize_length_unit("millimeters") == "mm"


def test_factor_to_m_for_common_units() -> None:
    assert factor_to_m("m") == pytest.approx(1.0)
    assert factor_to_m("km") == pytest.approx(1000.0)
    assert factor_to_m("cm") == pytest.approx(1.0e-2)
    assert factor_to_m("mm") == pytest.approx(1.0e-3)


def test_convert_to_m() -> None:
    assert convert_to_m(150.0, unit="cm") == pytest.approx(1.5)
    assert convert_to_m(2.0, unit="km") == pytest.approx(2000.0)


def test_parse_to_m_with_inline_unit() -> None:
    value_si, unit = parse_to_m(
        "125 cm",
        location="test.value",
        default_unit="m",
    )
    assert unit == "cm"
    assert value_si == pytest.approx(1.25)


def test_parse_to_m_rejects_unknown_unit() -> None:
    with pytest.raises(ValueError, match="Unsupported length unit"):
        _ = parse_to_m("10 furlong", location="test.value")


# ------------------------------------------------------------------ payloads

import numpy as np  # noqa: E402

from hydromodpy.core.units.length import convert_payload_to_m, format_length_from_m  # noqa: E402


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
def test_a_payload_in_km_is_converted_to_m_whatever_its_nesting(payload, expected):
    assert convert_payload_to_m(payload, unit="km") == expected


def test_an_array_payload_is_scaled_without_touching_the_input():
    array = np.array([1.0, 2.0])
    out = convert_payload_to_m(array, unit="cm")
    np.testing.assert_allclose(out, [0.01, 0.02])
    assert array.tolist() == [1.0, 2.0]


@pytest.mark.parametrize("payload", [True, "12", object(), {"a": True}])
def test_a_payload_that_is_not_numeric_is_refused_and_names_where(payload):
    with pytest.raises(TypeError, match="must be numeric"):
        convert_payload_to_m(payload, unit="m", label="depth")


def test_a_nested_refusal_names_the_path_to_the_bad_value():
    with pytest.raises(TypeError, match=r"depth\['a'\]\[1\]"):
        convert_payload_to_m({"a": [1, "x"]}, unit="m", label="depth")


def test_converting_a_bool_or_a_string_to_metres_is_refused():
    for bad in (True, "3"):
        with pytest.raises(TypeError, match="depth must be numeric"):
            convert_to_m(bad, unit="m", label="depth")


@pytest.mark.parametrize("unit", ["", "  ", "mile", "ft"])
def test_an_unsupported_or_empty_length_unit_is_refused(unit):
    with pytest.raises(ValueError, match="cannot be empty|Unsupported length unit"):
        normalize_length_unit(unit)


@pytest.mark.parametrize(
    ("meters", "unit", "precision", "text"),
    [
        (1500.0, "km", 3, "1.500 km"),
        (0.25, "cm", 1, "25.0 cm"),
        ("2", "mm", 0, "2000 mm"),
        (1.0, "m", 2, "1.00 m"),
    ],
)
def test_a_length_is_displayed_in_the_requested_unit(meters, unit, precision, text):
    assert format_length_from_m(meters, unit=unit, precision=precision) == text


def test_displaying_a_non_numeric_length_is_refused():
    with pytest.raises(ValueError, match="value_m must be numeric"):
        format_length_from_m("deep")


def test_displaying_in_a_length_and_converting_back_gives_the_same_length():
    for unit in ("m", "km", "cm", "mm"):
        text = format_length_from_m(123.456, unit=unit, precision=9)
        value, shown_unit = text.split()
        assert convert_to_m(float(value), unit=shown_unit) == pytest.approx(123.456)


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


def test_a_copyable_container_is_scaled_on_a_copy():
    original = _CopyScalable(3.0)
    assert convert_payload_to_m(original, unit="km").value == pytest.approx(3000.0)
    assert original.value == 3.0


def test_a_container_that_cannot_be_scaled_is_refused_as_not_numeric():
    with pytest.raises(TypeError, match="must be numeric"):
        convert_payload_to_m(_Unscalable(), unit="km")
