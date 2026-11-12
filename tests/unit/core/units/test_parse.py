"""Reading a unit written by a user and converting it to the canonical unit of its quantity.

A unit that pint does not know, or that measures another quantity, is refused
with a message that names the unit.
"""

from __future__ import annotations

import pytest

from hydromodpy.core.units.parse import (
    canonical_unit_short_form,
    check_unit_compatible,
    convert_between_units,
    parse_to_canonical_magnitude,
)

UNIT_REFUSALS = [
    pytest.param(check_unit_compatible, "", "unit cannot be empty", id="check, empty"),
    pytest.param(check_unit_compatible, "s", "Unsupported length unit 's'", id="check, a duration"),
    pytest.param(canonical_unit_short_form, " ", "unit cannot be empty", id="short form, empty"),
    pytest.param(
        canonical_unit_short_form, "s", "Unsupported length unit 's'", id="short form, a duration"
    ),
]


@pytest.mark.parametrize(("function", "unit", "message"), UNIT_REFUSALS)
def test_unit_refusals(function, unit, message) -> None:
    with pytest.raises(ValueError, match=message):
        function(unit, canonical_unit="m", label="length")


def test_an_unknown_unit_is_named() -> None:
    with pytest.raises(ValueError, match="x: unit 'bogus' is not recognized"):
        parse_to_canonical_magnitude("3 bogus", location="x", canonical_unit="m")


CONVERSION_REFUSALS = [
    pytest.param("bogus", "m", "cannot be read", id="unknown unit"),
    pytest.param(" ", "m", "measure different quantities", id="blank unit is a bare number"),
]


@pytest.mark.parametrize(("source", "target", "message"), CONVERSION_REFUSALS)
def test_conversion_refusals(source, target, message) -> None:
    with pytest.raises(ValueError, match=message):
        convert_between_units(1.0, from_unit=source, to_unit=target)


def test_two_spellings_of_no_unit_keep_the_value() -> None:
    assert convert_between_units(2.5, from_unit="-", to_unit="dimensionless") == 2.5
