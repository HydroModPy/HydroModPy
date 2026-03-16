"""Hydraulic-conductance unit helpers centered on SI (m2/s)."""

from __future__ import annotations

from numbers import Real

from hydromodpy.support.units.scalar import parse_scalar_and_unit


M2_PER_S_CANONICAL_UNITS: tuple[str, ...] = (
    "m2/s",
    "m2/day",
    "m2/h",
    "cm2/s",
    "cm2/day",
    "cm2/h",
    "mm2/s",
    "mm2/day",
    "mm2/h",
)

_M2_PER_S_UNIT_ALIASES: dict[str, str] = {
    "m2/s": "m2/s",
    "m^2/s": "m2/s",
    "m2.s-1": "m2/s",
    "m2*s-1": "m2/s",
    "m2*s^-1": "m2/s",
    "m2/day": "m2/day",
    "m2/d": "m2/day",
    "m^2/day": "m2/day",
    "m2/h": "m2/h",
    "m2/hr": "m2/h",
    "m2/hour": "m2/h",
    "m^2/h": "m2/h",
    "cm2/s": "cm2/s",
    "cm^2/s": "cm2/s",
    "cm2.s-1": "cm2/s",
    "cm2*s-1": "cm2/s",
    "cm2*s^-1": "cm2/s",
    "cm2/day": "cm2/day",
    "cm2/d": "cm2/day",
    "cm^2/day": "cm2/day",
    "cm2/h": "cm2/h",
    "cm2/hr": "cm2/h",
    "cm2/hour": "cm2/h",
    "cm^2/h": "cm2/h",
    "mm2/s": "mm2/s",
    "mm^2/s": "mm2/s",
    "mm2.s-1": "mm2/s",
    "mm2*s-1": "mm2/s",
    "mm2*s^-1": "mm2/s",
    "mm2/day": "mm2/day",
    "mm2/d": "mm2/day",
    "mm^2/day": "mm2/day",
    "mm2/h": "mm2/h",
    "mm2/hr": "mm2/h",
    "mm2/hour": "mm2/h",
    "mm^2/h": "mm2/h",
}

_M2_PER_S_FACTORS: dict[str, float] = {
    "m2/s": 1.0,
    "m2/day": 1.0 / 86400.0,
    "m2/h": 1.0 / 3600.0,
    "cm2/s": 1.0e-4,
    "cm2/day": 1.0e-4 / 86400.0,
    "cm2/h": 1.0e-4 / 3600.0,
    "mm2/s": 1.0e-6,
    "mm2/day": 1.0e-6 / 86400.0,
    "mm2/h": 1.0e-6 / 3600.0,
}


def _canonical_unit_token(unit: str) -> str:
    return "".join(str(unit).strip().lower().split())


def normalize_m2_per_s_unit(unit: str) -> str:
    """Normalize one hydraulic-conductance unit token to a canonical form."""
    token = _canonical_unit_token(unit)
    if token == "":
        raise ValueError("Hydraulic-conductance unit cannot be empty.")
    canonical = _M2_PER_S_UNIT_ALIASES.get(token)
    if canonical is None:
        allowed = ", ".join(M2_PER_S_CANONICAL_UNITS)
        raise ValueError(
            f"Unsupported hydraulic-conductance unit '{unit}'. Allowed units: {allowed}"
        )
    return canonical


def factor_to_m2_per_s(unit: str) -> float:
    """Return multiplicative factor to convert one unit to ``m2/s``."""
    canonical = normalize_m2_per_s_unit(unit)
    return float(_M2_PER_S_FACTORS[canonical])


def convert_to_m2_per_s(
    value: object,
    *,
    unit: str,
    label: str = "value",
) -> float:
    """Convert one numeric value from ``unit`` to ``m2/s``."""
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{label} must be numeric to convert to m2/s.")
    return float(value) * factor_to_m2_per_s(unit)


def parse_to_m2_per_s(
    value: object,
    *,
    location: str,
    default_unit: str = "m2/s",
    explicit_unit: str | None = None,
) -> tuple[float, str]:
    """Parse scalar + unit payload and convert to ``m2/s``."""
    scalar, resolved_unit = parse_scalar_and_unit(
        value,
        location=location,
        default_unit=default_unit,
        explicit_unit=explicit_unit,
    )
    canonical_unit = normalize_m2_per_s_unit(resolved_unit)
    return float(scalar) * _M2_PER_S_FACTORS[canonical_unit], canonical_unit
