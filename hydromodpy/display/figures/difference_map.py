"""Spatial difference between two simulations on the same mesh."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.display.figure import BaseFigure, FigureNotApplicable, FigureSpec, run_suffix
from hydromodpy.display.figure_options import Cmap, FieldName, ReferenceRun, Timestep
from hydromodpy.display.figure_registry import register
from hydromodpy.display.maps.ugrid import last_timestep, render_face_field

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run


@register
class DifferenceMap(BaseFigure):
    """Map of ``sim - reference`` for one field at one timestep.

    Both simulations must share the same mesh - the figure does not perform
    any interpolation. Pass a second :class:`Run` via ``reference``.
    """

    spec = FigureSpec(
        name="difference_map",
        title="Difference map",
        kind="comparison",
        default_figsize=(7.0, 5.5),
    )

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        reference: ReferenceRun = None,
        field: FieldName = "head",
        timestep: Timestep = None,
        cmap: Cmap = "RdBu_r",
        **_,
    ) -> Axes:
        if reference is None:
            raise FigureNotApplicable(
                "this figure compares two runs on one mesh: pass reference=<run>."
            )
        ts = last_timestep(sim) if timestep is None else timestep
        a = np.asarray(sim.field(field, timestep=ts)).ravel()
        b = np.asarray(reference.field(field, timestep=ts)).ravel()
        if a.shape != b.shape:
            raise ValueError(
                f"difference_map: incompatible mesh - sim has {a.size} faces, "
                f"reference has {b.size}"
            )
        diff = a - b
        vmax = float(np.nanmax(np.abs(diff))) or 1.0
        descriptor = self.field_descriptor_for(field)
        render_face_field(
            ax,
            sim,
            diff,
            cmap=cmap,
            vmin=-vmax,
            vmax=vmax,
            cbar_label=f"Δ {descriptor.long_name} ({descriptor.units})",
        )
        # Runs are named, never by id: a reader knows a run by its name.
        ax.set_title(
            f"Δ {descriptor.long_name}{run_suffix(sim)}{run_suffix(reference, ' minus {}')}"
        )
        ax.set_xlabel("x (m)")
        ax.set_ylabel("y (m)")
        return ax
