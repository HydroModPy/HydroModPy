"""Unit conversion helpers backed by ``hydromodpy.support.units``.

Supports multiplicative conversions (length, flow, concentration, radiation, ...)
and affine conversions (temperature with offset: K, °F ↔ °C).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from hydromodpy.support.units import (
    canonical_unit_token as _canonical_unit_token,
    factor_to_m,
    factor_to_m3_per_s,
    factor_to_m_per_s,
    factor_to_w_per_m2,
    normalize_length_unit,
    normalize_m3_per_s_unit,
    normalize_m_per_s_unit,
    normalize_radiation_unit,
)


@dataclass(frozen=True)
class _ResolvedUnit:
    family: str
    canonical: str
    factor_to_base: float
    offset_to_base: float = 0.0

    @property
    def has_offset(self) -> bool:
        return self.offset_to_base != 0.0


# ------------------------------------------------------------------
# Resolution via support.units modules (multiplicative families)
# ------------------------------------------------------------------

def _resolve_via_support_units(unit: str) -> _ResolvedUnit | None:
    resolvers: tuple[
        tuple[str, Callable[[str], str], Callable[[str], float]],
        ...,
    ] = (
        ("volumetric_flow", normalize_m3_per_s_unit, factor_to_m3_per_s),
        ("length", normalize_length_unit, factor_to_m),
        ("m_per_s", normalize_m_per_s_unit, factor_to_m_per_s),
        ("radiation", normalize_radiation_unit, factor_to_w_per_m2),
    )
    for family, normalize, factor in resolvers:
        try:
            canonical = normalize(unit)
        except ValueError:
            continue
        return _ResolvedUnit(
            family=family,
            canonical=canonical,
            factor_to_base=float(factor(canonical)),
        )
    return None


# ------------------------------------------------------------------
# Manual families (temperature, percent, concentration, code)
# ------------------------------------------------------------------

# Temperature — affine conversions (offset-based).
# Base: degC (factor=1, offset=0).
_TEMPERATURE_UNITS: dict[str, tuple[str, float, float]] = {
    # token: (canonical, factor_to_base, offset_to_base)
    "degc": ("degC", 1.0, 0.0),
    "°c": ("degC", 1.0, 0.0),
    "c": ("degC", 1.0, 0.0),
    "celsius": ("degC", 1.0, 0.0),
    # Kelvin: value_degC = value_K * 1.0 + (-273.15)
    "k": ("K", 1.0, -273.15),
    "kelvin": ("K", 1.0, -273.15),
    # Fahrenheit: value_degC = value_F * 5/9 + (-160/9)
    "degf": ("degF", 5.0 / 9.0, -160.0 / 9.0),
    "°f": ("degF", 5.0 / 9.0, -160.0 / 9.0),
    "f": ("degF", 5.0 / 9.0, -160.0 / 9.0),
    "fahrenheit": ("degF", 5.0 / 9.0, -160.0 / 9.0),
}

# Percent / fraction — multiplicative.
# Base: % (factor=1).
_PERCENT_UNITS: dict[str, tuple[str, float]] = {
    "%": ("%", 1.0),
    "percent": ("%", 1.0),
    "percentage": ("%", 1.0),
    "pct": ("%", 1.0),
    "fraction": ("fraction", 100.0),
    "0-1": ("fraction", 100.0),
    "ratio": ("fraction", 100.0),
}

# Concentration — multiplicative.
# Base: mg/L (factor=1).
_CONCENTRATION_UNITS: dict[str, tuple[str, float]] = {
    "mg/l": ("mg/L", 1.0),
    "ug/l": ("ug/L", 1.0e-3),
    "µg/l": ("ug/L", 1.0e-3),
    "μg/l": ("ug/L", 1.0e-3),
    "ng/l": ("ng/L", 1.0e-6),
    "g/l": ("g/L", 1000.0),
}

# CF-convention remapping — common NetCDF unit strings.
_CF_REMAP: dict[str, str] = {
    "kgm-2s-1": "mm/s",       # precipitation mass flux → mm/s
    "kg.m-2.s-1": "mm/s",
    "kg/m2/s": "mm/s",
    "kg/m^2/s": "mm/s",
    "kg/m²/s": "mm/s",
    "kgkg-1": "fraction",     # specific humidity
    "kg/kg": "fraction",
}


def _resolve_manual_unit(unit: str) -> _ResolvedUnit | None:
    token = _canonical_unit_token(unit)

    # Temperature (affine)
    temp = _TEMPERATURE_UNITS.get(token)
    if temp is not None:
        canonical, factor, offset = temp
        return _ResolvedUnit("temperature", canonical, factor, offset)

    # Percent (multiplicative)
    pct = _PERCENT_UNITS.get(token)
    if pct is not None:
        canonical, factor = pct
        return _ResolvedUnit("percent", canonical, factor)

    # Concentration (multiplicative)
    conc = _CONCENTRATION_UNITS.get(token)
    if conc is not None:
        canonical, factor = conc
        return _ResolvedUnit("concentration", canonical, factor)

    # Code (intermittency — identity)
    if token == "code":
        return _ResolvedUnit("code", "code", 1.0)

    return None


# ------------------------------------------------------------------
# Main resolution chain
# ------------------------------------------------------------------

def _resolve_unit(unit: str) -> _ResolvedUnit:
    resolved = _resolve_via_support_units(unit)
    if resolved is not None:
        return resolved

    resolved = _resolve_manual_unit(unit)
    if resolved is not None:
        return resolved

    # CF-convention remap: try remapping then resolve again.
    remapped = _CF_REMAP.get(_canonical_unit_token(unit))
    if remapped is not None:
        resolved = _resolve_via_support_units(remapped) or _resolve_manual_unit(remapped)
        if resolved is not None:
            return resolved

    raise ValueError(f"Unknown unit: '{unit}'")


# ------------------------------------------------------------------
# Public API
# ------------------------------------------------------------------

def convert_value(value: float, from_unit: str, to_unit: str) -> float:
    """Convert a scalar value between compatible units.

    Supports affine conversions (temperature K/°F ↔ °C).
    """
    if from_unit == to_unit:
        return value

    source = _resolve_unit(from_unit)
    target = _resolve_unit(to_unit)

    if source.family != target.family:
        raise ValueError(f"Incompatible units: '{from_unit}' ({source.family}) -> '{to_unit}' ({target.family})")

    # Affine: value_base = value * factor + offset
    base_value = value * source.factor_to_base + source.offset_to_base
    return (base_value - target.offset_to_base) / target.factor_to_base


def convert_array(data, from_unit: str, to_unit: str):
    """Convert array-like data (numpy, pandas, xarray) between compatible units.

    Supports affine conversions (temperature K/°F ↔ °C).
    Returns the same type as input.
    """
    if from_unit == to_unit:
        return data

    source = _resolve_unit(from_unit)
    target = _resolve_unit(to_unit)

    if source.family != target.family:
        raise ValueError(f"Incompatible units: '{from_unit}' ({source.family}) -> '{to_unit}' ({target.family})")

    result = data * source.factor_to_base + source.offset_to_base
    if target.offset_to_base != 0.0 or target.factor_to_base != 1.0:
        result = (result - target.offset_to_base) / target.factor_to_base
    return result


def get_conversion_factor(from_unit: str, to_unit: str) -> float:
    """Return a multiplicative conversion factor between compatible units.

    Raises TypeError for unit pairs that require offset conversion (e.g. K → °C).
    Use ``convert_value`` or ``convert_array`` for those.
    """
    if from_unit == to_unit:
        return 1.0

    source = _resolve_unit(from_unit)
    target = _resolve_unit(to_unit)

    if source.family != target.family:
        raise ValueError(f"Incompatible units: '{from_unit}' ({source.family}) -> '{to_unit}' ({target.family})")

    if source.has_offset or target.has_offset:
        raise TypeError(
            f"Conversion '{from_unit}' -> '{to_unit}' requires offset "
            f"(not purely multiplicative). Use convert_value() or convert_array()."
        )

    return source.factor_to_base / target.factor_to_base
