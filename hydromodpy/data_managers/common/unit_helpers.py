"""Unit conversion helpers backed by ``hydromodpy.support.units``."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from hydromodpy.support.units import (
    factor_to_m,
    factor_to_m3_per_s,
    factor_to_m_per_s,
    normalize_length_unit,
    normalize_m3_per_s_unit,
    normalize_m_per_s_unit,
)


@dataclass(frozen=True)
class _ResolvedUnit:
    family: str
    canonical: str
    factor_to_base: float


def _canonical_unit_token(unit: str) -> str:
    return "".join(str(unit).strip().lower().split())


def _resolve_via_support_units(unit: str) -> _ResolvedUnit | None:
    resolvers: tuple[
        tuple[str, Callable[[str], str], Callable[[str], float]],
        ...,
    ] = (
        ("volumetric_flow", normalize_m3_per_s_unit, factor_to_m3_per_s),
        ("length", normalize_length_unit, factor_to_m),
        ("m_per_s", normalize_m_per_s_unit, factor_to_m_per_s),
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


def _resolve_manual_unit(unit: str) -> _ResolvedUnit | None:
    token = _canonical_unit_token(unit)

    temperature_aliases = {
        "degc": "degC",
        "°c": "degC",
        "c": "degC",
        "celsius": "degC",
    }
    canonical = temperature_aliases.get(token)
    if canonical is not None:
        return _ResolvedUnit("temperature", canonical, 1.0)

    percent_aliases = {
        "%": "%",
        "percent": "%",
        "percentage": "%",
        "pct": "%",
    }
    canonical = percent_aliases.get(token)
    if canonical is not None:
        return _ResolvedUnit("percent", canonical, 1.0)

    radiation_aliases = {
        "mj/m2/j": "MJ/m2/j",
        "mj/m2/d": "MJ/m2/j",
        "mj/m2/day": "MJ/m2/j",
        "mj/m^2/j": "MJ/m2/j",
        "mj/m^2/d": "MJ/m2/j",
        "mj/m^2/day": "MJ/m2/j",
        "mj/m²/j": "MJ/m2/j",
        "mj/m²/d": "MJ/m2/j",
        "mj/m²/day": "MJ/m2/j",
    }
    canonical = radiation_aliases.get(token)
    if canonical is not None:
        return _ResolvedUnit("radiation", canonical, 1.0)

    concentration_factors = {
        "mg/l": ("mg/L", 1.0),
        "ug/l": ("ug/L", 1.0e-3),
        "µg/l": ("ug/L", 1.0e-3),
        "μg/l": ("ug/L", 1.0e-3),
    }
    concentration = concentration_factors.get(token)
    if concentration is not None:
        canonical, factor_to_base = concentration
        return _ResolvedUnit("concentration", canonical, factor_to_base)

    if token == "code":
        return _ResolvedUnit("code", "code", 1.0)

    return None


def _resolve_unit(unit: str) -> _ResolvedUnit:
    resolved = _resolve_via_support_units(unit)
    if resolved is not None:
        return resolved

    resolved = _resolve_manual_unit(unit)
    if resolved is not None:
        return resolved

    raise ValueError(f"Unknown unit conversion: '{unit}'")


def convert_value(value: float, from_unit: str, to_unit: str) -> float:
    """Convert a value between known units."""
    return value * get_conversion_factor(from_unit, to_unit)


def get_conversion_factor(from_unit: str, to_unit: str) -> float:
    """Return a multiplicative conversion factor between compatible units."""
    if from_unit == to_unit:
        return 1.0

    source = _resolve_unit(from_unit)
    target = _resolve_unit(to_unit)

    if source.family != target.family:
        raise ValueError(f"Unknown unit conversion: '{from_unit}' -> '{to_unit}'")

    return source.factor_to_base / target.factor_to_base
