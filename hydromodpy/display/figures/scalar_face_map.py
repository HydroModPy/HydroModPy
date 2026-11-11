"""Shared base for every "one scalar per mesh face" map figure.

Water-table elevation, water-table depth, recharge, concentration and the
seepage indicator are the same drawing with a different variable, colormap
and label. Factoring them here keeps their styling identical and gives
every one of them the same options: timestep, layer, color scale and
declarative overlays.

Subclasses only declare ``spec`` plus the class attributes below.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import numpy as np

from hydromodpy.core.fields.vertical_column import top_active_layer, values_at_layer
from hydromodpy.display.figure import BaseFigure, run_suffix
from hydromodpy.display.figure_options import CmapOrOwn, Layer, Overlays, Timestep, Vmax, Vmin
from hydromodpy.display.figures._instant import instant_label
from hydromodpy.display.maps.axes import style_relative_km_axes
from hydromodpy.display.maps.overlays import apply_overlays
from hydromodpy.display.maps.ugrid import last_timestep, render_face_field
from hydromodpy.display.style import place_legend

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run.view import Run


def top_active_values(sim: Run, values: np.ndarray) -> np.ndarray:
    """Return a ``(layer, face)`` field at the top active cell of each column.

    The stored ``idomain`` says which cell that is; a run without one shows
    layer 0. A column with no active cell is NaN.
    """
    if not sim.has_field("idomain"):
        return np.asarray(values[0], dtype="float64")
    layer = top_active_layer(np.asarray(sim.field("idomain")))
    return values_at_layer(values, layer)


class ScalarFaceMap(BaseFigure):
    """Plan-view map of one registered field, one value per mesh face."""

    #: Public field name read from the run. Defaults to the single entry of
    #: ``spec.required_fields``.
    variable: ClassVar[str | None] = None
    #: Colormap used when the caller does not pass one.
    default_cmap: ClassVar[str] = "viridis"
    #: Overlays drawn unless the caller overrides ``overlays``.
    default_overlays: ClassVar[tuple[str, ...]] = ("watershed",)
    #: Human-readable label for the colorbar. Defaults to the field registry
    #: entry, i.e. ``"<long_name> (<units>)"``.
    cbar_label: ClassVar[str | None] = None

    def field_name(self) -> str:
        """Return the field this map reads."""
        if self.variable is not None:
            return self.variable
        if len(self.spec.required_fields) != 1:
            raise NotImplementedError(
                f"{type(self).__name__} must set 'variable' when spec.required_fields "
                "does not hold exactly one entry."
            )
        return self.spec.required_fields[0]

    def values(self, sim: Run, *, timestep: int, layer: int | None) -> np.ndarray:
        """Return the per-face values to draw. Override to post-process."""
        values = np.asarray(sim.field(self.field_name(), time=timestep, layer=layer))
        if values.ndim > 1:
            # Layered field with no explicit layer selection: show the top active
            # cell of each column, the one the surface processes act on.
            values = top_active_values(sim, values)
        return values

    def label(self) -> str:
        """Return the colorbar label."""
        if self.cbar_label is not None:
            return self.cbar_label
        return self.axis_label_for(self.field_name())

    def title(self, sim: Run, *, timestep: int) -> str:
        """Return the axes title, naming the period drawn when the run has dates."""
        base = f"{self.spec.title}{run_suffix(sim)}"
        period = instant_label(sim, timestep)
        return f"{base}\n{period}" if period else base

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        timestep: Timestep = None,
        layer: Layer = None,
        cmap: CmapOrOwn = None,
        vmin: Vmin = None,
        vmax: Vmax = None,
        overlays: Overlays = None,
        **_,
    ) -> Axes:
        step = last_timestep(sim) if timestep is None else timestep
        values = self.values(sim, timestep=step, layer=layer)
        render_face_field(
            ax,
            sim,
            values,
            cmap=cmap or self.default_cmap,
            vmin=vmin,
            vmax=vmax,
            cbar_label=self.label(),
        )
        apply_overlays(
            ax,
            sim,
            self.default_overlays if overlays is None else overlays,
            timestep=step,
        )
        style_relative_km_axes(ax)
        ax.set_title(self.title(sim, timestep=step))
        handles, _labels = ax.get_legend_handles_labels()
        if handles:
            place_legend(ax, fontsize=8, framealpha=0.9)
        return ax


__all__ = ["ScalarFaceMap"]
