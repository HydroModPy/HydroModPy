"""Pint-based helpers to parse TOML-style unit payloads.

The normalizers that live alongside flow configs receive raw user input such as
``12.5``, ``"12.5 m"`` or ``"12.5"`` paired with an explicit ``unit=`` field.
This module converts them into a canonical magnitude using the shared
:data:`hydromodpy.core.units.registry.UREG`, so that call sites stop depending on the
per-quantity factor tables (``parse_to_m`` / ``parse_to_m2_per_s`` / ...).
"""

from __future__ import annotations

import re

import pint

from hydromodpy.core.units.quantities import factor_to_si
from hydromodpy.core.units.registry import UREG
from hydromodpy.core.units.scalar import canonical_unit_token, parse_scalar_and_unit

_POWER_SHORTHAND_RE = re.compile(r"(?P<base>[A-Za-z]+)(?P<power>[2-9])(?![A-Za-z0-9])")


def _to_pint_syntax(unit: str) -> str:
    """Rewrite common shorthand unit tokens into pint-friendly syntax.

    Accepts ``m2/s`` / ``cm3.s-1`` / ``m^2/s`` and returns ``m**2/s`` /
    ``cm**3*s**-1`` / ``m**2/s`` respectively. The shared :data:`UREG` then
    parses the result without bespoke alias tables.
    """
    token = str(unit).strip()
    if token == "":
        return token
    # Normalize inline exponents: ``m^2`` -> ``m**2``.
    token = token.replace("^", "**")
    # Normalize unit-exponent shorthand: ``m2/s`` -> ``m**2/s`` (only when the
    # digit directly follows a unit letter and is not part of a number literal).
    token = _POWER_SHORTHAND_RE.sub(
        lambda match: f"{match.group('base')}**{match.group('power')}",
        token,
    )
    # Normalize inline multiplication: ``m2.s-1`` -> ``m**2*s-1``.
    token = token.replace(".", "*")
    return token


def parse_to_canonical_magnitude(
    value: object,
    *,
    location: str,
    canonical_unit: str,
    explicit_unit: str | None = None,
    length_label: str | None = None,
) -> float:
    """Parse one scalar + unit payload into a float magnitude in ``canonical_unit``.

    Uses the shared pint registry to enforce dimensional compatibility with
    ``canonical_unit``. The ``length_label`` argument, when provided, shapes
    the "Unsupported <label> unit" error message (for example
    ``length_label="length"`` produces ``"Unsupported length unit 'furlong'"``).
    """
    scalar, resolved_unit = parse_scalar_and_unit(
        value,
        location=location,
        default_unit=canonical_unit,
        explicit_unit=explicit_unit,
    )
    try:
        quantity = scalar * UREG.Unit(_to_pint_syntax(resolved_unit))
        return float(quantity.to(canonical_unit).magnitude)
    except (pint.UndefinedUnitError, AttributeError) as exc:
        if length_label:
            raise ValueError(f"Unsupported {length_label} unit '{resolved_unit}'.") from exc
        raise ValueError(f"{location}: unit '{resolved_unit}' is not recognized.") from exc
    except pint.DimensionalityError as exc:
        if length_label:
            raise ValueError(f"Unsupported {length_label} unit '{resolved_unit}'.") from exc
        raise ValueError(
            f"{location}: unit '{resolved_unit}' is not compatible with '{canonical_unit}'."
        ) from exc


def check_unit_compatible(
    unit: str,
    *,
    canonical_unit: str,
    label: str,
) -> str:
    """Validate that ``unit`` is convertible to ``canonical_unit``.

    Returns the canonical unit token on success. Raises ``ValueError`` with a
    ``"Unsupported <label> unit"`` message if the unit is not recognized or
    dimensionally incompatible.
    """
    token = str(unit).strip()
    if token == "":
        raise ValueError(f"{label} unit cannot be empty.")
    try:
        quantity = 1.0 * UREG.Unit(_to_pint_syntax(token))
        quantity.to(canonical_unit)
    except (pint.UndefinedUnitError, pint.DimensionalityError, AttributeError) as exc:
        raise ValueError(f"Unsupported {label} unit '{unit}'.") from exc
    return canonical_unit


def canonical_unit_short_form(
    unit: str,
    *,
    canonical_unit: str,
    label: str,
) -> str:
    """Return the pint short-form alias of ``unit`` (e.g. "centimeter" -> "cm").

    Confirms that ``unit`` is dimensionally compatible with ``canonical_unit``
    before returning the short token, so the caller can use it as the
    runtime-facing unit string without maintaining a bespoke alias table.
    """
    token = str(unit).strip()
    if token == "":
        raise ValueError(f"{label} unit cannot be empty.")
    try:
        pint_unit = UREG.Unit(_to_pint_syntax(token))
        # Confirm dimensional compatibility with the canonical target.
        (1.0 * pint_unit).to(canonical_unit)
    except (pint.UndefinedUnitError, pint.DimensionalityError, AttributeError) as exc:
        raise ValueError(f"Unsupported {label} unit '{unit}'.") from exc
    # ``~P`` (pretty, short) is the registry's default format (see
    # :func:`registry.get_registry`). ``{!s}`` honors that format.
    return f"{pint_unit}"


_DIMENSIONLESS_TOKENS: frozenset[str] = frozenset({"", "-", "1", "dimensionless"})

_EXPONENT_SHORTHAND_RE = re.compile(r"(?P<base>[A-Za-z]+)-(?P<power>[1-9])(?![A-Za-z0-9])")


def convert_between_units(value: float, *, from_unit: str, to_unit: str) -> float:
    """Return ``value`` written in ``from_unit`` expressed in ``to_unit``.

    Two spellings of one unit give the value back unchanged. Otherwise the
    shared registry converts, and a unit of another dimension, or one it does
    not know, raises ``ValueError`` naming both units.
    """
    source, target = canonical_unit_token(from_unit), canonical_unit_token(to_unit)
    if source == target:
        return float(value)
    if source in _DIMENSIONLESS_TOKENS and target in _DIMENSIONLESS_TOKENS:
        return float(value)
    by_family = _convert_within_a_family(float(value), from_unit, to_unit)
    if by_family is not None:
        return by_family
    try:
        quantity = float(value) * UREG.Unit(_pint_token(from_unit))
        return float(quantity.to(UREG.Unit(_pint_token(to_unit))).magnitude)
    except pint.DimensionalityError as exc:
        raise ValueError(
            f"unit {from_unit!r} does not convert to {to_unit!r}: they measure "
            "different quantities."
        ) from exc
    except (pint.UndefinedUnitError, AssertionError, AttributeError, TypeError) as exc:
        raise ValueError(
            f"unit {from_unit!r} cannot be read, so it does not convert to {to_unit!r}."
        ) from exc


def _convert_within_a_family(value: float, from_unit: str, to_unit: str) -> float | None:
    """Convert through the alias table both units belong to, or return None.

    The tables know spellings pint does not read, such as ``1/mn`` or ``m3s-1``.
    """
    for quantity in (
        "hydraulic_conductivity",
        "leakance",
        "length",
        "volumetric_flow",
        "hydraulic_conductance",
    ):
        try:
            return value * factor_to_si(quantity, from_unit) / factor_to_si(quantity, to_unit)
        except (ValueError, KeyError):
            # Not this family: the next table, then pint, decide.
            continue
    return None


def _pint_token(unit: str) -> str:
    """Rewrite ``unit`` for pint, including the ``s-1`` and ``m-1`` exponent shorthand."""
    token = _EXPONENT_SHORTHAND_RE.sub(
        lambda match: f"{match.group('base')}**-{match.group('power')}", str(unit).strip()
    )
    return _to_pint_syntax(token)


__all__ = [
    "canonical_unit_short_form",
    "check_unit_compatible",
    "convert_between_units",
    "parse_to_canonical_magnitude",
]
