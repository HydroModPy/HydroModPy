"""Property-based tests for the unit conversion layer.

The example-based tests next to this file pin a handful of hand-picked
conversions ("150 cm is 1.5 m"). They cannot see a factor that is wrong only
for one unit of one family, and a wrong factor here is silent: it does not
raise, it just scales a hydraulic conductivity or a lake leakance by 86400
before the value reaches the solver. These tests state the invariants over the
whole continuous input space instead.

The strongest guard is
:func:`test_factor_tables_agree_with_pint`: every family keeps a bespoke
factor table for speed (the tables avoid loading pint on the hot path), and
that table must agree with the shared pint registry, which is an independent
implementation. Perturbing any single entry of any table fails it.

Determinism: every test is pinned with ``derandomize=True`` so hypothesis
replays the same examples on every run, matching the intent of the
``_deterministic_seeds`` fixture in ``tests/conftest.py``. ``deadline=None``
removes the only remaining source of flakiness, a slow shared CI runner.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from hydromodpy.core.units.hydraulic_conductance import (
    M2_PER_S_CANONICAL_UNITS,
    convert_to_m2_per_s,
    factor_to_m2_per_s,
    normalize_m2_per_s_unit,
    parse_to_m2_per_s,
)
from hydromodpy.core.units.hydraulic_conductivity import (
    M_PER_S_CANONICAL_UNITS,
    convert_to_m_per_s,
    factor_to_m_per_s,
    normalize_m_per_s_unit,
    parse_to_m_per_s,
)
from hydromodpy.core.units.leakance import (
    PER_S_CANONICAL_UNITS,
    convert_to_per_s,
    factor_to_per_s,
    normalize_per_s_unit,
    parse_to_per_s,
)
from hydromodpy.core.units.length import (
    LENGTH_CANONICAL_UNITS,
    convert_to_m,
    factor_to_m,
    normalize_length_unit,
    parse_to_m,
)
from hydromodpy.core.units.parse import check_unit_compatible, parse_to_canonical_magnitude
from hydromodpy.core.units.radiation import (
    RADIATION_CANONICAL_UNITS,
    convert_to_w_per_m2,
    factor_to_w_per_m2,
    normalize_radiation_unit,
)
from hydromodpy.core.units.time import (
    TIME_CANONICAL_UNITS,
    convert_seconds_to_unit,
    convert_to_seconds,
    factor_to_seconds,
    normalize_time_unit,
    to_modflow_itmuni,
)
from hydromodpy.core.units.volumetric_flow import (
    M3_PER_S_CANONICAL_UNITS,
    convert_to_m3_per_s,
    factor_to_m3_per_s,
    normalize_m3_per_s_unit,
    parse_to_m3_per_s,
)

# Pinned so a green run today is a green run on any runner, forever. Without
# derandomize a property test is a lottery ticket that CI eventually loses, and
# a muted flaky test guards nothing.
UNIT_PROPERTY = settings(derandomize=True, max_examples=100, deadline=None)


@dataclass(frozen=True)
class Family:
    """One quantity family and the uniform four-function API it exposes."""

    name: str
    units: tuple[str, ...]
    si_unit: str  # The unit whose conversion factor is exactly 1.0.
    pint_unit: str  # Same quantity written in pint syntax, for the cross-check.
    normalize: Callable[[Any], str]
    factor: Callable[[Any], float]
    convert: Callable[..., float]
    parse: Callable[..., tuple[float, str]] | None


FAMILIES: tuple[Family, ...] = (
    Family(
        "length",
        LENGTH_CANONICAL_UNITS,
        "m",
        "m",
        normalize_length_unit,
        factor_to_m,
        convert_to_m,
        parse_to_m,
    ),
    Family(
        "time",
        TIME_CANONICAL_UNITS,
        "seconds",
        "s",
        normalize_time_unit,
        factor_to_seconds,
        convert_to_seconds,
        None,
    ),
    Family(
        "hydraulic_conductivity",
        M_PER_S_CANONICAL_UNITS,
        "m/s",
        "m/s",
        normalize_m_per_s_unit,
        factor_to_m_per_s,
        convert_to_m_per_s,
        parse_to_m_per_s,
    ),
    Family(
        "hydraulic_conductance",
        M2_PER_S_CANONICAL_UNITS,
        "m2/s",
        "m**2/s",
        normalize_m2_per_s_unit,
        factor_to_m2_per_s,
        convert_to_m2_per_s,
        parse_to_m2_per_s,
    ),
    Family(
        "volumetric_flow",
        M3_PER_S_CANONICAL_UNITS,
        "m3/s",
        "m**3/s",
        normalize_m3_per_s_unit,
        factor_to_m3_per_s,
        convert_to_m3_per_s,
        parse_to_m3_per_s,
    ),
    Family(
        "leakance",
        PER_S_CANONICAL_UNITS,
        "1/s",
        "1/s",
        normalize_per_s_unit,
        factor_to_per_s,
        convert_to_per_s,
        parse_to_per_s,
    ),
    Family(
        "radiation",
        RADIATION_CANONICAL_UNITS,
        "W/m2",
        "W/m**2",
        normalize_radiation_unit,
        factor_to_w_per_m2,
        convert_to_w_per_m2,
        None,
    ),
)

FAMILY_IDS = [family.name for family in FAMILIES]

# Magnitude bounds, deliberately narrow. The smallest factor in the layer is
# mm2/day at ~1e-11 and the largest is years at ~3e7, so a magnitude inside
# [1e-6, 1e6] stays between roughly 1e-17 and 1e14 after conversion: far above
# the subnormal range where relative error stops being bounded by machine
# epsilon, and far below the overflow to inf. An unbounded float strategy would
# fail on 1e308 * 86400 and on denormals, which says nothing about the factor
# tables and would only teach us to mute the test.
_POSITIVE_MAGNITUDE = st.floats(
    min_value=1e-6,
    max_value=1e6,
    allow_nan=False,
    allow_infinity=False,
)
# Zero is carried explicitly: it is the one magnitude where sign and relative
# tolerance both degenerate, and every conversion must still return it exactly.
MAGNITUDES = st.one_of(
    st.just(0.0),
    _POSITIVE_MAGNITUDE,
    _POSITIVE_MAGNITUDE.map(lambda value: -value),
)


def _mangle(unit: str, *, upper: bool, spaced: bool, padded: bool) -> str:
    """Rewrite a unit token the way a careless TOML file would."""
    token = unit.upper() if upper else unit
    if spaced:
        token = " ".join(token)
    if padded:
        token = f"  {token}\t"
    return token


@pytest.mark.parametrize("family", FAMILIES, ids=FAMILY_IDS)
@given(value=MAGNITUDES)
@UNIT_PROPERTY
def test_converting_in_the_si_unit_is_the_identity(family: Family, value: float) -> None:
    """The SI unit of each family must convert bit-for-bit, not merely closely.

    Every family declares one unit whose factor is exactly 1.0. If a rounding
    creeps into that path, a value that was never converted still drifts, and
    the drift is invisible because it is small.
    """
    assert family.factor(family.si_unit) == 1.0
    assert family.convert(value, unit=family.si_unit) == value


@pytest.mark.parametrize("family", FAMILIES, ids=FAMILY_IDS)
@given(value=MAGNITUDES, data=st.data())
@UNIT_PROPERTY
def test_conversion_is_the_factor_applied_and_is_reversible(
    family: Family, value: float, data: st.DataObject
) -> None:
    """Converting then dividing by the same factor returns the input.

    This is the round trip the layer actually supports: the converters only go
    towards SI, so the way back is the published factor. It catches a converter
    that stops agreeing with the factor it advertises, for instance one that
    divides where it should multiply.
    """
    unit = data.draw(st.sampled_from(family.units))
    converted = family.convert(value, unit=unit)
    assert converted == pytest.approx(value * family.factor(unit), rel=1e-15, abs=0.0)
    assert converted / family.factor(unit) == pytest.approx(value, rel=1e-12, abs=1e-300)


@pytest.mark.parametrize("family", FAMILIES, ids=FAMILY_IDS)
@given(low=MAGNITUDES, high=MAGNITUDES, data=st.data())
@UNIT_PROPERTY
def test_conversion_preserves_sign_and_order(
    family: Family, low: float, high: float, data: st.DataObject
) -> None:
    """Every factor is strictly positive, so conversion is monotone.

    A negative or zero factor would silently flip the sign of a flux or wipe a
    conductivity to zero. Order preservation is the cheapest statement that
    rules both out over the whole input space.
    """
    assume(low <= high)
    unit = data.draw(st.sampled_from(family.units))
    converted_low = family.convert(low, unit=unit)
    converted_high = family.convert(high, unit=unit)
    assert converted_low <= converted_high
    assert math.copysign(1.0, converted_low) == math.copysign(1.0, low)


@pytest.mark.parametrize("family", FAMILIES, ids=FAMILY_IDS)
@given(value=MAGNITUDES, data=st.data())
@UNIT_PROPERTY
def test_factor_tables_agree_with_pint(family: Family, value: float, data: st.DataObject) -> None:
    """The hand-written factor tables must match the shared pint registry.

    Each family keeps its own dict of factors so the common path never imports
    pint, but ``hydromodpy.core.units.parse`` resolves the same units through
    pint. Two implementations of one number is only safe while they agree, and
    nothing else in the suite compares them. This is the test that fails when a
    factor is edited by hand.
    """
    unit = data.draw(st.sampled_from(family.units))
    ours = family.convert(value, unit=unit)
    theirs = parse_to_canonical_magnitude(
        value,
        location=f"{family.name}.value",
        canonical_unit=family.pint_unit,
        explicit_unit=unit,
    )
    # 1e-12 is many orders above the ~1e-16 spread actually observed; it is set
    # by float64 associativity in pint's own chain, not by any real slack.
    assert ours == pytest.approx(theirs, rel=1e-12, abs=1e-300)


@pytest.mark.parametrize("family", FAMILIES, ids=FAMILY_IDS)
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
    """A unit written ``M3/DAY`` or `` m 3 / d a y `` must resolve identically.

    Units reach this layer from user-edited TOML and from solver metadata, so
    the casing and the spacing are not under our control. The normalizer strips
    both; the factor it yields must not depend on either.
    """
    unit = data.draw(st.sampled_from(family.units))
    mangled = _mangle(unit, upper=upper, spaced=spaced, padded=padded)
    assert family.normalize(mangled) == family.normalize(unit)
    assert family.factor(mangled) == family.factor(unit)


@pytest.mark.parametrize("family", FAMILIES, ids=FAMILY_IDS)
@given(value=MAGNITUDES, text=st.text(min_size=0, max_size=12))
@UNIT_PROPERTY
def test_a_unit_the_normalizer_rejects_is_rejected_by_the_converter(
    family: Family, value: float, text: str
) -> None:
    """The validator and the converter must reject exactly the same tokens.

    If a token slips past the converter that the normalizer refuses, an unknown
    unit reaches the solver as if it were canonical. The value is the free
    variable on purpose: rejection must not depend on the magnitude.
    """
    try:
        family.normalize(text)
    except ValueError:
        pass
    else:
        assume(False)
    with pytest.raises(ValueError):
        family.convert(value, unit=text)


@pytest.mark.parametrize("family", FAMILIES, ids=FAMILY_IDS)
@given(data=st.data())
@UNIT_PROPERTY
def test_a_unit_from_another_family_is_rejected_as_incompatible(
    family: Family, data: st.DataObject
) -> None:
    """A unit of the right shape but the wrong dimension must not pass.

    The seven canonical targets have seven distinct dimensions, so any unit
    borrowed from another family is dimensionally incompatible. This guards the
    pint-backed checker used by the config normalizers, where a copy-pasted
    ``m/s`` under a ``m3/s`` key is a realistic mistake.
    """
    other = data.draw(st.sampled_from([f for f in FAMILIES if f.name != family.name]))
    unit = data.draw(st.sampled_from(other.units))
    with pytest.raises(ValueError):
        check_unit_compatible(unit, canonical_unit=family.pint_unit, label=family.name)


@pytest.mark.parametrize("family", FAMILIES, ids=FAMILY_IDS)
@given(data=st.data())
@UNIT_PROPERTY
def test_booleans_are_rejected_whatever_the_unit(family: Family, data: st.DataObject) -> None:
    """``True`` is an ``int`` in Python, so it must be trapped explicitly.

    TOML and JSON payloads carry booleans, and without the guard ``True`` would
    convert to one metre instead of raising.
    """
    unit = data.draw(st.sampled_from(family.units))
    with pytest.raises(TypeError):
        family.convert(True, unit=unit)
    with pytest.raises(TypeError):
        family.convert(False, unit=unit)


_PARSING_FAMILIES = tuple(family for family in FAMILIES if family.parse is not None)


@pytest.mark.parametrize("family", _PARSING_FAMILIES, ids=[f.name for f in _PARSING_FAMILIES])
@given(value=MAGNITUDES, data=st.data())
@UNIT_PROPERTY
def test_the_inline_unit_parser_matches_the_direct_conversion(
    family: Family, value: float, data: st.DataObject
) -> None:
    """``parse_to_x("3.5 cm")`` must equal ``convert_to_x(3.5, unit="cm")``.

    Configs may write the unit inline in the string or in a separate ``unit``
    field, and the two spellings must land on the same number. ``repr`` is used
    to build the string because it round-trips a float exactly.
    """
    assert family.parse is not None
    unit = data.draw(st.sampled_from(family.units))
    parsed, canonical = family.parse(
        f"{value!r} {unit}",
        location=f"{family.name}.value",
        default_unit=family.si_unit,
    )
    assert canonical == family.normalize(unit)
    assert parsed == pytest.approx(family.convert(value, unit=unit), rel=1e-15, abs=0.0)


@given(value=MAGNITUDES, data=st.data())
@UNIT_PROPERTY
def test_time_conversion_round_trips_through_seconds(value: float, data: st.DataObject) -> None:
    """Seconds are the pivot every model clock passes through.

    Time is the only family with a published way back out of SI, so it is the
    only one where the true round trip can be stated. HMP runs MODFLOW 6 in
    seconds and reports in days, so this path is crossed on every run.
    """
    unit = data.draw(st.sampled_from(TIME_CANONICAL_UNITS))
    seconds = convert_to_seconds(value, unit=unit)
    assert convert_seconds_to_unit(seconds, unit=unit) == pytest.approx(
        value, rel=1e-12, abs=1e-300
    )


@given(value=MAGNITUDES, data=st.data())
@UNIT_PROPERTY
def test_time_conversion_composes(value: float, data: st.DataObject) -> None:
    """Going a to b then b to c must equal going a to c directly.

    Composition is what makes seconds safe as an intermediate representation.
    If it failed, the reported duration would depend on how many times the
    value happened to be re-expressed on the way out.
    """
    unit_a = data.draw(st.sampled_from(TIME_CANONICAL_UNITS))
    unit_b = data.draw(st.sampled_from(TIME_CANONICAL_UNITS))
    unit_c = data.draw(st.sampled_from(TIME_CANONICAL_UNITS))
    in_b = convert_seconds_to_unit(convert_to_seconds(value, unit=unit_a), unit=unit_b)
    stepwise = convert_seconds_to_unit(convert_to_seconds(in_b, unit=unit_b), unit=unit_c)
    direct = convert_seconds_to_unit(convert_to_seconds(value, unit=unit_a), unit=unit_c)
    assert stepwise == pytest.approx(direct, rel=1e-12, abs=1e-300)


@given(data=st.data())
@UNIT_PROPERTY
def test_derived_factors_are_coherent_with_length_and_time(data: st.DataObject) -> None:
    """A derived factor must be the length factor over the time factor.

    ``m/s``, ``m2/s``, ``m3/s`` and ``1/s`` each keep their own table, written
    out by hand rather than composed. Nothing forces those four tables to stay
    consistent with the length and time tables they are built from, so a
    typo in one of them survives every example-based test. Stating the
    composition is what makes the four tables one fact instead of four.
    """
    length_unit = data.draw(st.sampled_from(("m", "cm", "mm")))
    time_unit = data.draw(st.sampled_from(("s", "h", "day")))
    seconds = factor_to_seconds(time_unit)
    metres = factor_to_m(length_unit)

    assert factor_to_m_per_s(f"{length_unit}/{time_unit}") == pytest.approx(
        metres / seconds, rel=1e-12
    )
    assert factor_to_m2_per_s(f"{length_unit}2/{time_unit}") == pytest.approx(
        metres**2 / seconds, rel=1e-12
    )
    assert factor_to_per_s(f"1/{time_unit}") == pytest.approx(1.0 / seconds, rel=1e-12)


@given(data=st.data())
@UNIT_PROPERTY
def test_volumetric_flow_factors_are_coherent_with_length_and_time(
    data: st.DataObject,
) -> None:
    """``m3/T`` is a cubic metre per T, and a litre is exactly a thousandth of it.

    Split out from the other derived families because the litre branch is not a
    length cubed: it is the one place where the volume unit is not spelled as a
    power of a length, so it needs its own statement.
    """
    time_unit = data.draw(st.sampled_from(("s", "h", "min", "day")))
    seconds = factor_to_seconds(time_unit)
    assert factor_to_m3_per_s(f"m3/{time_unit}") == pytest.approx(
        factor_to_m("m") ** 3 / seconds, rel=1e-12
    )
    assert factor_to_m3_per_s(f"l/{time_unit}") == pytest.approx(1.0e-3 / seconds, rel=1e-12)


@given(code=st.integers(min_value=1, max_value=5), data=st.data())
@UNIT_PROPERTY
def test_modflow_itmuni_codes_round_trip(code: int, data: st.DataObject) -> None:
    """The ITMUNI integer written to the model must read back as the same unit.

    MODFLOW encodes the time unit as an integer 1..5. The mapping is used in
    both directions, when writing a model and when reading a foreign one, so a
    swapped pair would silently reinterpret every stress period length.
    """
    unit = normalize_time_unit(code)
    assert to_modflow_itmuni(unit) == code
    assert normalize_time_unit(to_modflow_itmuni(unit)) == unit
    # Written as an int, a float or a string, an ITMUNI code means the same.
    spelling = data.draw(st.sampled_from((code, float(code), str(code))))
    assert normalize_time_unit(spelling) == unit
