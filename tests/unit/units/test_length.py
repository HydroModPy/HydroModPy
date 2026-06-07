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
