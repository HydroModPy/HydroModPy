"""What a frame asks about a variable: its label, display unit, scale and ramp.

The answers come from the descriptor in ``results/field_registry.py`` and from its
quantity kind in ``core/units/kinds.py``. A descriptor fact (``sign``, ``log``)
wins over the fact of the kind, read through ``request.descriptor``. The checks a
request makes on a name (``shape_of``, ``descriptor``) live in ``request.py``,
which must stay free of matplotlib. Nothing here reads a run.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.core.units.kinds import CATEGORICAL, QuantityKind, scale_of
from hydromodpy.core.units.parse import convert_between_units
from hydromodpy.display.request import descriptor
from hydromodpy.display.theme import RAMPS, Theme, unit_text
from hydromodpy.results.field_registry import kind_of, label_of


def kind(name: str) -> QuantityKind:
    """Return the quantity kind of a registered variable."""
    return kind_of(name)


def label(name: str) -> str:
    """Return the axis label with the display unit, ``"Hydraulic head (m)"``.

    The unit goes through ``theme.unit_text``. A dimensionless unit adds nothing. A
    budget term adds ``BUDGET_SIGN_RULE`` to the legend, not to the label.
    """
    unit = unit_text(kind(name).display_unit)
    return f"{label_of(name)} ({unit})" if unit else label_of(name)


def to_display(
    name: str, values: np.ndarray, *, area: np.ndarray | float | None = None
) -> np.ndarray:
    """Convert ``values`` from the stored unit to the display unit of the kind of ``name``.

    A ``per_area`` kind first divides by ``area`` in m2: the cell areas for a map,
    the zone area for a zone series. ``area`` is required then and ignored
    otherwise. The conversion goes through ``convert_between_units`` of
    ``core/units``. NaN stays NaN. Returns float64 of the same shape.
    """
    kind_ = kind(name)
    data = np.asarray(values, dtype=float)
    stored = kind_.stored_unit
    if kind_.per_area:
        if area is None:
            raise ValueError(f"{name!r} is a flow per area: pass the area in m2.")
        data = data / np.asarray(area, dtype=float)
        stored = "m s-1"
    # Every unit of the kinds is linear, so one factor converts the whole array.
    factor = convert_between_units(1.0, from_unit=stored, to_unit=kind_.display_unit)
    return data * factor


def scale(name: str) -> str:
    """Return the colour scale family, ``scale_of(kind, descriptor.sign)``."""
    return scale_of(kind(name), descriptor(name).sign)


def is_log(name: str, panel_scale: str | None = None) -> bool:
    """Return whether the values are drawn on a log scale.

    The panel ``scale`` wins when set, then the descriptor ``log``, then the kind.
    """
    if panel_scale is not None:
        return panel_scale == "log"
    own = descriptor(name).log
    return kind(name).log if own is None else own


def ramp(name: str, theme: Theme) -> str:
    """Return the colormap name: the quantity ramp of the theme, else the ramp of its scale.

    A categorical scale has no ramp and takes ``theme.categorical`` in class order;
    this returns ``""`` for it.
    """
    family = scale(name)
    if family == CATEGORICAL:
        return ""
    own = theme.quantity_ramps.get(descriptor(name).quantity)
    if own is None or (own == theme.ramps["diverging"] and family != "diverging"):
        return theme.ramps.get(family, RAMPS[family])
    return own


def class_colors(name: str, theme: Theme) -> list[str]:
    """Return one colour per class of a categorical variable, in the order of its classes."""
    palette = theme.categorical
    return [palette[i % len(palette)] for i, _ in enumerate(descriptor(name).classes)]
