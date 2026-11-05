"""Canonical axis labels for field names.

Figures should never hard-code axis labels. Calling :func:`axis_label`
keeps the terminology consistent across the corpus (e.g. "Hydraulic head
(m)" rather than "head (m)" vs. "H (m)" depending on who wrote the
figure).
"""

from __future__ import annotations

from typing import Any

from hydromodpy.core.scope import CATCHMENT

AXIS_LABELS: dict[str, tuple[str, str]] = {
    # field_name: (human label, canonical unit)
    "head": ("Hydraulic head", "m"),
    "watertable_elevation": ("Water-table elevation", "m"),
    "watertable_depth": ("Water-table depth", "m"),
    "drawdown": ("Drawdown", "m"),
    "recharge": ("Recharge", "m/y"),
    "infiltration": ("Infiltration", "m/y"),
    "seepage": ("Seepage", "m/s"),
    "discharge": ("Discharge", "m³/s"),
    "flow": ("Flow", "m³/s"),
    "flux": ("Flux", "m³/s"),
    "velocity": ("Darcy velocity", "m/s"),
    "concentration": ("Concentration", "mg/L"),
    "temperature": ("Temperature", "°C"),
    "elevation": ("Elevation", "m a.s.l."),
    "dem": ("Topography", "m a.s.l."),
    "storage": ("Storage", "m³"),
    "hydraulic_conductivity": ("Hydraulic conductivity", "m/s"),
    "transmissivity": ("Transmissivity", "m²/s"),
    "porosity": ("Porosity", "-"),
    "specific_yield": ("Specific yield", "-"),
    "specific_storage": ("Specific storage", "1/m"),
    "time": ("Time", "d"),
    "date": ("Date", ""),
}


def axis_label(field_name: str, unit: str | None = None) -> str:
    """Return the canonical axis label for ``field_name``.

    If ``field_name`` is unknown, the name itself is used as the label.
    ``unit`` overrides the registered canonical unit when given.
    """
    label, canon_unit = AXIS_LABELS.get(field_name, (field_name, ""))
    display_unit = unit if unit is not None else canon_unit
    if display_unit:
        return f"{label} ({display_unit})"
    return label


_STATION_NAMES: dict[str, str] = {CATCHMENT: "catchment outlet"}


def station_label(station: str) -> str:
    """Return how a title names ``station``.

    The catchment-outlet series is stored under the ``catchment`` station. A
    reader sees ``"catchment outlet"`` instead. A gauge keeps its own id.
    """
    text = str(station)
    return _STATION_NAMES.get(text, text)


def format_length_from_m(value_m: Any, *, unit: str = "m", precision: int = 3) -> str:
    """Format one SI length in the requested display unit, for example ``"1.500 km"``."""
    from hydromodpy.core.units.registry import get_registry

    try:
        meters = float(value_m)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"value_m must be numeric. Got: {value_m!r}") from exc
    number = float(get_registry().Quantity(meters, "m").to(unit).magnitude)
    return f"{number:.{int(precision)}f} {unit}"


__all__ = ["AXIS_LABELS", "axis_label", "format_length_from_m", "station_label"]
