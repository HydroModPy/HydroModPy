"""Unit tests for hydraulic-conductance conversions to m2/s."""

from __future__ import annotations

import pytest

from hydromodpy.support.units.hydraulic_conductance import (
    convert_to_m2_per_s,
    factor_to_m2_per_s,
    normalize_m2_per_s_unit,
    parse_to_m2_per_s,
)


def test_normalize_m2_per_s_unit_accepts_aliases() -> None:
    assert normalize_m2_per_s_unit("m^2/s") == "m2/s"
    assert normalize_m2_per_s_unit("m2/d") == "m2/day"
    assert normalize_m2_per_s_unit("cm2/hr") == "cm2/h"
    assert normalize_m2_per_s_unit("mm2/day") == "mm2/day"


def test_factor_to_m2_per_s_for_common_units() -> None:
    assert factor_to_m2_per_s("m2/s") == pytest.approx(1.0)
    assert factor_to_m2_per_s("m2/day") == pytest.approx(1.0 / 86400.0)
    assert factor_to_m2_per_s("cm2/day") == pytest.approx(1.0e-4 / 86400.0)
    assert factor_to_m2_per_s("mm2/h") == pytest.approx(1.0e-6 / 3600.0)


def test_convert_to_m2_per_s() -> None:
    assert convert_to_m2_per_s(8.64, unit="m2/day") == pytest.approx(1.0e-4)
    assert convert_to_m2_per_s(1.0, unit="cm2/s") == pytest.approx(1.0e-4)


def test_parse_to_m2_per_s_with_inline_unit() -> None:
    value_si, unit = parse_to_m2_per_s(
        "8.64 m2/day",
        location="test.value",
        default_unit="m2/s",
    )
    assert unit == "m2/day"
    assert value_si == pytest.approx(1.0e-4)


def test_parse_to_m2_per_s_rejects_unknown_unit() -> None:
    with pytest.raises(ValueError, match="Unsupported hydraulic-conductance unit"):
        _ = parse_to_m2_per_s("10 foo/day", location="test.value")
