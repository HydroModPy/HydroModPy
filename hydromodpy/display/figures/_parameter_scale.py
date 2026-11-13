"""The aquifer properties the parameter figures draw, on what scale, under what name.

K22 and K33 take the conductivity scale of K, so a set of panels shows an
anisotropic aquifer as a shift of color between K and K33 and not as three
ramps that each fill their own range. The three tensor angles are degrees on a
linear scale. Angle1 is a turn, 0 and 360 are the same direction, so it takes a
cyclic palette over one full turn.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.display.style import PREFERRED_CMAPS
from hydromodpy.display.subject import FigureNotApplicable
from hydromodpy.results import field_registry

if TYPE_CHECKING:
    from matplotlib.colors import Normalize

    from hydromodpy.results.run.view import Run

CONDUCTIVITY_FIELDS = (
    "hydraulic_conductivity",
    "hydraulic_conductivity_k22",
    "hydraulic_conductivity_k33",
)
"""The conductivity along each axis of the K tensor, drawn on one shared scale."""

STORAGE_FIELDS = ("specific_yield", "specific_storage")

ANGLE_FIELDS = (
    "conductivity_tensor_angle1",
    "conductivity_tensor_angle2",
    "conductivity_tensor_angle3",
)
"""The MODFLOW 6 angles of the K tensor, in degrees."""

CYCLIC_FIELDS = ("conductivity_tensor_angle1",)
"""Angles that come back to where they started after a full turn."""

PARAMETER_FIELDS = (*CONDUCTIVITY_FIELDS, *STORAGE_FIELDS, *ANGLE_FIELDS)
"""Aquifer properties the parameter figures can color, in the order panels are drawn."""

PARAMETER_CHOICES = ", ".join(f'"{name}"' for name in PARAMETER_FIELDS)
"""``PARAMETER_FIELDS`` written for an option description."""

LOG_SCALE_DECADES = 1.0
"""Span, in decades, above which a parameter is colored on a log scale."""

FULL_TURN = 360.0

_SHORT_NAMES = {
    "hydraulic_conductivity_k22": "K22, conductivity along the second tensor axis",
    "hydraulic_conductivity_k33": "K33, conductivity along the third tensor axis",
    "conductivity_tensor_angle1": "angle1, first K axis turned from east towards north",
    "conductivity_tensor_angle2": "angle2, first K axis raised above the horizontal",
    "conductivity_tensor_angle3": "angle3, K tensor rotated about its first axis",
}
"""What the registry says in a sentence, cut to fit a title and a color bar."""


def refuse_other_variable(variable: str, *, figure: str) -> None:
    """Refuse a variable that is no aquifer property."""
    if variable not in PARAMETER_FIELDS:
        raise ValueError(
            f"{figure}: {variable!r} is not an aquifer property; "
            f"pick one of {', '.join(PARAMETER_FIELDS)}"
        )


def require_property(sim: Run, variable: str, *, figure: str) -> None:
    """Refuse a variable that is no aquifer property, or one the run did not keep.

    The second refusal depends on the option, so it is a ``FigureNotApplicable``
    and not an ``unavailable_reason``, which only sees the run. A batch skips
    the figure with this sentence as its reason.
    """
    refuse_other_variable(variable, figure=figure)
    if not sim.has_field(variable):
        raise FigureNotApplicable(f"{figure}: {variable!r} is not in this run")


def parameter_name(variable: str) -> str:
    """Return the title of a property, with the convention of a tensor angle in it."""
    return _SHORT_NAMES.get(variable) or field_registry.get(variable).long_name


def parameter_label(variable: str) -> str:
    """Return the color bar label ``"<name> (<units>)"`` of a property."""
    return f"{parameter_name(variable)} ({field_registry.get(variable).units})"


def cmap_for(variable: str, cmap: str | None) -> str:
    """Return the colormap asked for, else the one that fits what ``variable`` is."""
    if cmap:
        return cmap
    return PREFERRED_CMAPS["cyclic" if variable in CYCLIC_FIELDS else "sequential"]


def wrapped(variable: str, values: np.ndarray) -> np.ndarray:
    """Return ``values`` as drawn: a cyclic angle brought into ``[0, 360)``."""
    if variable in CYCLIC_FIELDS:
        return np.mod(values, FULL_TURN)
    return values


def uses_log_scale(values: np.ndarray) -> bool:
    """A parameter spanning more than a decade reads as flat on a linear scale."""
    positive = values[np.isfinite(values) & (values > 0.0)]
    if positive.size == 0:
        return False
    return float(np.log10(positive.max() / positive.min())) > LOG_SCALE_DECADES


def color_norm(variable: str, limits: np.ndarray, *, log: bool | None) -> Normalize | None:
    """Return the color scale of ``variable`` over ``limits``, None for matplotlib's own.

    ``limits`` is what sets the ends of the scale, which is more than the panel
    itself when several conductivities share one. A full turn is the scale of a
    cyclic angle and a linear one is left to matplotlib for the other angles,
    so ``log`` does not reach them: the log of an angle of zero is no number.
    """
    from matplotlib.colors import LogNorm, Normalize

    if variable in CYCLIC_FIELDS:
        return Normalize(vmin=0.0, vmax=FULL_TURN)
    if variable in ANGLE_FIELDS:
        return None
    finite = limits[np.isfinite(limits)]
    if finite.size == 0:
        return None
    if uses_log_scale(finite) if log is None else bool(log):
        positive = finite[finite > 0.0]
        if positive.size == 0:
            return None
        return LogNorm(vmin=float(positive.min()), vmax=float(positive.max()))
    if variable in CONDUCTIVITY_FIELDS:
        return Normalize(vmin=float(finite.min()), vmax=float(finite.max()))
    return None


def mark_turn(colorbar) -> None:
    """Put the quarter turns on the color bar of a cyclic angle."""
    colorbar.set_ticks(np.arange(0.0, FULL_TURN + 1.0, FULL_TURN / 4.0))


__all__ = [
    "ANGLE_FIELDS",
    "CONDUCTIVITY_FIELDS",
    "CYCLIC_FIELDS",
    "LOG_SCALE_DECADES",
    "PARAMETER_CHOICES",
    "PARAMETER_FIELDS",
    "STORAGE_FIELDS",
    "cmap_for",
    "color_norm",
    "mark_turn",
    "parameter_label",
    "parameter_name",
    "refuse_other_variable",
    "require_property",
    "uses_log_scale",
    "wrapped",
]
