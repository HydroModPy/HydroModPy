"""Property-based tests for the unit conversion layer.

A wrong factor is silent: it does not raise, it scales a conductivity or a
leakance by 86400 before the value reaches the solver. These tests state the
invariants over the whole input space, one strategy per quantity (its units).
The strongest guard is ``test_factor_tables_agree_with_pint``, which compares
every table row with the shared pint registry, an independent implementation.

Every test is pinned with ``derandomize=True`` so hypothesis replays the same
examples on every run, and ``deadline=None`` removes slow-runner flakiness.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Any

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from hydromodpy.core.units.parse import check_unit_compatible, parse_to_canonical_magnitude
from hydromodpy.core.units.quantities import (
    QUANTITIES,
    convert_to_si,
    factor_to_si,
    normalize_unit,
    parse_to_si,
)
from hydromodpy.core.units.time import (
    TIME_CANONICAL_UNITS,
    convert_seconds_to_unit,
    convert_to_seconds,
    factor_to_seconds,
    normalize_time_unit,
    to_modflow_itmuni,
)

UNIT_PROPERTY = settings(derandomize=True, max_examples=100, deadline=None)


@dataclass(frozen=True)
class Family:
    """One quantity, its units (the strategy) and its normalize, factor, convert functions."""

    name: str
    units: tuple[str, ...]
    si_unit: str  # The unit whose factor is exactly 1.0.
    pint_unit: str  # The same quantity in pint syntax, for the cross-check.
    normalize: Callable[[Any], str]
    factor: Callable[[Any], float]
    convert: Callable[..., float]
    parses: bool


def _family(name: str, si_unit: str, pint_unit: str) -> Family:
    """Build a family from the generic functions; time adds ITMUNI codes, so it has its own."""
    units = tuple(QUANTITIES[name][2])
    if name == "time":
        functions = (normalize_time_unit, factor_to_seconds, convert_to_seconds)
    else:
        functions = tuple(partial(f, name) for f in (normalize_unit, factor_to_si, convert_to_si))
    return Family(
        name, units, si_unit, pint_unit, *functions, parses=name not in ("time", "radiation")
    )


FAMILIES = (
    _family("length", "m", "m"),
    _family("time", "seconds", "s"),
    _family("hydraulic_conductivity", "m/s", "m/s"),
    _family("hydraulic_conductance", "m2/s", "m**2/s"),
    _family("volumetric_flow", "m3/s", "m**3/s"),
    _family("leakance", "1/s", "1/s"),
    _family("radiation", "W/m2", "W/m**2"),
)
PER_FAMILY = pytest.mark.parametrize("family", FAMILIES, ids=[f.name for f in FAMILIES])

# Narrow on purpose: the smallest factor is ~1e-11 and the largest ~3e7, so
# [1e-6, 1e6] stays far from subnormals and overflow. Zero is explicit, as the
# one magnitude where sign and relative tolerance degenerate.
_POSITIVE = st.floats(min_value=1e-6, max_value=1e6, allow_nan=False, allow_infinity=False)
MAGNITUDES = st.one_of(st.just(0.0), _POSITIVE, _POSITIVE.map(lambda value: -value))


def _mangle(unit: str, *, upper: bool, spaced: bool, padded: bool) -> str:
    """Rewrite a unit token the way a careless TOML file would."""
    token = unit.upper() if upper else unit
    token = " ".join(token) if spaced else token
    return f"  {token}\t" if padded else token


@PER_FAMILY
@given(value=MAGNITUDES)
@UNIT_PROPERTY
def test_converting_in_the_si_unit_is_the_identity(family: Family, value: float) -> None:
    """The SI unit must convert bit for bit, or an unconverted value drifts unseen."""
    assert family.factor(family.si_unit) == 1.0
    assert family.convert(value, unit=family.si_unit) == value


@PER_FAMILY
@given(value=MAGNITUDES, data=st.data())
@UNIT_PROPERTY
def test_conversion_is_the_factor_applied_and_is_reversible(
    family: Family, value: float, data: st.DataObject
) -> None:
    """Converting then dividing by the published factor returns the input."""
    unit = data.draw(st.sampled_from(family.units))
    converted = family.convert(value, unit=unit)
    assert converted == pytest.approx(value * family.factor(unit), rel=1e-15, abs=0.0)
    assert converted / family.factor(unit) == pytest.approx(value, rel=1e-12, abs=1e-300)


@PER_FAMILY
@given(low=MAGNITUDES, high=MAGNITUDES, data=st.data())
@UNIT_PROPERTY
def test_conversion_preserves_sign_and_order(
    family: Family, low: float, high: float, data: st.DataObject
) -> None:
    """A strictly positive factor makes the conversion monotone and sign-keeping."""
    assume(low <= high)
    unit = data.draw(st.sampled_from(family.units))
    converted_low = family.convert(low, unit=unit)
    assert converted_low <= family.convert(high, unit=unit)
    assert math.copysign(1.0, converted_low) == math.copysign(1.0, low)


@PER_FAMILY
@given(value=MAGNITUDES, data=st.data())
@UNIT_PROPERTY
def test_factor_tables_agree_with_pint(family: Family, value: float, data: st.DataObject) -> None:
    """Each table row must match the shared pint registry, which parse.py uses."""
    unit = data.draw(st.sampled_from(family.units))
    theirs = parse_to_canonical_magnitude(
        value,
        location=f"{family.name}.value",
        canonical_unit=family.pint_unit,
        explicit_unit=unit,
    )
    # 1e-12 is set by float64 associativity in pint's own chain, not by slack.
    assert family.convert(value, unit=unit) == pytest.approx(theirs, rel=1e-12, abs=1e-300)


@PER_FAMILY
@given(
    upper=st.booleans(),
    spaced=st.booleans(),
    padded=st.booleans(),
    data=st.data(),
)
@UNIT_PROPERTY
def test_unit_tokens_are_case_and_whitespace_insensitive(
    family: Family, upper: bool, spaced: bool, padded: bool, data: st.DataObject
) -> None:
    """``M3/DAY`` and `` m 3 / d a y `` resolve like ``m3/day``: units come from TOML."""
    unit = data.draw(st.sampled_from(family.units))
    mangled = _mangle(unit, upper=upper, spaced=spaced, padded=padded)
    assert family.normalize(mangled) == family.normalize(unit)
    assert family.factor(mangled) == family.factor(unit)


@PER_FAMILY
@given(value=MAGNITUDES, text=st.text(min_size=0, max_size=12))
@UNIT_PROPERTY
def test_a_unit_the_normalizer_rejects_is_rejected_by_the_converter(
    family: Family, value: float, text: str
) -> None:
    """Validator and converter reject the same tokens, whatever the magnitude."""
    try:
        family.normalize(text)
    except ValueError:
        pass
    else:
        assume(False)
    with pytest.raises(ValueError):
        family.convert(value, unit=text)


@PER_FAMILY
@given(data=st.data())
@UNIT_PROPERTY
def test_a_unit_from_another_family_is_rejected_as_incompatible(
    family: Family, data: st.DataObject
) -> None:
    """The seven quantities have seven dimensions, so a borrowed unit must not pass."""
    other = data.draw(st.sampled_from([f for f in FAMILIES if f.name != family.name]))
    unit = data.draw(st.sampled_from(other.units))
    with pytest.raises(ValueError):
        check_unit_compatible(unit, canonical_unit=family.pint_unit, label=family.name)


@PER_FAMILY
@given(data=st.data())
@UNIT_PROPERTY
def test_booleans_are_rejected_whatever_the_unit(family: Family, data: st.DataObject) -> None:
    """``True`` is an ``int``: without the guard it would convert to one metre."""
    unit = data.draw(st.sampled_from(family.units))
    for flag in (True, False):
        with pytest.raises(TypeError):
            family.convert(flag, unit=unit)


@pytest.mark.parametrize(
    "family", [f for f in FAMILIES if f.parses], ids=[f.name for f in FAMILIES if f.parses]
)
@given(value=MAGNITUDES, data=st.data())
@UNIT_PROPERTY
def test_the_inline_unit_parser_matches_the_direct_conversion(
    family: Family, value: float, data: st.DataObject
) -> None:
    """``parse("3.5 cm")`` equals ``convert(3.5, unit="cm")``; repr round-trips a float."""
    unit = data.draw(st.sampled_from(family.units))
    parsed, canonical = parse_to_si(
        family.name,
        f"{value!r} {unit}",
        location=f"{family.name}.value",
        default_unit=family.si_unit,
    )
    assert canonical == family.normalize(unit)
    assert parsed == pytest.approx(family.convert(value, unit=unit), rel=1e-15, abs=0.0)


@given(value=MAGNITUDES, data=st.data())
@UNIT_PROPERTY
def test_time_conversion_round_trips_through_seconds(value: float, data: st.DataObject) -> None:
    """Time is the only family with a way back out of SI, and every model clock uses it."""
    unit = data.draw(st.sampled_from(TIME_CANONICAL_UNITS))
    seconds = convert_to_seconds(value, unit=unit)
    assert convert_seconds_to_unit(seconds, unit=unit) == pytest.approx(
        value, rel=1e-12, abs=1e-300
    )


@given(value=MAGNITUDES, data=st.data())
@UNIT_PROPERTY
def test_time_conversion_composes(value: float, data: st.DataObject) -> None:
    """a to b to c equals a to c, which is what makes seconds a safe pivot."""
    unit_a, unit_b, unit_c = (data.draw(st.sampled_from(TIME_CANONICAL_UNITS)) for _ in range(3))
    in_b = convert_seconds_to_unit(convert_to_seconds(value, unit=unit_a), unit=unit_b)
    stepwise = convert_seconds_to_unit(convert_to_seconds(in_b, unit=unit_b), unit=unit_c)
    direct = convert_seconds_to_unit(convert_to_seconds(value, unit=unit_a), unit=unit_c)
    assert stepwise == pytest.approx(direct, rel=1e-12, abs=1e-300)


@given(data=st.data())
@UNIT_PROPERTY
def test_derived_factors_are_coherent_with_length_and_time(data: st.DataObject) -> None:
    """A derived factor is the length factor over the time factor (m/s, m2/s, 1/s)."""
    length_unit = data.draw(st.sampled_from(("m", "cm", "mm")))
    time_unit = data.draw(st.sampled_from(("s", "h", "day")))
    seconds = factor_to_seconds(time_unit)
    metres = factor_to_si("length", length_unit)
    assert factor_to_si("hydraulic_conductivity", f"{length_unit}/{time_unit}") == pytest.approx(
        metres / seconds, rel=1e-12
    )
    assert factor_to_si("hydraulic_conductance", f"{length_unit}2/{time_unit}") == pytest.approx(
        metres**2 / seconds, rel=1e-12
    )
    assert factor_to_si("leakance", f"1/{time_unit}") == pytest.approx(1.0 / seconds, rel=1e-12)


@given(data=st.data())
@UNIT_PROPERTY
def test_volumetric_flow_factors_are_coherent_with_length_and_time(data: st.DataObject) -> None:
    """``m3/T`` is a cubic metre per T and a litre is a thousandth of it (not a length cubed)."""
    time_unit = data.draw(st.sampled_from(("s", "h", "min", "day")))
    seconds = factor_to_seconds(time_unit)
    assert factor_to_si("volumetric_flow", f"m3/{time_unit}") == pytest.approx(
        factor_to_si("length", "m") ** 3 / seconds, rel=1e-12
    )
    assert factor_to_si("volumetric_flow", f"l/{time_unit}") == pytest.approx(
        1.0e-3 / seconds, rel=1e-12
    )


@given(code=st.integers(min_value=1, max_value=5), data=st.data())
@UNIT_PROPERTY
def test_modflow_itmuni_codes_round_trip(code: int, data: st.DataObject) -> None:
    """The ITMUNI integer reads back as the same unit, as int, float or string."""
    unit = normalize_time_unit(code)
    assert to_modflow_itmuni(unit) == code
    assert normalize_time_unit(to_modflow_itmuni(unit)) == unit
    spelling = data.draw(st.sampled_from((code, float(code), str(code))))
    assert normalize_time_unit(spelling) == unit
