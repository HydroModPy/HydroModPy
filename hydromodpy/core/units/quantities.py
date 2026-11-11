"""Unit tables and conversions to SI for the quantities read from user input.

Each quantity has one table row per accepted unit, written as
``unit: (factor to SI, "alias alias ...")``. Aliases are matched after the
unit text is lower-cased and stripped of spaces, and the unit itself is always
an alias of itself. The generic functions take the quantity name first. The
named functions at the bottom (``factor_to_m``, ``parse_to_m3_per_s``, ...) fix
that first argument and are the public API.

This module does not import pint, so the common path stays light.

``SECONDS_PER_DAY`` lives here. ``time.py`` keeps what only time has: the MODFLOW ITMUNI
codes, the pandas ``Timedelta`` alias, ``timedelta_to_seconds`` and the CF time axis. A
new unit of an existing quantity is one row of ``QUANTITIES``, and its factor is written
again in the table of ``tests/unit/core/units/test_quantities.py``, which the property
tests also compare with pint. A new quantity is one entry of ``QUANTITIES`` and its
named functions at the bottom of this module.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import partial
from numbers import Real

import numpy as np

from hydromodpy.core.units.scalar import canonical_unit_token, parse_scalar_and_unit

SECONDS_PER_DAY = 86400.0
_MIN, _H, _DAY = 60.0, 3600.0, SECONDS_PER_DAY

# quantity: (label, text after "convert to" in errors, {unit: (factor, aliases)})
QUANTITIES: dict[str, tuple[str, str, dict[str, tuple[float, str]]]] = {
    "length": (
        "Length",
        "meters",
        {
            "m": (1.0, "meter meters metre metres"),
            "km": (1000.0, "kilometer kilometers kilometre kilometres"),
            "cm": (1.0e-2, "centimeter centimeters centimetre centimetres"),
            "mm": (1.0e-3, "millimeter millimeters millimetre millimetres"),
        },
    ),
    # Calendar-dependent by definition; the year is only a conventional scalar.
    "time": (
        "Time",
        "seconds",
        {
            "seconds": (1.0, "s sec secs second"),
            "minutes": (_MIN, "m min mins minute"),
            "hours": (_H, "h hr hrs hour"),
            "days": (_DAY, "d day"),
            "years": (365.25 * _DAY, "y yr yrs year"),
        },
    ),
    "hydraulic_conductivity": (
        "Hydraulic-conductivity",
        "m/s",
        {
            "m/s": (
                1.0,
                "m.s-1 m*s-1 m*s^-1 meter/second meters/second metre/second metres/second",
            ),
            "m/day": (1.0 / _DAY, "m/d meter/day meters/day metre/day metres/day"),
            "m/h": (1.0 / _H, "m/hr m/hour meter/hour meters/hour metre/hour metres/hour"),
            "cm/s": (
                1.0e-2,
                "cm.s-1 cm*s-1 cm*s^-1 centimeter/second centimeters/second "
                "centimetre/second centimetres/second",
            ),
            "cm/day": (
                1.0e-2 / _DAY,
                "cm/d centimeter/day centimeters/day centimetre/day centimetres/day",
            ),
            "cm/h": (
                1.0e-2 / _H,
                "cm/hr cm/hour centimeter/hour centimeters/hour centimetre/hour centimetres/hour",
            ),
            "mm/s": (
                1.0e-3,
                "mm.s-1 mm*s-1 mm*s^-1 millimeter/second millimeters/second "
                "millimetre/second millimetres/second",
            ),
            "mm/day": (
                1.0e-3 / _DAY,
                "mm/d millimeter/day millimeters/day millimetre/day millimetres/day",
            ),
            "mm/h": (
                1.0e-3 / _H,
                "mm/hr mm/hour millimeter/hour millimeters/hour millimetre/hour millimetres/hour",
            ),
        },
    ),
    "hydraulic_conductance": (
        "Hydraulic-conductance",
        "m2/s",
        {
            "m2/s": (1.0, "m^2/s m2.s-1 m2*s-1 m2*s^-1"),
            "m2/day": (1.0 / _DAY, "m2/d m^2/day"),
            "m2/h": (1.0 / _H, "m2/hr m2/hour m^2/h"),
            "cm2/s": (1.0e-4, "cm^2/s cm2.s-1 cm2*s-1 cm2*s^-1"),
            "cm2/day": (1.0e-4 / _DAY, "cm2/d cm^2/day"),
            "cm2/h": (1.0e-4 / _H, "cm2/hr cm2/hour cm^2/h"),
            "mm2/s": (1.0e-6, "mm^2/s mm2.s-1 mm2*s-1 mm2*s^-1"),
            "mm2/day": (1.0e-6 / _DAY, "mm2/d mm^2/day"),
            "mm2/h": (1.0e-6 / _H, "mm2/hr mm2/hour mm^2/h"),
        },
    ),
    "volumetric_flow": (
        "Volumetric-flow",
        "m3/s",
        {
            # "m3s-1" is the CF spelling the solver adapters write on an
            # observable. The unit text drops the space, so "m3 s-1" lands here.
            "m3/s": (1.0, "m^3/s m3.s-1 m3*s-1 m3*s^-1 m3s-1 m3s^-1"),
            "m3/day": (1.0 / _DAY, "m3/d m^3/day"),
            "m3/h": (1.0 / _H, "m3/hr m3/hour m^3/h"),
            "m3/min": (1.0 / _MIN, "m3/mn m^3/min"),
            "l/s": (1.0e-3, "liter/s liters/s litre/s litres/s"),
            "l/day": (1.0e-3 / _DAY, "l/d"),
            "l/h": (1.0e-3 / _H, "l/hr l/hour"),
            "l/min": (1.0e-3 / _MIN, ""),
        },
    ),
    # A leakance is an inverse time. The lake-bed leakance (K_bed / thickness_bed)
    # must reach MF6 in 1/s, so legacy 1/day and 1/h declarations are converted.
    "leakance": (
        "Leakance",
        "1/s",
        {
            "1/s": (1.0, "s-1 s^-1 1/sec 1/second"),
            "1/day": (1.0 / _DAY, "1/d day-1 d-1"),
            "1/h": (1.0 / _H, "1/hr 1/hour h-1"),
            "1/min": (1.0 / _MIN, "1/mn min-1"),
        },
    ),
    # 1 MJ/m2/day = 1e6 J / 86400 s = 11.57 W/m2; 1 kWh/m2/day = 41.67 W/m2;
    # 1 J/cm2/day = 0.1157 W/m2; 1 cal/cm2/day (Langley/day) = 0.4843 W/m2.
    "radiation": (
        "Radiation",
        "W/m2",
        {
            "W/m2": (1.0, "w/m^2 w/m² w.m-2 w*m-2 wm-2 watt/m2"),
            "MJ/m2/day": (
                1.0e6 / _DAY,
                "mj/m2/d mj/m2/j mj/m^2/day mj/m^2/d mj/m^2/j mj/m²/day mj/m²/d mj/m²/j "
                "mjm-2d-1 mjm-2day-1",
            ),
            "J/m2/s": (1.0, "j/m^2/s j/m²/s"),
            "kWh/m2/day": (3.6e6 / _DAY, "kwh/m2/d kwh/m^2/day kwh/m²/day"),
            "J/cm2/day": (1.0e4 / _DAY, "j/cm2/d j/cm2/j j/cm^2/day j/cm²/day j/cm²/d j/cm²/j"),
            "cal/cm2/day": (4.184e4 / _DAY, "cal/cm2/d langley/day ly/day ly/d"),
        },
    ),
}

_ALIASES: dict[str, dict[str, str]] = {
    quantity: {
        alias: unit
        for unit, (_, names) in units.items()
        for alias in (unit.lower(), *names.split())
    }
    for quantity, (_, _, units) in QUANTITIES.items()
}


def normalize_unit(quantity: str, unit: object) -> str:
    """Return the canonical unit of ``quantity`` that ``unit`` spells."""
    label, _, units = QUANTITIES[quantity]
    token = canonical_unit_token(unit)
    if token == "":
        raise ValueError(f"{label} unit cannot be empty.")
    canonical = _ALIASES[quantity].get(token)
    if canonical is None:
        # Time keeps its older message, which quotes with repr.
        shown = repr(unit) if quantity == "time" else f"'{unit}'"
        raise ValueError(
            f"Unsupported {label.lower()} unit {shown}. Allowed units: {', '.join(units)}"
        )
    return canonical


def factor_to_si(quantity: str, unit: object) -> float:
    """Return the multiplicative factor from ``unit`` to the SI unit of ``quantity``."""
    return float(QUANTITIES[quantity][2][normalize_unit(quantity, unit)][0])


def require_number(value: object, message: str) -> float:
    """Return ``value`` as a float, and raise ``TypeError(message)`` for a bool or non-number."""
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(message)
    return float(value)


def convert_to_si(quantity: str, value: object, *, unit: object, label: str = "value") -> float:
    """Convert one numeric value from ``unit`` to the SI unit of ``quantity``."""
    number = require_number(
        value, f"{label} must be numeric to convert to {QUANTITIES[quantity][1]}."
    )
    return number * factor_to_si(quantity, unit)


def convert_payload_to_si(
    quantity: str, value: object, *, unit: object, label: str = "value", scale: float = 1.0
) -> object:
    """Convert a scalar, sequence, mapping or numpy payload to SI times ``scale``."""
    factor = factor_to_si(quantity, unit) * scale
    if value is None:
        return None
    if isinstance(value, Real) and not isinstance(value, bool):
        return float(value) * factor
    if isinstance(value, Mapping):
        return {
            key: convert_payload_to_si(
                quantity, item, unit=unit, label=f"{label}[{key!r}]", scale=scale
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [
            convert_payload_to_si(quantity, item, unit=unit, label=f"{label}[{index}]", scale=scale)
            for index, item in enumerate(value)
        ]
    # Arrays: cast to float first, then fall back to a plain copy for other objects.
    if hasattr(value, "astype"):
        try:
            return value.astype(float) * factor
        except Exception:
            pass
    if hasattr(value, "copy") and hasattr(value, "__mul__"):
        try:
            return value.copy() * factor
        except Exception:
            pass
    raise TypeError(f"{label} must be numeric, a sequence, or a mapping.")


def parse_to_si(
    quantity: str,
    value: object,
    *,
    location: str,
    default_unit: str,
    explicit_unit: str | None = None,
) -> tuple[float, str]:
    """Parse ``"<number> <unit>"`` or a number and a unit, and convert to SI.

    Returns ``(value_in_si, canonical_input_unit)``.
    """
    scalar, resolved_unit = parse_scalar_and_unit(
        value, location=location, default_unit=default_unit, explicit_unit=explicit_unit
    )
    canonical = normalize_unit(quantity, resolved_unit)
    return float(scalar) * QUANTITIES[quantity][2][canonical][0], canonical


# Public names, one per quantity. The factor, the canonical-unit tuple and the
# four functions all come from the table above.
LENGTH_CANONICAL_UNITS = tuple(QUANTITIES["length"][2])
normalize_length_unit = partial(normalize_unit, "length")
factor_to_m = partial(factor_to_si, "length")
convert_to_m = partial(convert_to_si, "length")
convert_payload_to_m = partial(convert_payload_to_si, "length")
parse_to_m = partial(parse_to_si, "length", default_unit="m")


def coerce_length_series_to_m(*, values: object, units: object, label: str) -> np.ndarray:
    """Convert one length payload to a float array in meters."""
    source_units = normalize_length_unit(str(units).strip() or "m")
    return np.asarray(convert_payload_to_m(values, unit=source_units, label=label), dtype=float)


def forcing_units(forcing: object, *, fallback: object) -> object:
    """Return the units field of one forcing object or mapping."""
    if isinstance(forcing, Mapping):
        return forcing.get("units", fallback)
    return getattr(forcing, "units", fallback)


M_PER_S_CANONICAL_UNITS = tuple(QUANTITIES["hydraulic_conductivity"][2])
normalize_m_per_s_unit = partial(normalize_unit, "hydraulic_conductivity")
factor_to_m_per_s = partial(factor_to_si, "hydraulic_conductivity")
convert_to_m_per_s = partial(convert_to_si, "hydraulic_conductivity")
convert_payload_to_m_per_s = partial(convert_payload_to_si, "hydraulic_conductivity")
parse_to_m_per_s = partial(parse_to_si, "hydraulic_conductivity", default_unit="m/s")

M2_PER_S_CANONICAL_UNITS = tuple(QUANTITIES["hydraulic_conductance"][2])
normalize_m2_per_s_unit = partial(normalize_unit, "hydraulic_conductance")
factor_to_m2_per_s = partial(factor_to_si, "hydraulic_conductance")
convert_to_m2_per_s = partial(convert_to_si, "hydraulic_conductance")
parse_to_m2_per_s = partial(parse_to_si, "hydraulic_conductance", default_unit="m2/s")

M3_PER_S_CANONICAL_UNITS = tuple(QUANTITIES["volumetric_flow"][2])
normalize_m3_per_s_unit = partial(normalize_unit, "volumetric_flow")
factor_to_m3_per_s = partial(factor_to_si, "volumetric_flow")
convert_to_m3_per_s = partial(convert_to_si, "volumetric_flow")
parse_to_m3_per_s = partial(parse_to_si, "volumetric_flow", default_unit="m3/s")

PER_S_CANONICAL_UNITS = tuple(QUANTITIES["leakance"][2])
normalize_per_s_unit = partial(normalize_unit, "leakance")
factor_to_per_s = partial(factor_to_si, "leakance")
convert_to_per_s = partial(convert_to_si, "leakance")
parse_to_per_s = partial(parse_to_si, "leakance", default_unit="1/s")

RADIATION_CANONICAL_UNITS = tuple(QUANTITIES["radiation"][2])
normalize_radiation_unit = partial(normalize_unit, "radiation")
factor_to_w_per_m2 = partial(factor_to_si, "radiation")
convert_to_w_per_m2 = partial(convert_to_si, "radiation")
