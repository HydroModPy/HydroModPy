"""A cost margin carries its unit: a share of the best cost, or a length in meters.

``"5%"`` is a fraction of the best cost, ``"75 m"`` is a length. A bare number,
a zero, a negative and an unknown unit are refused with the label of the field.
"""

from __future__ import annotations

import pytest

from hydromodpy.core.scoring.cost_margin import NEEDS_A_UNIT, CostMargin, parse_cost_margin

# One row per text: the margin it reads as, in the unit it carries.
_READ = [
    pytest.param("5%", CostMargin("relative", 0.05), id="share"),
    pytest.param(" 12.5 % ", CostMargin("relative", 0.125), id="share_with_spaces"),
    pytest.param("75 m", CostMargin("absolute", 75.0), id="meters"),
    pytest.param("2 km", CostMargin("absolute", 2000.0), id="kilometers_to_meters"),
    pytest.param("150 cm", CostMargin("absolute", 1.5), id="centimeters_to_meters"),
    pytest.param("20 mm", CostMargin("absolute", 0.02), id="millimeters_to_meters"),
    pytest.param("1e2 cm", CostMargin("absolute", 1.0), id="exponent"),
    pytest.param(".5%", CostMargin("relative", 0.005), id="leading_dot"),
]


@pytest.mark.parametrize(("text", "expected"), _READ)
def test_a_margin_reads_in_the_unit_it_carries(text, expected) -> None:
    margin = parse_cost_margin(text)
    assert margin.kind == expected.kind
    assert margin.value == pytest.approx(expected.value)


# One row per refusal: the value and a phrase the message holds.
_REFUSED = [
    pytest.param("5", "has no unit", id="bare_text_number"),
    pytest.param(5, "has no unit", id="bare_number"),
    pytest.param(None, "has no unit", id="none"),
    pytest.param("0%", "strictly positive", id="zero_share"),
    pytest.param("-3 m", "strictly positive", id="negative_length"),
    pytest.param("nan m", "is not a share or a length", id="nan_is_no_number"),
    pytest.param("abc", "is not a share or a length", id="word"),
    pytest.param("5 parsecs", "Unsupported length unit", id="unknown_unit"),
]


@pytest.mark.parametrize(("value", "phrase"), _REFUSED)
def test_a_margin_without_a_usable_unit_is_refused_with_the_label(value, phrase) -> None:
    with pytest.raises(ValueError, match=phrase) as raised:
        parse_cost_margin(value, label="calibration.cost_margin")
    assert "calibration.cost_margin" in str(raised.value)


def test_a_bare_number_is_told_how_to_write_a_margin() -> None:
    with pytest.raises(ValueError) as raised:
        parse_cost_margin("5")
    assert NEEDS_A_UNIT in str(raised.value)
