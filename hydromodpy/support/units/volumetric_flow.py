"""Volumetric-flow unit helpers centered on SI (m3/s)."""

from __future__ import annotations

from numbers import Real

from hydromodpy.support.units.scalar import canonical_unit_token as _canonical_unit_token, parse_scalar_and_unit


M3_PER_S_CANONICAL_UNITS: tuple[str, ...] = (
    "m3/s",
    "m3/day",
    "m3/h",
    "m3/min",
    "l/s",
    "l/day",
    "l/h",
    "l/min",
)


_M3_PER_S_UNIT_ALIASES: dict[str, str] = {
    "m3/s": "m3/s",
    "m^3/s": "m3/s",
    "m3.s-1": "m3/s",
    "m3*s-1": "m3/s",
    "m3*s^-1": "m3/s",
    "m3/day": "m3/day",
    "m3/d": "m3/day",
    "m^3/day": "m3/day",
    "m3/h": "m3/h",
    "m3/hr": "m3/h",
    "m3/hour": "m3/h",
    "m^3/h": "m3/h",
    "m3/min": "m3/min",
    "m3/mn": "m3/min",
    "m^3/min": "m3/min",
    "l/s": "l/s",
    "liter/s": "l/s",
    "liters/s": "l/s",
    "litre/s": "l/s",
    "litres/s": "l/s",
    "l/day": "l/day",
    "l/d": "l/day",
    "l/h": "l/h",
    "l/hr": "l/h",
    "l/hour": "l/h",
    "l/min": "l/min",
}


_M3_PER_S_FACTORS: dict[str, float] = {
    "m3/s": 1.0,
    "m3/day": 1.0 / 86400.0,
    "m3/h": 1.0 / 3600.0,
    "m3/min": 1.0 / 60.0,
    "l/s": 1.0e-3,
    "l/day": 1.0e-3 / 86400.0,
    "l/h": 1.0e-3 / 3600.0,
    "l/min": 1.0e-3 / 60.0,
}


def normalize_m3_per_s_unit(unit: str) -> str:
    """Normalize one volumetric-flow unit token to a canonical form."""
    token = _canonical_unit_token(unit)
    if token == "":
        raise ValueError("Volumetric-flow unit cannot be empty.")
    canonical = _M3_PER_S_UNIT_ALIASES.get(token)
    if canonical is None:
        allowed = ", ".join(M3_PER_S_CANONICAL_UNITS)
        raise ValueError(
            f"Unsupported volumetric-flow unit '{unit}'. Allowed units: {allowed}"
        )
    return canonical


def factor_to_m3_per_s(unit: str) -> float:
    """Return multiplicative factor to convert one unit to ``m3/s``."""
    canonical = normalize_m3_per_s_unit(unit)
    return float(_M3_PER_S_FACTORS[canonical])


def convert_to_m3_per_s(
    value: object,
    *,
    unit: str,
    label: str = "value",
) -> float:
    """Convert one numeric value from ``unit`` to ``m3/s``."""
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{label} must be numeric to convert to m3/s.")
    return float(value) * factor_to_m3_per_s(unit)


def parse_to_m3_per_s(
    value: object,
    *,
    location: str,
    default_unit: str = "m3/s",
    explicit_unit: str | None = None,
) -> tuple[float, str]:
    """Parse scalar + unit payload and convert to ``m3/s``.

    Returns
    -------
    tuple[float, str]
        ``(value_m3_per_s, canonical_input_unit)``.
    """
    scalar, resolved_unit = parse_scalar_and_unit(
        value,
        location=location,
        default_unit=default_unit,
        explicit_unit=explicit_unit,
    )
    canonical_unit = normalize_m3_per_s_unit(resolved_unit)
    return float(scalar) * _M3_PER_S_FACTORS[canonical_unit], canonical_unit
