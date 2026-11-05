"""Unit-aware config types: a unit written by the user lands in SI, errors name the problem."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from hydromodpy.core.units import UREG
from hydromodpy.core.units.types import (
    AreaSquareMeters,
    DurationDays,
    DurationSeconds,
    FluxDensityMPerS,
    HydraulicConductivity,
    HydraulicConductivityMPerS,
    Length,
    LengthMeters,
    LengthMillimeters,
    SpecificYield,
    VolumetricFlowM3PerSecond,
)

# ------------------------------------------------------------ float flavors


class _Floats(BaseModel):
    length: LengthMeters | None = None
    mm: LengthMillimeters | None = None
    area: AreaSquareMeters | None = None
    flow: VolumetricFlowM3PerSecond | None = None
    seconds: DurationSeconds | None = None
    days: DurationDays | None = None
    k: HydraulicConductivityMPerS | None = None
    recharge: FluxDensityMPerS | None = None


@pytest.mark.parametrize(
    ("field", "given", "expected"),
    [
        ("length", 50, 50.0),
        ("length", "1 km", 1000.0),
        ("length", "250 cm", 2.5),
        ("length", " 3 m ", 3.0),
        ("length", {"value": 2, "unit": "km"}, 2000.0),
        ("length", {"value": 7}, 7.0),  # no unit: the canonical one
        ("mm", "12 cm", 120.0),
        ("mm", 120, 120.0),
        ("area", "2 km**2", 2.0e6),
        ("flow", "1 m**3/h", 1 / 3600),
        ("seconds", "1 day", 86400.0),
        ("days", "1 week", 7.0),
        ("k", "0.36 m/h", 1.0e-4),
        ("recharge", "86.4 mm/day", 1.0e-6),
        ("recharge", UREG.Quantity(1.0, "mm/day"), 1.0e-3 / 86400),
    ],
)
def test_a_value_written_with_its_unit_is_stored_in_the_canonical_si_unit(field, given, expected):
    assert getattr(_Floats(**{field: given}), field) == pytest.approx(expected)


def test_an_absent_value_stays_none():
    assert _Floats(length=None).length is None


@pytest.mark.parametrize(
    ("field", "given", "match"),
    [
        ("length", "50", "dimensionless"),  # a string needs its unit
        ("length", "", "empty string"),
        ("length", "   ", "empty string"),
        ("length", "3 s", "dimension|convert|Cannot"),
        ("length", "banana", "banana|not defined|Cannot"),
        ("length", UREG.Quantity(1.0, "kg"), "dimension|convert|Cannot"),
        ("length", {"value": 1, "unit": "bogus_unit"}, "bogus_unit|not defined"),
        ("length", {"value": 1, "unit": "s"}, "dimension|convert|Cannot"),
        ("k", "1 m", "dimension|convert|Cannot"),
    ],
)
def test_a_wrong_dimension_a_boolean_or_an_unreadable_value_is_refused_by_validation(
    field, given, match
):
    with pytest.raises(ValidationError, match=match):
        _Floats(**{field: given})


@pytest.mark.parametrize(
    "given", [True, {"unit": "km"}, [1, 2]], ids=["boolean", "mapping-without-value", "list"]
)
def test_a_value_of_no_readable_kind_is_refused_by_validation(given):
    # Pydantic only wraps ValueError, so a TypeError would reach the caller raw.
    with pytest.raises(ValidationError, match="boolean|unsupported value"):
        _Floats(length=given)


# --------------------------------------------------------- pint quantities


class _Quantities(BaseModel):
    length: Length | None = None
    k: HydraulicConductivity | None = None
    sy: SpecificYield = 0.1


def test_a_quantity_type_keeps_its_unit_and_converts_on_demand():
    model = _Quantities(length="100 cm", k="0.36 m/h")
    assert model.length.to("m").magnitude == pytest.approx(1.0)
    assert model.k.to("m/s").magnitude == pytest.approx(1.0e-4)


def test_a_bare_number_is_read_in_the_canonical_unit():
    assert _Quantities(length=2.5).length.to("m").magnitude == pytest.approx(2.5)


def test_a_boolean_is_refused_instead_of_read_as_one_metre():
    with pytest.raises(ValidationError, match="boolean"):
        _Quantities(length=True)


def test_a_quantity_dumps_as_a_float_in_the_canonical_unit_and_round_trips():
    model = _Quantities(length="2 km", k="36 m/h")
    dumped = model.model_dump()
    assert dumped["length"] == pytest.approx(2000.0)
    assert dumped["k"] == pytest.approx(1.0e-2)
    again = _Quantities(**dumped)
    assert again.length.to("m").magnitude == pytest.approx(2000.0)
    assert again.k.to("m/s").magnitude == pytest.approx(1.0e-2)
    assert _Quantities().model_dump()["length"] is None


def test_an_unvalidated_default_bare_number_still_serializes_as_a_float():
    class _Defaulted(BaseModel):
        length: Length = 3.0

    assert _Defaulted().model_dump() == {"length": 3.0}


@pytest.mark.parametrize("value", [-0.01, 1.01])
def test_a_specific_yield_outside_zero_one_is_refused(value):
    with pytest.raises(ValidationError):
        _Quantities(sy=value)
