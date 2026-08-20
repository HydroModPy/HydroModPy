"""Shared base for every "one scalar per mesh face" map figure.

Water-table elevation, water-table depth, recharge, concentration and the
seepage indicator are the same drawing with a different variable, colormap
and label. Factoring them here keeps their styling identical and gives
every one of them the same options: timestep, layer, colour scale and
declarative overlays.

Subclasses only declare ``spec`` plus the class attributes below.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

import numpy as np

from hydromodpy.display.figure import BaseFigure
from hydromodpy.display.map_axes import style_relative_km_axes
from hydromodpy.display.overlays import apply_overlays
from hydromodpy.display.ugrid import last_timestep, render_face_field

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from hydromodpy.results.run import Run


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
        values = np.asarray(sim.field(self.field_name(), timestep=timestep, layer=layer))
        if values.ndim > 1:
            # Layered field with no explicit layer selection: show the top layer,
            # which is the one the surface processes act on.
            values = values[0]
        return values

    def label(self) -> str:
        """Return the colorbar label."""
        if self.cbar_label is not None:
            return self.cbar_label
        return self.axis_label_for(self.field_name())

    def title(self, sim: Run, *, timestep: int) -> str:
        """Return the axes title, dated when the run carries a time axis."""
        base = f"{self.spec.title} - {sim.name or sim.sim_id}"
        stamp = _timestamp_label(sim, timestep)
        return f"{base}\n{stamp}" if stamp else base

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        timestep: int | None = None,
        layer: int | None = None,
        cmap: str | None = None,
        vmin: float | None = None,
        vmax: float | None = None,
        overlays: tuple[str, ...] | list[str] | None = None,
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
            ax.legend(loc="best", fontsize=8, framealpha=0.9)
        return ax


def _timestamp_label(sim: Run, timestep: int) -> str:
    """Return the ISO date of ``timestep``, or an empty string when unknown."""
    try:
        index = sim.time_index
    except Exception:
        return ""
    if timestep < 0 or timestep >= len(index):
        return ""
    return f"{index[timestep]:%Y-%m-%d} (step {timestep + 1}/{len(index)})"


__all__ = ["ScalarFaceMap"]
