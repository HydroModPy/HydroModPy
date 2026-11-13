"""What a frame asks about a variable: its label, display unit, scale and ramp.

The answers come from the descriptor in ``results/field_registry.py`` and from its
quantity kind in ``core/units/kinds.py``. A descriptor fact (``sign``, ``log``)
wins over the fact of the kind, read through ``request.descriptor``. The checks a
request makes on a name (``shape_of``, ``descriptor``) live in ``request.py``,
which must stay free of matplotlib. Nothing here reads a run.
"""

from __future__ import annotations

import numpy as np
from matplotlib.colors import BoundaryNorm, ListedColormap, LogNorm, Normalize, TwoSlopeNorm

from hydromodpy.core.units.kinds import CATEGORICAL, QuantityKind, scale_of
from hydromodpy.core.units.parse import convert_between_units
from hydromodpy.display.request import descriptor
from hydromodpy.display.theme import RAMPS, Theme, unit_text
from hydromodpy.results.field_registry import kind_of, label_of

FREQUENCY_LABEL = "Share of steps with a non-zero value"
"""Axis label of ``reduce = "frequency"`` on every frame."""


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


def label_parts(name: str) -> tuple[str, str]:
    """Return the label of ``name`` without its unit, and the display unit text."""
    full = label(name)
    return full.rpartition(" (")[0] or full, unit_text(kind(name).display_unit)


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
    return scale_of(kind(name), getattr(descriptor(name), "sign", None))


def is_log(name: str, panel_scale: str | None = None) -> bool:
    """Return whether the values are drawn on a log scale.

    The panel ``scale`` wins when set, then the descriptor ``log``, then the kind.
    """
    if panel_scale is not None:
        return panel_scale == "log"
    own = getattr(descriptor(name), "log", None)
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
    return _class_palette([value for value, _ in descriptor(name).classes], theme)


def _class_palette(values: list[int], theme: Theme) -> list[str]:
    """Paint the class of value 0, the absence, with the no-data role and the rest in order."""
    palette = iter(theme.class_colors(sum(value != 0 for value in values)))
    return [theme.roles["no_data"] if value == 0 else next(palette) for value in values]


def color_norm(
    scale_name: str,
    log: bool,
    values: np.ndarray,
    limits: tuple[float, float] | None = None,
) -> Normalize:
    """Return the colour norm of a continuous scale for ``values``.

    A diverging scale is centred on zero. A log scale starts at the smallest positive
    value unless ``limits`` are given. Without ``limits`` the range of the finite
    values is used, and a range of one value is widened so the ramp stays defined.
    """
    finite = values[np.isfinite(values)]
    lo, hi = limits or ((float(finite.min()), float(finite.max())) if finite.size else (0.0, 1.0))
    if scale_name == "diverging":
        reach = max(abs(lo), abs(hi)) or 1.0
        return TwoSlopeNorm(vcenter=0.0, vmin=-reach, vmax=reach)
    if log:
        positive = finite[finite > 0]
        if limits is None:
            lo = max(lo, float(positive.min()) if positive.size else 1.0)
        return LogNorm(vmin=lo, vmax=max(hi, lo * 10))
    return Normalize(vmin=lo, vmax=hi if hi > lo else lo + 1.0)


def class_scale(
    values: np.ndarray, classes: tuple[tuple[int, str], ...], theme: Theme
) -> tuple[np.ndarray, ListedColormap, BoundaryNorm]:
    """Return the class positions of ``values``, the class colormap and its boundary norm."""
    known = np.array([value for value, _ in classes])
    position = np.where(np.isin(values, known), np.searchsorted(known, values), np.nan)
    return (
        position,
        ListedColormap(_class_palette([int(value) for value in known], theme)),
        BoundaryNorm(np.arange(len(known) + 1) - 0.5, len(known)),
    )


def member_colors(names: list[str], theme: Theme) -> dict[str, str]:
    """Return one palette colour per member of a list, in list order.

    The stacked budget of a series and the budget bars of a groups panel both use it,
    so a term has one colour in every frame.
    """
    return dict(zip(names, theme.class_colors(len(names)), strict=True))


def join_unit(head: str, unit: str) -> str:
    """Return ``head (unit)``, or ``head`` alone for a dimensionless value."""
    return f"{head} ({unit})" if unit else head
