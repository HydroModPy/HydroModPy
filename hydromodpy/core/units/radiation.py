"""Radiation flux unit helpers centered on SI (W/m2)."""

from __future__ import annotations

from numbers import Real

from hydromodpy.core.units.scalar import canonical_unit_token as _canonical_unit_token


RADIATION_CANONICAL_UNITS: tuple[str, ...] = (
    "W/m2",
    "MJ/m2/day",
    "J/m2/s",
    "kWh/m2/day",
    "J/cm2/day",
    "cal/cm2/day",
)

_RADIATION_UNIT_ALIASES: dict[str, str] = {
    # SI
    "w/m2": "W/m2",
    "w/m^2": "W/m2",
    "w/m²": "W/m2",
    "w.m-2": "W/m2",
    "w*m-2": "W/m2",
    "wm-2": "W/m2",
    "watt/m2": "W/m2",
    "j/m2/s": "J/m2/s",
    "j/m^2/s": "J/m2/s",
    "j/m²/s": "J/m2/s",
    # MJ/m2/day  (common hydrology unit, SIM2 internal)
    "mj/m2/day": "MJ/m2/day",
    "mj/m2/d": "MJ/m2/day",
    "mj/m2/j": "MJ/m2/day",
    "mj/m^2/day": "MJ/m2/day",
    "mj/m^2/d": "MJ/m2/day",
    "mj/m^2/j": "MJ/m2/day",
    "mj/m²/day": "MJ/m2/day",
    "mj/m²/d": "MJ/m2/day",
    "mj/m²/j": "MJ/m2/day",
    "mjm-2d-1": "MJ/m2/day",
    "mjm-2day-1": "MJ/m2/day",
    # kWh/m2/day
    "kwh/m2/day": "kWh/m2/day",
    "kwh/m2/d": "kWh/m2/day",
    "kwh/m^2/day": "kWh/m2/day",
    "kwh/m²/day": "kWh/m2/day",
    # J/cm2/day  (SIM2 native cumulative)
    "j/cm2/day": "J/cm2/day",
    "j/cm2/d": "J/cm2/day",
    "j/cm2/j": "J/cm2/day",
    "j/cm^2/day": "J/cm2/day",
    "j/cm²/day": "J/cm2/day",
    "j/cm²/d": "J/cm2/day",
    "j/cm²/j": "J/cm2/day",
    # cal/cm2/day  (Langley/day)
    "cal/cm2/day": "cal/cm2/day",
    "cal/cm2/d": "cal/cm2/day",
    "langley/day": "cal/cm2/day",
    "ly/day": "cal/cm2/day",
    "ly/d": "cal/cm2/day",
}

# Factors to convert TO W/m2 (base SI).
# 1 W/m2 = 1 J/m2/s
# 1 MJ/m2/day = 1e6 J / 86400 s / m2 = 11.5741 W/m2
# 1 kWh/m2/day = 3.6e6 J / 86400 s / m2 = 41.6667 W/m2
# 1 J/cm2/day = 1e4 J/m2 / 86400 s = 0.115741 W/m2
# 1 cal/cm2/day = 4.184 J/cm2/day = 4.184e4 J/m2 / 86400 s = 0.484259 W/m2
_RADIATION_FACTORS: dict[str, float] = {
    "W/m2": 1.0,
    "J/m2/s": 1.0,
    "MJ/m2/day": 1.0e6 / 86400.0,
    "kWh/m2/day": 3.6e6 / 86400.0,
    "J/cm2/day": 1.0e4 / 86400.0,
    "cal/cm2/day": 4.184e4 / 86400.0,
}


def normalize_radiation_unit(unit: str) -> str:
    """Normalize one radiation flux unit token to a canonical form."""
    token = _canonical_unit_token(unit)
    if token == "":
        raise ValueError("Radiation unit cannot be empty.")
    canonical = _RADIATION_UNIT_ALIASES.get(token)
    if canonical is None:
        allowed = ", ".join(RADIATION_CANONICAL_UNITS)
        raise ValueError(
            f"Unsupported radiation unit '{unit}'. Allowed units: {allowed}"
        )
    return canonical


def factor_to_w_per_m2(unit: str) -> float:
    """Return multiplicative factor to convert one unit to ``W/m2``."""
    canonical = normalize_radiation_unit(unit)
    return float(_RADIATION_FACTORS[canonical])


def convert_to_w_per_m2(
    value: object,
    *,
    unit: str,
    label: str = "value",
) -> float:
    """Convert one numeric value from ``unit`` to ``W/m2``."""
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{label} must be numeric to convert to W/m2.")
    return float(value) * factor_to_w_per_m2(unit)
