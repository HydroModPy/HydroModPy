"""Length helpers centered on SI (meters)."""

from __future__ import annotations

import re
from collections.abc import Mapping
from numbers import Real
from typing import Any

from hydromodpy.core.units.scalar import (
    canonical_unit_token as _canonical_unit_token,
)
from hydromodpy.core.units.scalar import (
    parse_scalar_and_unit,
)

try:
    from pint import UnitRegistry
except Exception:  # pragma: no cover - fallback when pint is unavailable.
    UnitRegistry = None  # type: ignore[assignment]


_SIMPLE_LENGTH_FACTORS_TO_M: dict[str, float] = {
    "m": 1.0,
    "meter": 1.0,
    "meters": 1.0,
    "metre": 1.0,
    "metres": 1.0,
    "km": 1000.0,
    "kilometer": 1000.0,
    "kilometers": 1000.0,
    "kilometre": 1000.0,
    "kilometres": 1000.0,
    "cm": 0.01,
    "centimeter": 0.01,
    "centimeters": 0.01,
    "centimetre": 0.01,
    "centimetres": 0.01,
    "mm": 0.001,
    "millimeter": 0.001,
    "millimeters": 0.001,
    "millimetre": 0.001,
    "millimetres": 0.001,
}

_LENGTH_TOKEN_PATTERN = re.compile(
    r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*([A-Za-z_/\-^0-9]+)?\s*$"
)

LENGTH_CANONICAL_UNITS: tuple[str, ...] = ("m", "km", "cm", "mm")

_LENGTH_UNIT_ALIASES: dict[str, str] = {
    "m": "m",
    "meter": "m",
    "meters": "m",
    "metre": "m",
    "metres": "m",
    "km": "km",
    "kilometer": "km",
    "kilometers": "km",
    "kilometre": "km",
    "kilometres": "km",
    "cm": "cm",
    "centimeter": "cm",
    "centimeters": "cm",
    "centimetre": "cm",
    "centimetres": "cm",
    "mm": "mm",
    "millimeter": "mm",
    "millimeters": "mm",
    "millimetre": "mm",
    "millimetres": "mm",
}

_LENGTH_FACTORS_TO_M: dict[str, float] = {
    "m": 1.0,
    "km": 1000.0,
    "cm": 1.0e-2,
    "mm": 1.0e-3,
}


def _build_unit_registry() -> Any:
    if UnitRegistry is None:
        return None
    ureg = UnitRegistry(autoconvert_offset_to_baseunit=True)
    return ureg


_UREG = _build_unit_registry()


def _coerce_float(value: Any, *, label: str) -> float:
    try:
        return float(value)
    except Exception as exc:
        raise ValueError(f"{label} must be numeric. Got: {value!r}") from exc


def normalize_length_unit(unit: str) -> str:
    """Normalize one length unit token to a strict canonical form."""
    token = _canonical_unit_token(unit)
    if token == "":
        raise ValueError("Length unit cannot be empty.")
    canonical = _LENGTH_UNIT_ALIASES.get(token)
    if canonical is None:
        allowed = ", ".join(LENGTH_CANONICAL_UNITS)
        raise ValueError(f"Unsupported length unit '{unit}'. Allowed units: {allowed}")
    return canonical


def factor_to_m(unit: str) -> float:
    """Return multiplicative factor to convert one unit to meters."""
    return float(_LENGTH_FACTORS_TO_M[normalize_length_unit(unit)])


def convert_to_m(
    value: object,
    *,
    unit: str,
    label: str = "value",
) -> float:
    """Convert one numeric value from ``unit`` to meters."""
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TypeError(f"{label} must be numeric to convert to meters.")
    return float(value) * factor_to_m(unit)


def convert_payload_to_m(
    value: object,
    *,
    unit: str,
    label: str = "value",
) -> object:
    """Convert one scalar/sequence/mapping payload from ``unit`` to meters."""
    factor = factor_to_m(unit)
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError(f"{label} must be numeric, a sequence, or a mapping.")
    if isinstance(value, Real):
        return float(value) * factor
    if isinstance(value, Mapping):
        return {
            key: convert_payload_to_m(
                item,
                unit=unit,
                label=f"{label}[{key!r}]",
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [
            convert_payload_to_m(
                item,
                unit=unit,
                label=f"{label}[{index}]",
            )
            for index, item in enumerate(value)
        ]
    if hasattr(value, "astype"):
        try:
            return value.astype(float) * float(factor)
        except Exception:
            pass
    if hasattr(value, "copy") and hasattr(value, "__mul__"):
        try:
            return value.copy() * float(factor)
        except Exception:
            pass
    raise TypeError(f"{label} must be numeric, a sequence, or a mapping.")


def parse_to_m(
    value: object,
    *,
    location: str,
    default_unit: str = "m",
    explicit_unit: str | None = None,
) -> tuple[float, str]:
    """Parse scalar + unit payload and convert to meters."""
    scalar, resolved_unit = parse_scalar_and_unit(
        value,
        location=location,
        default_unit=default_unit,
        explicit_unit=explicit_unit,
    )
    canonical_unit = normalize_length_unit(resolved_unit)
    return float(scalar) * _LENGTH_FACTORS_TO_M[canonical_unit], canonical_unit


def _fallback_parse(value: Any, *, default_unit: str, label: str) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        factor = _SIMPLE_LENGTH_FACTORS_TO_M.get(str(default_unit).strip().lower())
        if factor is None:
            raise ValueError(
                f"{label}: unsupported default length unit without pint: {default_unit!r}"
            )
        return float(value) * factor

    if isinstance(value, Mapping):
        if "value" not in value:
            raise ValueError(f"{label}: mapping input must contain key 'value'.")
        raw_value = _coerce_float(value.get("value"), label=f"{label}.value")
        raw_unit = str(value.get("unit", default_unit)).strip().lower()
        factor = _SIMPLE_LENGTH_FACTORS_TO_M.get(raw_unit)
        if factor is None:
            raise ValueError(f"{label}: unsupported length unit without pint: {raw_unit!r}")
        return raw_value * factor

    if isinstance(value, str):
        token = value.strip()
        if token == "":
            raise ValueError(f"{label}: empty length string is not allowed.")
        match = _LENGTH_TOKEN_PATTERN.match(token)
        if match is None:
            raise ValueError(
                f"{label}: invalid length string {value!r}. Expected formats like '20 km' or '500 m'."
            )
        raw_value = float(match.group(1))
        raw_unit = (match.group(2) or str(default_unit)).strip().lower()
        factor = _SIMPLE_LENGTH_FACTORS_TO_M.get(raw_unit)
        if factor is None:
            raise ValueError(f"{label}: unsupported length unit without pint: {raw_unit!r}")
        return raw_value * factor

    raise ValueError(f"{label}: unsupported length value type: {type(value).__name__}.")


def parse_length_to_m(
    value: Any,
    *,
    default_unit: str = "m",
    label: str = "length",
) -> float:
    """Convert a length-like input to meters (SI float)."""
    if value is None:
        raise ValueError(f"{label} cannot be None.")

    if _UREG is None:
        return _fallback_parse(value, default_unit=default_unit, label=label)

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        quantity = _UREG.Quantity(float(value), default_unit)
        return float(quantity.to("m").magnitude)

    if isinstance(value, Mapping):
        if "value" not in value:
            raise ValueError(f"{label}: mapping input must contain key 'value'.")
        raw_value = _coerce_float(value.get("value"), label=f"{label}.value")
        raw_unit = str(value.get("unit", default_unit)).strip() or str(default_unit)
        quantity = _UREG.Quantity(raw_value, raw_unit)
        return float(quantity.to("m").magnitude)

    if isinstance(value, str):
        token = value.strip()
        if token == "":
            raise ValueError(f"{label}: empty length string is not allowed.")
        match = _LENGTH_TOKEN_PATTERN.match(token)
        if match is not None:
            raw_value = float(match.group(1))
            raw_unit = (match.group(2) or str(default_unit)).strip() or str(default_unit)
            quantity = _UREG.Quantity(raw_value, raw_unit)
            return float(quantity.to("m").magnitude)
        quantity = _UREG.Quantity(token)
        return float(quantity.to("m").magnitude)

    # Allow direct pint quantities.
    if hasattr(value, "to") and hasattr(value, "magnitude"):
        return float(value.to("m").magnitude)

    raise ValueError(f"{label}: unsupported length value type: {type(value).__name__}.")


def format_length_from_m(value_m: Any, *, unit: str = "m", precision: int = 3) -> str:
    """Format one SI length in the requested display unit."""
    meters = _coerce_float(value_m, label="value_m")
    if _UREG is not None:
        quantity = _UREG.Quantity(meters, "m").to(unit)
        number = float(quantity.magnitude)
        return f"{number:.{int(precision)}f} {unit}"

    factor = _SIMPLE_LENGTH_FACTORS_TO_M.get(str(unit).strip().lower())
    if factor is None:
        raise ValueError(f"Unsupported output unit without pint: {unit!r}")
    number = meters / factor
    return f"{number:.{int(precision)}f} {unit}"
