"""Unit conversion helpers."""

from __future__ import annotations

# (from_unit, to_unit) -> multiplicative factor
_CONVERSIONS: dict[tuple[str, str], float] = {
    ("L/s", "m3/s"): 0.001,
    ("m3/s", "L/s"): 1000.0,
    ("mm/d", "m/s"): 1.0 / 86_400_000,
    ("m/s", "mm/d"): 86_400_000.0,
    ("mm/d", "m/d"): 0.001,
    ("m/d", "mm/d"): 1000.0,
    ("cm", "m"): 0.01,
    ("m", "cm"): 100.0,
    ("mm", "m"): 0.001,
    ("m", "mm"): 1000.0,
    ("ug/L", "mg/L"): 0.001,
    ("mg/L", "ug/L"): 1000.0,
}


def convert_value(value: float, from_unit: str, to_unit: str) -> float:
    """Convert a value between known units."""
    if from_unit == to_unit:
        return value
    factor = _CONVERSIONS.get((from_unit, to_unit))
    if factor is None:
        raise ValueError(f"Unknown unit conversion: '{from_unit}' -> '{to_unit}'")
    return value * factor


def get_conversion_factor(from_unit: str, to_unit: str) -> float:
    """Return multiplicative factor, or 1.0 if units match."""
    if from_unit == to_unit:
        return 1.0
    factor = _CONVERSIONS.get((from_unit, to_unit))
    if factor is None:
        raise ValueError(f"Unknown unit conversion: '{from_unit}' -> '{to_unit}'")
    return factor
