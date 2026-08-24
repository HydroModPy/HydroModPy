"""Which boundary package acts on which cell, read from what the model did.

There is no per-cell package table in the store, and there should not be: a
package a builder declared and the solver never applied would still be in it.
What the store holds is the per-cell budget, one array per component under
``budget/``. A cell where a component carries a non-zero flux is a cell that
package acts on, whichever backend solved the model and whichever section of
the configuration put the package there.

A component the store carries and no cell of which is ever non-zero is drawn
nowhere and reported as zero cells, and that is all this figure knows about
it. Why it is empty is not in the store: the reference run carries a
``constant_head`` array of zeros with no constant-head cell anywhere in it and
no CHD in its configuration, because MODFLOW-NWT writes the record whether or
not the package exists. So the zero is reported as the measurement it is, in
the legend and in the note at the foot, and nothing is read into it here.

Overlaps are drawn, not resolved. A cell that two packages act on (a drain on
a streambed cell, a well under a lake) takes its own class rather than the
colour of whichever package happens to be painted last, so the map never
quietly hides a package behind another.

A boundary package acts on a fraction of a mesh, and that fraction is what
makes this map hard to read rather than wrong: 770 drain cells over 60 395 is
a one-cell-wide network drawn on a page a few inches wide, where one cell is a
fraction of a pixel. Three things earn that area back. The view is framed on
the catchment and the packages rather than on the buffered mesh. Every acting
cell carries a page-space mark, so a class survives whatever size the page is
printed at. And the legend carries the cell count of every package, so an
almost empty page is read as the 1.3 % of the mesh it is rather than guessed
at. The counts are exact; the marks are deliberately wider than the cells they
stand for.

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

LEGEND_SIZE = 9.0
"""Point size of the legend, which is what the map is left with after it.

Outside the axes, and with the axes box locked to the aspect of the data, the
legend reserves a share of the page fixed in points: it does not shrink with
the figure while the axes does, so a larger size costs the map far more than
the few points it gains the reader. Measured on the reference catchment: at
the shipped 9.5 x 7.5 in, 12.5 pt leaves the map 48 % of the page and 9 pt
leaves it 58 %; at 6 x 4.5 in, 12.5 pt leaves it 7 % and 9 pt leaves it 40 %.
Below the axes rather than beside it is no better: it takes the same points
off the height, which an equal aspect turns straight back into width.
"""

MARK_POINTS = 2.4
"""Side, in typographic points, of the mark drawn over every acting cell.

A page unit, not a ground unit, and that is the whole point: a 50 m cell on a
12 km map printed five inches wide is 1.5 points across, and drops under a
pixel as soon as the figure is scaled down for a report. The mark is a square
of this side centred on the cell and painted in the colour of the class it
belongs to, so it can only ever widen a class, never narrow one: where the
cells are already larger than it, it is invisible inside the one it covers.
"""

VIEW_MARGIN = 0.02
"""Padding around the cropped view, as a fraction of its longer side."""

_NOTE_BOX = {"facecolor": "white", "alpha": 0.9, "edgecolor": GROUND_EDGE}

_DEFAULT_SLAB_STEPS = 64
"""Steps read at once from a store that does not declare a time chunk."""

_WATERSHED_FEATURE = "watershed"
"""The delineated catchment, under the name the geographic step persists it."""


@register
class BoundaryPackageMap(BaseFigure):
    """Categorical map of the boundary package acting on each cell.

    ``over="run"`` (the default) asks which cells a package acts on at all;
    ``over="step"`` asks which ones exchange water at ``timestep``. The outlet
    is marked because whether it sits in a package, and in which one, is the
    first thing a reader checks on this map.

    Read it as where each package *exchanges* water over the window. A
    component whose cells are all zero is drawn nowhere and counted as zero
    cells, which is what was measured; whether the package was ever built is
    not something this store answers.

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
        default_figsize=(9.5, 7.5),
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
            _add_marked_class(
                ax,
                polygons,
                acting[name] & ~several,
                color=BOUNDARY_PACKAGES[name][1],
                zorder=zorder,
            )
        _add_marked_class(ax, polygons, several, color=SEVERAL_COLOR, zorder=len(acting) + 2)

        overlay_watershed_contour(ax, sim, color="#404040", linewidth=0.9, alpha=0.7)
        apply_overlays(ax, sim, ("outlet",), timestep=step)
        _crop_to_subject(ax, sim, polygons, ~none)
        style_relative_km_axes(ax)
        # Set after the crop, and against what style_relative_km_axes leaves:
        # an equal aspect adjusted on the data limits widens the view back to
        # the shape of the axes box, which puts the empty bands the crop just
        # removed straight back on the page.
        ax.set_aspect("equal", adjustable="box")
        ax.set_title(f"{self.spec.title} - {sim.name or sim.sim_id}")
        overlay_handles, _labels = ax.get_legend_handles_labels()
        ax.legend(
            handles=_legend_handles(acting, several, none) + overlay_handles,
            loc="upper left",
            bbox_to_anchor=LEGEND_ANCHOR,
            fontsize=LEGEND_SIZE,
            framealpha=0.9,
        )
        ax.annotate(
            _note(sim, step, over, acting_cells=int((~none).sum()), n_faces=n_faces),
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


def _note(sim: Run, step: int, over: str, *, acting_cells: int, n_faces: int) -> str:
    """Return what was read, how much of it answered, and what a zero means.

    The second line is what a reader looking at an almost empty page needs:
    the share is small because a boundary package is a small object on a mesh.
    The third one reads the zero entries of the legend for what they are, a
    measurement on the stored budget and not a statement about the model.
    """
    if over == "step":
        read = f"non-zero per-cell budget at {_step_label(sim, step)}"
    else:
        n_steps = sim.n_timesteps or 1
        plural = "" if n_steps == 1 else "s"
        read = f"non-zero per-cell budget at any of the {n_steps:,} persisted step{plural}"
    share = 100.0 * acting_cells / n_faces if n_faces else 0.0
    return (
        f"{read}\n"
        f"{acting_cells:,} of {n_faces:,} mesh cells ({share:.1f} %) exchange water\n"
        "0 cells means no cell exchanges water on that component"
    )


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

    A component present in the store but acting nowhere keeps its entry, with
    a count of zero: the run was asked about that package and the answer was
    no cell, which is a result. Dropping the entry would leave a reader unable
    to tell that from a package never looked for.
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


def _add_marked_class(
    ax: Axes,
    polygons: list[np.ndarray],
    mask: np.ndarray,
    *,
    color: str,
    zorder: int,
) -> None:
    """Draw one acting class, and a page-space mark over each of its cells.

    The cells are the truth and are drawn first; the marks are painted on top
    of them, in the same colour, and are what keeps the class on the page once
    the mesh is finer than the print. See :data:`MARK_POINTS`.
    """
    selected = np.flatnonzero(mask)
    if selected.size == 0:
        return
    _add_class(ax, polygons, mask, color=color, zorder=zorder)
    centres = np.array([polygons[index].mean(axis=0) for index in selected], dtype="float64")
    ax.scatter(
        centres[:, 0],
        centres[:, 1],
        s=MARK_POINTS**2,
        marker="s",
        c=color,
        linewidths=0.0,
        zorder=zorder,
    )


def _crop_to_subject(
    ax: Axes,
    sim: Run,
    polygons: list[np.ndarray],
    subject: np.ndarray,
) -> None:
    """Frame the map on the catchment, widened to every cell a package acts on.

    A mesh is a buffered box and a boundary package is a handful of cells in
    it: on the reference catchment the delineated basin is 43 % of the mesh,
    and the rest of the page is background the map is not about. What the view
    drops is only ever background, since it is widened to hold every acting
    cell, so the crop can never hide a class; and the counts in the legend and
    in the note stay counts of the model rather than of the frame.

    A run with no delineation is drawn whole. The mesh is then the only
    support it declares, and framing on the packages alone would answer a map
    of six well cells with a close-up of six well cells.

    So is a run whose delineation lands off the mesh. The bounds are taken as
    they are stored, in whatever CRS they were stored in, and a delineation
    that came back in degrees while the mesh is in metres would frame the map
    on ground that holds no cell: an empty page, and the reader with no way of
    knowing why. The whole mesh is a worse frame than the catchment, and a
    readable one.
    """
    catchment = _catchment_box(sim)
    mesh = _mesh_box(polygons)
    if catchment is None or mesh is None or not _overlaps(catchment, mesh):
        return
    boxes = [box for box in (catchment, _subject_box(polygons, subject)) if box]
    x0 = min(box[0] for box in boxes)
    x1 = max(box[1] for box in boxes)
    y0 = min(box[2] for box in boxes)
    y1 = max(box[3] for box in boxes)
    if x1 <= x0 or y1 <= y0:
        return
    pad = VIEW_MARGIN * max(x1 - x0, y1 - y0)
    ax.set_xlim(x0 - pad, x1 + pad)
    ax.set_ylim(y0 - pad, y1 + pad)


def _subject_box(
    polygons: list[np.ndarray],
    subject: np.ndarray,
) -> tuple[float, float, float, float] | None:
    """Return the bounds of every cell a package acts on, None when none do."""
    selected = np.flatnonzero(subject)
    if selected.size == 0:
        return None
    return _corner_box(np.concatenate([polygons[index] for index in selected]))


def _mesh_box(polygons: list[np.ndarray]) -> tuple[float, float, float, float] | None:
    """Return the bounds of the whole mesh, None when it holds no face."""
    return _corner_box(np.concatenate(polygons)) if polygons else None


def _corner_box(corners: np.ndarray) -> tuple[float, float, float, float]:
    """Return the ``(x0, x1, y0, y1)`` bounds of a stack of polygon corners."""
    return (
        float(corners[:, 0].min()),
        float(corners[:, 0].max()),
        float(corners[:, 1].min()),
        float(corners[:, 1].max()),
    )


def _overlaps(
    box: tuple[float, float, float, float],
    other: tuple[float, float, float, float],
) -> bool:
    """Return whether two ``(x0, x1, y0, y1)`` boxes share any ground."""
    return box[0] <= other[1] and other[0] <= box[1] and box[2] <= other[3] and other[2] <= box[3]


def _catchment_box(sim: Run) -> tuple[float, float, float, float] | None:
    """Return the bounds of the delineated catchment, None without one."""
    try:
        gdf = sim.geographic(_WATERSHED_FEATURE)
    except Exception:
        return None
    if gdf is None or gdf.empty:
        return None
    x0, y0, x1, y1 = (float(value) for value in gdf.total_bounds)
    return (x0, x1, y0, y1)


def _cell_count(mask: np.ndarray) -> str:
    """Return the size of one group of cells, written for a legend entry."""
    count = int(np.asarray(mask, dtype=bool).sum())
    return f"{count:,} cell" if count == 1 else f"{count:,} cells"


__all__ = ["BOUNDARY_PACKAGES", "BoundaryPackageMap"]
