"""Which boundary package acts on which cell, read from what the model did.

There is no per-cell package table in the store, and there should not be: a
package a builder declared and the solver never applied would still be in it.
What the store holds is the per-cell budget, one array per component under
``budget/``. A cell where a component carries a non-zero flux is a cell that
package acts on, whichever backend solved the model and whichever section of
the configuration put the package there.

Overlaps are drawn, not resolved. A cell that two packages act on (a drain on
a streambed cell, a well under a lake) takes its own class rather than the
colour of whichever package happens to be painted last, so the map never
quietly hides a package behind another.

Which cell a package acts on is a structural question, so the default answer
is taken over the whole run: a drain cell discharges on the days the water
table reaches it and carries nothing on the others, and one of those days is
not the map the reader asked for. That costs one pass over every persisted
step of every stored component, read in one opening of the store and in the
slabs it was written in; ``over="step"`` narrows it to the rendered step, and
then the map answers which cells are exchanging water on that day instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

import numpy as np

from hydromodpy.display.figure import BaseFigure, FigureSpec
from hydromodpy.display.figure_registry import register
from hydromodpy.display.map_axes import overlay_watershed_contour, style_relative_km_axes
from hydromodpy.display.mesh_geometry import face_polygons
from hydromodpy.display.overlays import apply_overlays
from hydromodpy.display.ugrid import last_timestep
from hydromodpy.results.derive.config_flags import enable_options_hint, missing_field_options

if TYPE_CHECKING:
    from matplotlib.axes import Axes
    from matplotlib.patches import Patch

    from hydromodpy.results.run import Run

BOUNDARY_PACKAGES: dict[str, tuple[str, str]] = {
    "drain": ("DRN", "#332288"),
    "river": ("RIV", "#882255"),
    "well": ("WEL", "#CC3311"),
    "stream": ("SFR", "#009988"),
    "constant_head": ("CHD", "#AAAA00"),
    "lake": ("LAK", "#88CCEE"),
}
"""Public field name of each boundary package, its MODFLOW label and colour.

The colours are fixed per package so two runs of the same catchment can be
laid side by side, and they climb in lightness in the order written here
(roughly L* 22, 32, 46, 57, 68, 79). Every pair is therefore separable in
greyscale as well as in hue, and a map showing any subset keeps that spacing.
"""

SEVERAL_COLOR = "#1A1A1A"
"""Cells more than one package acts on: the darkest thing on the page."""

GROUND_COLOR = "#EDEDED"
"""Cells no boundary package acts on: they cover the catchment, so they recede."""

GROUND_EDGE = "#C8C8C8"
"""A border on the two neutral legend swatches, which are otherwise flat."""

LEGEND_ANCHOR = (1.01, 1.0)
"""The legend sits outside the axes, where the scalar maps put their colorbar.

Eight classes and a note at the foot leave a placed legend nowhere to go
without covering one of them, and a categorical map has no colorbar competing
for that margin.
"""

_NOTE_BOX = {"facecolor": "white", "alpha": 0.9, "edgecolor": GROUND_EDGE}

_DEFAULT_SLAB_STEPS = 64
"""Steps read at once from a store that does not declare a time chunk."""


@register
class BoundaryPackageMap(BaseFigure):
    """Categorical map of the boundary package acting on each cell.

    ``over="run"`` (the default) asks which cells a package acts on at all;
    ``over="step"`` asks which ones exchange water at ``timestep``. The outlet
    is marked because whether it sits in a package, and in which one, is the
    first thing a reader checks on this map.

    The six components are declared optional rather than required: any one of
    them draws the map, so requiring them all would report the figure
    unavailable on a run that carries only DRN. Declared all the same, so the
    planner counts this figure among the consumers of the per-cell budget and
    computes the group when it is asked for.
    """

    spec = FigureSpec(
        name="boundary_package_map",
        title="Boundary packages",
        kind="spatial",
        optional_fields=tuple(BOUNDARY_PACKAGES),
        default_figsize=(9.0, 5.5),
    )

    def unavailable_reason(self, sim: Run) -> str | None:
        """Name the components looked for, and the option that would keep them."""
        base = super().unavailable_reason(sim)
        if base is not None:
            return base
        if any(sim.has_field(name) for name in BOUNDARY_PACKAGES):
            return None
        looked_for = ", ".join(BOUNDARY_PACKAGES)
        reason = (
            "this run stores no per-cell boundary flux: none of "
            f"{looked_for} is in the store, so no cell can be attributed to a package."
        )
        options = missing_field_options(BOUNDARY_PACKAGES, sim)
        return reason if not options else f"{reason} {enable_options_hint(options)}"

    def render(
        self,
        sim: Run,
        ax: Axes,
        *,
        over: Literal["run", "step"] = "run",
        timestep: int | None = None,
        **_,
    ) -> Axes:
        if over not in ("run", "step"):
            raise ValueError(f"over must be 'run' or 'step', got {over!r}.")

        polygons = face_polygons(sim)
        n_faces = len(polygons)
        step = last_timestep(sim) if timestep is None else timestep

        stored = [name for name in BOUNDARY_PACKAGES if sim.has_field(name)]
        if not stored:
            raise ValueError(self.unavailable_reason(sim))
        acting = (
            {name: _acting_cells(sim, name, step, n_faces) for name in stored}
            if over == "step"
            else _acting_cells_over_run(sim, stored, n_faces)
        )

        several = np.sum(list(acting.values()), axis=0) >= 2
        none = ~np.logical_or.reduce(list(acting.values()))

        _add_class(ax, polygons, none, color=GROUND_COLOR, zorder=1)
        for zorder, name in enumerate(acting, start=2):
            _add_class(
                ax,
                polygons,
                acting[name] & ~several,
                color=BOUNDARY_PACKAGES[name][1],
                zorder=zorder,
            )
        _add_class(ax, polygons, several, color=SEVERAL_COLOR, zorder=len(acting) + 2)

        overlay_watershed_contour(ax, sim, color="#404040", linewidth=0.9, alpha=0.7)
        apply_overlays(ax, sim, ("outlet",), timestep=step)
        style_relative_km_axes(ax)
        ax.set_title(f"{self.spec.title} - {sim.name or sim.sim_id}")
        marked, _labels = ax.get_legend_handles_labels()
        ax.legend(
            handles=_legend_handles(acting, several, none) + marked,
            loc="upper left",
            bbox_to_anchor=LEGEND_ANCHOR,
            fontsize=9,
            framealpha=0.9,
        )
        ax.annotate(
            _note(sim, step, over),
            xy=(0.5, 0.03),
            xycoords="axes fraction",
            ha="center",
            va="bottom",
            fontsize=9,
            bbox=_NOTE_BOX,
            zorder=10,
        )
        return ax


def _acting_cells(sim: Run, name: str, step: int, n_faces: int) -> np.ndarray:
    """Return the cells one package carries a non-zero flux on, at one step."""
    return _acting_faces(np.asarray(sim.field(name, timestep=step)), name, n_faces)


def _acting_cells_over_run(sim: Run, names: list[str], n_faces: int) -> dict[str, np.ndarray]:
    """Return, per package, the cells it acts on at any persisted step.

    One store opening for the whole map. Asking the run for one timestep at a
    time reopens the Zarr store on every call: six components over a 365-day
    chronicle is 2 190 openings for one figure, and a ten-year daily run is
    twenty times that. The stack of each component is read once instead, in
    slabs of the chunking it was written in, so the memory stays bounded
    whatever the chronicle is worth.
    """
    from hydromodpy.results.field_registry import get as field_descriptor
    from hydromodpy.results.run.array import lookup_zarr_path

    store = sim._catalog.open_zarr(sim.sim_id)
    try:
        return {
            name: _acting_over_stack(
                lookup_zarr_path(store.root, field_descriptor(name).zarr_path), name, n_faces
            )
            for name in names
        }
    finally:
        store.close()


def _acting_over_stack(stack: Any, name: str, n_faces: int) -> np.ndarray:
    """Reduce one stored component to the cells it ever acts on."""
    if stack is None:
        raise ValueError(f"the '{name}' budget is not an array of the store of this run.")
    acting = np.zeros(n_faces, dtype=bool)
    slab = _slab_steps(stack)
    for start in range(0, int(stack.shape[0]), slab):
        acting |= _acting_faces(np.asarray(stack[start : start + slab]), name, n_faces)
        if acting.all():
            break
    return acting


def _slab_steps(stack: Any) -> int:
    """Return how many steps to read at once, from how they were written."""
    chunks = getattr(stack, "chunks", None)
    return int(chunks[0]) if chunks else _DEFAULT_SLAB_STEPS


def _acting_faces(values: np.ndarray, name: str, n_faces: int) -> np.ndarray:
    """Return the faces one block of fluxes carries a finite non-zero value on.

    Every axis but the last is reduced away, so a layered component names the
    cell whichever layer the package sits in, and signed layer fluxes that
    cancel out over the column are still an acting cell.
    """
    if values.shape[-1] != n_faces:
        raise ValueError(
            f"the '{name}' budget holds {values.shape[-1]} values per step, which is not "
            f"the {n_faces} cells the mesh holds."
        )
    carried = np.isfinite(values) & (np.abs(values) > 0.0)
    return np.any(carried, axis=tuple(range(values.ndim - 1)))


def _note(sim: Run, step: int, over: str) -> str:
    """Return the line naming what the classes were read over."""
    if over == "step":
        return f"non-zero per-cell budget at {_step_label(sim, step)}"
    n_steps = sim.n_timesteps or 1
    plural = "" if n_steps == 1 else "s"
    return f"non-zero per-cell budget at any of the {n_steps:,} persisted step{plural}"


def _step_label(sim: Run, step: int) -> str:
    """Return the date of one step, or its rank when the run carries no clock."""
    try:
        index = sim.time_index
    except Exception:
        index = None
    if index is not None and 0 <= step < len(index):
        return f"{index[step]:%Y-%m-%d}"
    return f"step {step + 1}"


def _legend_handles(
    acting: dict[str, np.ndarray],
    several: np.ndarray,
    none: np.ndarray,
) -> list[Patch]:
    """Return one patch per package the store carries, sized by its cells.

    A package present in the store but acting nowhere keeps its entry: that it
    was built and never applied is a result, and dropping it would read as a
    question the figure never asked.
    """
    from matplotlib.patches import Patch

    handles = [
        Patch(
            facecolor=BOUNDARY_PACKAGES[name][1],
            edgecolor="none",
            label=f"{name} ({BOUNDARY_PACKAGES[name][0]}, {_cell_count(mask & ~several)})",
        )
        for name, mask in acting.items()
    ]
    if several.any():
        handles.append(
            Patch(
                facecolor=SEVERAL_COLOR,
                edgecolor="none",
                label=f"several packages ({_cell_count(several)})",
            )
        )
    if none.any():
        handles.append(
            Patch(
                facecolor=GROUND_COLOR,
                edgecolor=GROUND_EDGE,
                label=f"no boundary package ({_cell_count(none)})",
            )
        )
    return handles


def _add_class(
    ax: Axes,
    polygons: list[np.ndarray],
    mask: np.ndarray,
    *,
    color: str,
    zorder: int,
) -> None:
    """Draw one class of cells as a flat colour, or nothing when it is empty."""
    from matplotlib.collections import PolyCollection

    selected = np.flatnonzero(mask)
    if selected.size == 0:
        return
    ax.add_collection(
        PolyCollection(
            [polygons[index] for index in selected],
            facecolors=color,
            edgecolors="none",
            zorder=zorder,
        )
    )
    ax.set_aspect("equal", adjustable="datalim")
    ax.autoscale_view()


def _cell_count(mask: np.ndarray) -> str:
    """Return the size of one group of cells, written for a legend entry."""
    count = int(np.asarray(mask, dtype=bool).sum())
    return f"{count:,} cell" if count == 1 else f"{count:,} cells"


__all__ = ["BOUNDARY_PACKAGES", "BoundaryPackageMap"]
