"""Where the drainage accumulates, on the scale the field actually spans.

``accumulation_flux`` is the drain outflow summed along the downslope paths,
so over one catchment it spans four to five decades. A linear ramp paints the
trunk bright and leaves every headwater at the bottom colour, which is why the
only figure reading the field so far thresholded it instead of showing it.
This map draws the field itself, on a logarithmic ramp by default.

A cell carrying no accumulated flux is not a small value, it is a cell no
upslope release ever reached. Those cells are drawn in a flat neutral grey
under both scales and counted in the legend, so the ramp only ever describes
the drainage network itself.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Literal

import numpy as np

from hydromodpy.display.colormaps import get_cmap
from hydromodpy.display.figure import FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.figures._scalar_face_map import ScalarFaceMap
from hydromodpy.display.legend_placement import place_legend
from hydromodpy.display.map_axes import style_relative_km_axes
from hydromodpy.display.overlays import apply_overlays
from hydromodpy.display.ugrid import last_timestep, render_face_field

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.colors import Colormap

    from hydromodpy.results.run import Run

GROUND_COLOR = "#EDEDED"
"""Cells no accumulated flux reaches, and the lightest thing on the page."""

GROUND_EDGE = "#C8C8C8"
"""A border on the legend swatch, which is otherwise near-white on white."""

PALETTE_FLOOR = 0.45
"""How much of the sequential palette is cut, as a fraction of its range.

The pale end of a sequential palette is lighter than the ground grey, so the
cells drawn in it would dissolve into the cells the ramp says nothing about.
Dropping that end keeps every drawn value darker than the ground, which is
also what carries the map through a greyscale print: one hue, and a lightness
that never meets the background.
"""


@register
class AccumulationMap(ScalarFaceMap):
    """Accumulated drain outflow per cell, on a logarithmic ramp.

    The scale is the whole point. ``scale="linear"`` is available for a caller
    who wants the raw proportions, and ``vmin`` / ``vmax`` pin the ramp when
    two runs have to be compared on one scale.
    """

    spec = FigureSpec(
        name="accumulation_map",
        title="Accumulated drainage flux",
        kind="spatial",
        required_fields=("accumulation_flux",),
        default_figsize=(7.0, 5.5),
    )
    default_cmap: ClassVar[str] = "Blues"
    default_overlays: ClassVar[tuple[str, ...]] = ("watershed", "outlet")

    def label(self) -> str:
        """Return the colorbar label, with the units the registry declares."""
        units = self.field_descriptor_for(self.field_name()).units
        return f"Accumulated drain outflow ({units})"

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        timestep: int | None = None,
        scale: Literal["log", "linear"] = "log",
        cmap: str | None = None,
        palette_floor: float = PALETTE_FLOOR,
        vmin: float | None = None,
        vmax: float | None = None,
        overlays: tuple[str, ...] | list[str] | None = None,
        **_,
    ) -> Axes:
        from matplotlib.colors import LogNorm
        from matplotlib.patches import Patch

        if scale not in ("log", "linear"):
            raise ValueError(f"scale must be 'log' or 'linear', got {scale!r}.")

        step = last_timestep(sim) if timestep is None else timestep
        values = np.asarray(self.values(sim, timestep=step, layer=None), dtype="float64")
        carried = np.isfinite(values) & (values > 0.0)
        low = float(values[carried].min()) if carried.any() else 0.0
        high = float(values[carried].max()) if carried.any() else 1.0
        low = low if vmin is None else float(vmin)
        high = high if vmax is None else float(vmax)

        use_log = scale == "log" and bool(carried.any())
        if use_log and low <= 0.0:
            raise ValueError(
                "a logarithmic ramp needs a strictly positive lower bound; "
                "pass vmin > 0 or scale='linear'."
            )

        collection = render_face_field(
            ax,
            sim,
            np.where(carried, values, np.nan),
            cmap=truncated_palette(cmap or self.default_cmap, palette_floor),
            cbar_label=self.label(),
        )
        if use_log:
            collection.set_norm(LogNorm(vmin=low, vmax=high))
        else:
            collection.set_clim(vmin=low, vmax=high)

        apply_overlays(
            ax,
            sim,
            self.default_overlays if overlays is None else overlays,
            timestep=step,
        )
        style_relative_km_axes(ax)
        ax.set_title(self.title(sim, timestep=step))

        handles, _labels = ax.get_legend_handles_labels()
        empty = int((~carried).sum())
        if empty:
            handles.append(
                Patch(
                    facecolor=GROUND_COLOR,
                    edgecolor=GROUND_EDGE,
                    label=f"no accumulated flux ({_cell_count(empty)})",
                )
            )
        if handles:
            place_legend(ax, handles=handles, fontsize=9, framealpha=0.9)
        return ax


def truncated_palette(name: str, floor: float) -> Colormap:
    """Return the sequential palette ``name`` with its light end cut off.

    Which end that is has to be measured, not assumed. ``Blues`` and its
    family are light at the bottom, ``viridis`` and its family at the top,
    and cutting the bottom of the second kind removes the dark colours and
    leaves the pale ones sitting on the ground grey: the cells the ramp is
    supposed to single out are then the ones that vanish.

    Masked cells take the ground colour, which is how a cell with no
    accumulated flux leaves the ramp instead of sitting at its bottom.
    """
    from matplotlib.colors import ListedColormap

    if not 0.0 <= floor < 1.0:
        raise ValueError(f"palette_floor must sit in [0, 1), got {floor!r}.")
    base = get_cmap(name)
    light_at_bottom = _relative_luminance(base(0.0)) > _relative_luminance(base(1.0))
    low, high = (floor, 1.0) if light_at_bottom else (0.0, 1.0 - floor)
    palette = ListedColormap(base(np.linspace(low, high, base.N)), name=f"{name}_floor")
    return palette.with_extremes(bad=GROUND_COLOR)


def _relative_luminance(color: str | tuple[float, ...]) -> float:
    """Perceived brightness of one colour, the quantity a greyscale print keeps."""
    from matplotlib.colors import to_rgb

    channels = [
        value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        for value in to_rgb(color)
    ]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _cell_count(count: int) -> str:
    """Return a cell count written for a legend entry."""
    return f"{count:,} cell" if count == 1 else f"{count:,} cells"


__all__ = ["AccumulationMap", "truncated_palette"]
