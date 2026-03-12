"""Hydraulic-conductivity unit helpers centered on SI (m/s)."""

from __future__ import annotations

from numbers import Real

from hydromodpy.support.units.scalar import parse_scalar_and_unit


M_PER_S_CANONICAL_UNITS: tuple[str, ...] = (
    "m/s",
    "m/day",
    "m/h",
    "cm/s",
    "cm/day",
    "cm/h",
    "mm/s",
    "mm/day",
    "mm/h",
)

_M_PER_S_UNIT_ALIASES: dict[str, str] = {
    "m/s": "m/s",
    "m.s-1": "m/s",
    "m*s-1": "m/s",
    "m*s^-1": "m/s",
    "meter/second": "m/s",
    "meters/second": "m/s",
    "metre/second": "m/s",
    "metres/second": "m/s",
    "m/day": "m/day",
    "m/d": "m/day",
    "meter/day": "m/day",
    "meters/day": "m/day",
    "metre/day": "m/day",
    "metres/day": "m/day",
    "m/h": "m/h",
    "m/hr": "m/h",
    "m/hour": "m/h",
    "meter/hour": "m/h",
    "meters/hour": "m/h",
    "metre/hour": "m/h",
    "metres/hour": "m/h",
    "cm/s": "cm/s",
    "cm.s-1": "cm/s",
    "cm*s-1": "cm/s",
    "cm*s^-1": "cm/s",
    "centimeter/second": "cm/s",
    "centimeters/second": "cm/s",
    "centimetre/second": "cm/s",
    "centimetres/second": "cm/s",
    "cm/day": "cm/day",
    "cm/d": "cm/day",
    "centimeter/day": "cm/day",
    "centimeters/day": "cm/day",
    "centimetre/day": "cm/day",
    "centimetres/day": "cm/day",
    "cm/h": "cm/h",
    "cm/hr": "cm/h",
    "cm/hour": "cm/h",
    "centimeter/hour": "cm/h",
    "centimeters/hour": "cm/h",
    "centimetre/hour": "cm/h",
    "centimetres/hour": "cm/h",
    "mm/s": "mm/s",
    "mm.s-1": "mm/s",
    "mm*s-1": "mm/s",
    "mm*s^-1": "mm/s",
    "millimeter/second": "mm/s",
    "millimeters/second": "mm/s",
    "millimetre/second": "mm/s",
    "millimetres/second": "mm/s",
    "mm/day": "mm/day",
    "mm/d": "mm/day",
    "millimeter/day": "mm/day",
    "millimeters/day": "mm/day",
    "millimetre/day": "mm/day",
    "millimetres/day": "mm/day",
    "mm/h": "mm/h",
    "mm/hr": "mm/h",
    "mm/hour": "mm/h",
    "millimeter/hour": "mm/h",
    "millimeters/hour": "mm/h",
    "millimetre/hour": "mm/h",
    "millimetres/hour": "mm/h",
}

_M_PER_S_FACTORS: dict[str, float] = {
    "m/s": 1.0,
    "m/day": 1.0 / 86400.0,
    "m/h": 1.0 / 3600.0,
    "cm/s": 1.0e-2,
    "cm/day": 1.0e-2 / 86400.0,
    "cm/h": 1.0e-2 / 3600.0,
    "mm/s": 1.0e-3,
    "mm/day": 1.0e-3 / 86400.0,
    "mm/h": 1.0e-3 / 3600.0,
}


def _canonical_unit_token(unit: str) -> str:
    return "".join(str(unit).strip().lower().split())


def normalize_m_per_s_unit(unit: str) -> str:
    """Normalize one hydraulic-conductivity unit token to a canonical form."""
    token = _canonical_unit_token(unit)
    if token == "":
        raise ValueError("Hydraulic-conductivity unit cannot be empty.")
    canonical = _M_PER_S_UNIT_ALIASES.get(token)
    if canonical is None:
        allowed = ", ".join(M_PER_S_CANONICAL_UNITS)
        raise ValueError(
            f"Unsupported hydraulic-conductivity unit '{unit}'. Allowed units: {allowed}"
        )
    return canonical


def factor_to_m_per_s(unit: str) -> float:
    """Return multiplicative factor to convert one unit to ``m/s``."""
    canonical = normalize_m_per_s_unit(unit)
    return float(_M_PER_S_FACTORS[canonical])


def convert_to_m_per_s(
    value: object,
    *,
    unit: str,
    label: str = "value",
) -> float:
    """Convert one numeric value from ``unit`` to ``m/s``."""
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{label} must be numeric to convert to m/s.")
    return float(value) * factor_to_m_per_s(unit)


def parse_to_m_per_s(
    value: object,
    *,
    location: str,
    default_unit: str = "m/s",
    explicit_unit: str | None = None,
) -> tuple[float, str]:
    """Parse scalar + unit payload and convert to ``m/s``.

    Returns
    -------
    tuple[float, str]
        ``(value_m_per_s, canonical_input_unit)``.
    """
    scalar, resolved_unit = parse_scalar_and_unit(
        value,
        location=location,
        default_unit=default_unit,
        explicit_unit=explicit_unit,
    )
    canonical_unit = normalize_m_per_s_unit(resolved_unit)
    return float(scalar) * _M_PER_S_FACTORS[canonical_unit], canonical_unit
