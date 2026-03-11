"""Unit tests for hydraulic-conductivity conversions to m/s."""

from __future__ import annotations

import pytest

from hydromodpy.support.units.hydraulic_conductivity import (
    convert_to_m_per_s,
    factor_to_m_per_s,
    normalize_m_per_s_unit,
    parse_to_m_per_s,
)


def test_normalize_m_per_s_unit_accepts_aliases() -> None:
    assert normalize_m_per_s_unit("m.s-1") == "m/s"
    assert normalize_m_per_s_unit("m/d") == "m/day"
    assert normalize_m_per_s_unit("cm/hr") == "cm/h"
    assert normalize_m_per_s_unit("mm/day") == "mm/day"


def test_factor_to_m_per_s_for_common_units() -> None:
    assert factor_to_m_per_s("m/s") == pytest.approx(1.0)
    assert factor_to_m_per_s("m/day") == pytest.approx(1.0 / 86400.0)
    assert factor_to_m_per_s("cm/day") == pytest.approx(1.0e-2 / 86400.0)
    assert factor_to_m_per_s("mm/h") == pytest.approx(1.0e-3 / 3600.0)


def test_convert_to_m_per_s() -> None:
    assert convert_to_m_per_s(8.64, unit="m/day") == pytest.approx(1.0e-4)
    assert convert_to_m_per_s(1.0, unit="cm/s") == pytest.approx(1.0e-2)


def test_parse_to_m_per_s_with_inline_unit() -> None:
    value_si, unit = parse_to_m_per_s(
        "8.64 m/day",
        location="test.value",
        default_unit="m/s",
    )
    assert unit == "m/day"
    assert value_si == pytest.approx(1.0e-4)


def test_parse_to_m_per_s_rejects_unknown_unit() -> None:
    with pytest.raises(ValueError, match="Unsupported hydraulic-conductivity unit"):
        _ = parse_to_m_per_s("10 foo/bar", location="test.value")
