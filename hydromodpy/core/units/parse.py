"""Pint-based helpers to parse TOML-style unit payloads.

The normalizers that live alongside flow configs receive raw user input such as
``12.5``, ``"12.5 m"`` or ``"12.5"`` paired with an explicit ``unit=`` field.
This module converts them into a canonical magnitude using the shared
:data:`hydromodpy.core.units.UREG`, so that call sites stop depending on the
per-quantity factor tables (``parse_to_m`` / ``parse_to_m2_per_s`` / ...).
"""

from __future__ import annotations

import re

import pint

from hydromodpy.core.units.registry import UREG
from hydromodpy.core.units.scalar import parse_scalar_and_unit


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
    ``canonical_unit``. The ``length_label`` argument, when provided, is used
    to shape the "Unsupported <label> unit" error expected by legacy call
    sites (for example ``length_label="length"`` reproduces the historical
    ``"Unsupported length unit 'furlong'"`` message).
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
    # :func:`registry.get_registry`). ``{!s}`` honours that format.
    return f"{pint_unit}"


__all__ = [
    "canonical_unit_short_form",
    "check_unit_compatible",
    "parse_to_canonical_magnitude",
]
