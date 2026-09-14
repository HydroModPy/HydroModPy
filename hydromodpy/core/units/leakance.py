"""Leakance unit helpers centered on SI (1/s).

A leakance is an inverse time (``1/T``): the lake-bed leakance ``bedleak`` =
``K_bed / thickness_bed`` controls the lake-aquifer head-dependent exchange in
the MF6 LAK package. HMP runs MF6 in seconds, so leakances must reach the solver
in ``1/s``; this helper converts legacy ``1/day`` / ``1/h`` declarations.
"""

from __future__ import annotations

from numbers import Real

from hydromodpy.core.units.scalar import (
    canonical_unit_token as _canonical_unit_token,
)
from hydromodpy.core.units.scalar import (
    parse_scalar_and_unit,
)

PER_S_CANONICAL_UNITS: tuple[str, ...] = (
    "1/s",
    "1/day",
    "1/h",
    "1/min",
)


_PER_S_UNIT_ALIASES: dict[str, str] = {
    "1/s": "1/s",
    "s-1": "1/s",
    "s^-1": "1/s",
    "1/sec": "1/s",
    "1/second": "1/s",
    "1/day": "1/day",
    "1/d": "1/day",
    "day-1": "1/day",
    "d-1": "1/day",
    "1/h": "1/h",
    "1/hr": "1/h",
    "1/hour": "1/h",
    "h-1": "1/h",
    "1/min": "1/min",
    "1/mn": "1/min",
    "min-1": "1/min",
}


_PER_S_FACTORS: dict[str, float] = {
    "1/s": 1.0,
    "1/day": 1.0 / 86400.0,
    "1/h": 1.0 / 3600.0,
    "1/min": 1.0 / 60.0,
}


def normalize_per_s_unit(unit: str) -> str:
    """Normalize one leakance (1/T) unit token to a canonical form."""
    token = _canonical_unit_token(unit)
    if token == "":
        raise ValueError("Leakance unit cannot be empty.")
    canonical = _PER_S_UNIT_ALIASES.get(token)
    if canonical is None:
        allowed = ", ".join(PER_S_CANONICAL_UNITS)
        raise ValueError(f"Unsupported leakance unit '{unit}'. Allowed units: {allowed}")
    return canonical


def factor_to_per_s(unit: str) -> float:
    """Return multiplicative factor to convert one unit to ``1/s``."""
    canonical = normalize_per_s_unit(unit)
    return float(_PER_S_FACTORS[canonical])


def convert_to_per_s(
    value: object,
    *,
    unit: str,
    label: str = "value",
) -> float:
    """Convert one numeric value from ``unit`` to ``1/s``."""
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{label} must be numeric to convert to 1/s.")
    return float(value) * factor_to_per_s(unit)


def parse_to_per_s(
    value: object,
    *,
    location: str,
    default_unit: str = "1/s",
    explicit_unit: str | None = None,
) -> tuple[float, str]:
    """Parse scalar + unit payload and convert to ``1/s``.

    Returns
    -------
    tuple[float, str]
        ``(value_per_s, canonical_input_unit)``.
    """
    scalar, resolved_unit = parse_scalar_and_unit(
        value,
        location=location,
        default_unit=default_unit,
        explicit_unit=explicit_unit,
    )
    canonical_unit = normalize_per_s_unit(resolved_unit)
    return float(scalar) * _PER_S_FACTORS[canonical_unit], canonical_unit
