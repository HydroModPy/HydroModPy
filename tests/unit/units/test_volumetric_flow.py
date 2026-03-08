"""Unit tests for volumetric-flow conversions to m3/s."""

from __future__ import annotations

import pytest

from hydromodpy.units.volumetric_flow import (
    convert_to_m3_per_s,
    factor_to_m3_per_s,
    normalize_m3_per_s_unit,
    parse_to_m3_per_s,
)


def test_normalize_m3_per_s_unit_accepts_aliases() -> None:
    assert normalize_m3_per_s_unit("m3/d") == "m3/day"
    assert normalize_m3_per_s_unit("m3/hr") == "m3/h"
    assert normalize_m3_per_s_unit("L/s") == "l/s"
    assert normalize_m3_per_s_unit("l/min") == "l/min"


def test_factor_to_m3_per_s_for_common_units() -> None:
    assert factor_to_m3_per_s("m3/s") == pytest.approx(1.0)
    assert factor_to_m3_per_s("m3/day") == pytest.approx(1.0 / 86400.0)
    assert factor_to_m3_per_s("m3/h") == pytest.approx(1.0 / 3600.0)
    assert factor_to_m3_per_s("l/s") == pytest.approx(1.0e-3)


def test_convert_to_m3_per_s() -> None:
    assert convert_to_m3_per_s(86400.0, unit="m3/day") == pytest.approx(1.0)
    assert convert_to_m3_per_s(1000.0, unit="l/s") == pytest.approx(1.0)


def test_parse_to_m3_per_s_with_inline_unit() -> None:
    value_si, unit = parse_to_m3_per_s(
        "3600 m3/h",
        location="test.value",
        default_unit="m3/s",
    )
    assert unit == "m3/h"
    assert value_si == pytest.approx(1.0)


def test_parse_to_m3_per_s_rejects_unknown_unit() -> None:
    with pytest.raises(ValueError, match="Unsupported volumetric-flow unit"):
        _ = parse_to_m3_per_s("10 foo/day", location="test.value")
