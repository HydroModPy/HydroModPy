"""Canonical axis labels for field names.

Figures should never hard-code axis labels. Calling :func:`axis_label`
keeps the terminology consistent across the corpus (e.g. "Hydraulic head
(m)" rather than "head (m)" vs. "H (m)" depending on who wrote the
figure).
"""

from __future__ import annotations

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


__all__ = ["AXIS_LABELS", "axis_label"]
