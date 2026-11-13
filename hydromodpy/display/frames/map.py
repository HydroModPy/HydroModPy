"""Map frame: one value per mesh cell, drawn as filled polygons in the mesh CRS.

It draws a continuous value on a ramp, classes on the categorical palette, and
isolines when the panel or the quantity asks for them. A variable of the table
``sfr_reaches`` is drawn as a line from each reach cell to its downstream cell. The
overlays of the panel are drawn by ``render`` after ``draw``, since they read the
subject.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass

import numpy as np
import pandas as pd
from matplotlib.collections import LineCollection, PolyCollection
from matplotlib.colors import BoundaryNorm, ListedColormap, LogNorm, Normalize, TwoSlopeNorm
from matplotlib.ticker import MaxNLocator
from matplotlib.tri import Triangulation
from pyproj import CRS
from pyproj.exceptions import CRSError

from hydromodpy.display import static, variables
from hydromodpy.display.request import (
    COLUMN_SEPARATOR,
    MAP_TABLE,
    PanelRequest,
    descriptor,
    is_column,
)
from hydromodpy.display.subject import (
    FigureNotApplicable,
    MeshView,
    read_field,
    read_mesh,
    read_table,
)
from hydromodpy.display.theme import Theme
from hydromodpy.results.field_registry import BUDGET_GROUP, BUDGET_SIGN_RULE
from hydromodpy.results.run.view import Run

MAP_COLUMNS = ("cell", "x", "y", "value")
REACH_COLUMNS = (*MAP_COLUMNS, "x_down", "y_down")
LONG_EDGE = 2.2
"""A contour triangle with an edge longer than this many cell sizes is dropped."""


@dataclass(frozen=True, slots=True)
class MapData:
    """What a map draws.

    ``table`` has the columns of ``MAP_COLUMNS``, one row per cell of ``mesh``, in
    mesh order: ``cell`` the face index (int64), ``x`` and ``y`` the cell centre in
    m in the mesh CRS (float64), ``value`` in the display unit (float64, NaN where
    nothing is drawn). Cells outside ``panel.bbox`` are dropped. ``limits`` is the
    colour norm, set by ``render`` for a shared norm across small multiples, else
    None and taken from the values. ``classes`` holds value and name for a
    categorical variable. A variable of the table ``sfr_reaches`` has one row per
    reach instead, with the columns of ``REACH_COLUMNS``: ``cell`` is the reach cell
    and ``x_down``, ``y_down`` the centre of the downstream reach cell (NaN at an
    outlet). ``ramp`` is the name for the default theme, ``draw`` takes the ramp of
    the theme it receives.
    """

    table: pd.DataFrame
    mesh: MeshView
    variable: str
    label: str
    scale: str
    ramp: str
    log: bool
    contours: bool
    classes: tuple[tuple[int, str], ...] = ()
    limits: tuple[float, float] | None = None


# ----------------------------------------------------------------------- data
def _instants(subject: Run, panel: PanelRequest) -> list[int]:
    return list(range(int(subject.n_timesteps or 1)))


def _stored(subject: Run, name: str, panel: PanelRequest) -> np.ndarray:
    """Return the field of one run in the stored unit, after the time operation."""
    layer = panel.layer
    if panel.change is not None:
        first, last = (read_field(subject, name, time=t, layer=layer) for t in panel.change)
        return last - first
    time = "last" if panel.time is None else panel.time
    if panel.reduce is None:
        return read_field(subject, name, time=time, layer=layer)
    stack = np.stack(
        [read_field(subject, name, time=t, layer=layer) for t in _instants(subject, panel)]
    )
    seen = np.isfinite(stack)
    if panel.reduce == "frequency":
        share = (seen & (stack != 0)).mean(axis=0)
        return np.where(seen.any(axis=0), share, np.nan)
    if panel.reduce == "max":
        top = np.where(seen, stack, -np.inf).max(axis=0)
        return np.where(seen.any(axis=0), top, np.nan)
    mean = np.where(seen, stack, 0.0).sum(axis=0) / np.maximum(seen.sum(axis=0), 1)
    return np.where(seen.any(axis=0), mean, np.nan)


def _reaches(subject: Run, panel: PanelRequest, mesh: MeshView) -> pd.DataFrame:
    """One row per reach: its cell centre, the centre of its downstream cell, and a column."""
    column = panel.variable[0].split(COLUMN_SEPARATOR, 1)[1]
    reaches = read_table(subject, MAP_TABLE)
    if column not in reaches.columns:
        raise FigureNotApplicable(
            f"The table {MAP_TABLE!r} has no column {column!r}. It holds: "
            f"{', '.join(map(str, reaches.columns))}."
        )
    cell_of = dict(zip(reaches["reach"], reaches["cell2d"], strict=True))
    rows = []
    for reach in reaches.itertuples():
        if pd.isna(reach.cell2d):
            continue
        down = next((cell_of[d] for d in reach.downstream if pd.notna(cell_of.get(d))), None)
        x, y = mesh.centres[int(reach.cell2d)]
        xd, yd = (np.nan, np.nan) if down is None else mesh.centres[int(down)]
        value = getattr(reach, column)
        rows.append((int(reach.cell2d), x, y, float(value), xd, yd))
    return pd.DataFrame(rows, columns=list(REACH_COLUMNS)).astype({"cell": "int64"})


def data(subject: Run, panel: PanelRequest) -> MapData:
    """Read one variable at one instant on every cell, reduced over layers, in display unit.

    Reads ``read_mesh`` and ``read_field(variable, time=panel.time, layer=panel.layer)``,
    applies ``reduce``, ``change`` and ``against``, divides a ``per_area`` kind by the
    cell areas through ``variables.to_display``, and sets ``contours`` from the panel,
    else from ``QuantityKind.isolines``. A change or a difference is signed, so it takes
    the diverging scale whatever the variable.

    Science choices. A date in ``time`` picks the period ``(start, end]`` that holds it.
    ``reduce = "mean"`` and ``"frequency"`` average the periods one by one, without
    weighting by their length. ``frequency`` counts the periods where the value is finite
    and not zero, so it means little for a variable whose zero is a value, such as a water
    table depth. A signed variable whose finite values all have one sign is drawn on a
    sequential ramp, not on a ramp centred on zero.
    """
    name = panel.variable[0]
    mesh = read_mesh(subject)
    difference = panel.change is not None or panel.against is not None
    log = panel.scale == "log"
    if is_column(name):
        table = _reaches(subject, panel, mesh)
        label = name.split(COLUMN_SEPARATOR, 1)[1]
        scale = "diverging" if (table["value"] < 0).any() else "sequential"
        return MapData(table, mesh, name, label, scale, Theme().ramps[scale], log, False)
    values = _stored(subject, name, panel)
    if panel.against == "observed":
        raise FigureNotApplicable(f"{name!r} has no observed field to subtract on a map.")
    if panel.against is not None:
        raise FigureNotApplicable(
            f"against = {panel.against!r} compares with another run. This comes with the "
            "panel operations of a later version. Subtract two runs with the readers for now."
        )
    frequency = panel.reduce == "frequency"
    if not frequency:
        values = variables.to_display(name, values, area=mesh.areas)
    scale = "diverging" if difference else variables.scale(name)
    seen = values[np.isfinite(values)]
    if (
        scale == "diverging"
        and not difference
        and seen.size
        and (seen.min() >= 0 or seen.max() <= 0)
    ):
        scale = "sequential"
    label = variables.label(name)
    if frequency:
        label, scale = "Share of steps with a non-zero value", "sequential"
    elif difference:
        label = f"{label[0].lower()}{label[1:]}" if label[1:2].islower() else label
        label = f"Change in {label}" if panel.change is not None else f"Difference in {label}"
    contours = panel.contours
    if contours is None:
        contours = variables.kind(name).isolines and not (difference or frequency)
    keep = np.ones(len(values), dtype=bool)
    if panel.bbox is not None:
        x0, y0, x1, y1 = panel.bbox
        keep = (
            (mesh.centres[:, 0] >= x0) & (mesh.centres[:, 0] <= x1)
            & (mesh.centres[:, 1] >= y0) & (mesh.centres[:, 1] <= y1)
        )  # fmt: skip
    table = pd.DataFrame(
        {
            "cell": np.arange(len(values), dtype=np.int64),
            "x": mesh.centres[:, 0],
            "y": mesh.centres[:, 1],
            "value": values,
        }
    )[keep].reset_index(drop=True)
    classes = tuple(descriptor(name).classes) if scale == "categorical" else ()
    log = variables.is_log(name, panel.scale) and scale in ("sequential", "cyclic")
    return MapData(
        table, mesh, name, label, scale, variables.ramp(name, Theme()), log, bool(contours), classes
    )


# ----------------------------------------------------------------------- draw
def _ramp(data: MapData, theme: Theme) -> str:
    registered = not is_column(data.variable) and data.scale == variables.scale(data.variable)
    return variables.ramp(data.variable, theme) if registered else theme.ramps[data.scale]


def _norm(data: MapData, values: np.ndarray) -> Normalize:
    finite = values[np.isfinite(values)]
    lo, hi = data.limits or (
        (float(finite.min()), float(finite.max())) if finite.size else (0.0, 1.0)
    )
    if data.scale == "diverging":
        reach = max(abs(lo), abs(hi)) or 1.0
        return TwoSlopeNorm(vcenter=0.0, vmin=-reach, vmax=reach)
    if data.log:
        positive = finite[finite > 0]
        floor = float(positive.min()) if positive.size else 1.0
        lo = max(lo, floor) if data.limits is None else lo
        return LogNorm(vmin=lo, vmax=max(hi, lo * 10))
    return Normalize(vmin=lo, vmax=hi if hi > lo else lo + 1.0)


def _polygons(mesh: MeshView, cells: np.ndarray) -> list[np.ndarray]:
    return [mesh.vertices[ring[ring >= 0]][:, :2] for ring in mesh.faces[cells]]


def _classes(
    data: MapData, values: np.ndarray, theme: Theme
) -> tuple[np.ndarray, ListedColormap, BoundaryNorm]:
    known = np.array([value for value, _ in data.classes])
    position = np.searchsorted(known, values)
    position = np.where(np.isin(values, known), position, np.nan)
    palette = [theme.categorical[i % len(theme.categorical)] for i in range(len(known))]
    return (
        position,
        ListedColormap(palette),
        BoundaryNorm(np.arange(len(known) + 1) - 0.5, len(known)),
    )


def _isolines(ax: object, data: MapData, theme: Theme) -> None:
    table = data.table
    values = table["value"].to_numpy()
    finite = np.isfinite(values)
    if finite.sum() < 3 or np.ptp(values[finite]) == 0:
        return
    tri = Triangulation(table["x"].to_numpy(), table["y"].to_numpy())
    size = np.sqrt(np.nanmedian(data.mesh.areas))
    corners = tri.triangles
    x, y = table["x"].to_numpy()[corners], table["y"].to_numpy()[corners]
    far = np.hypot(np.ptp(x, axis=1), np.ptp(y, axis=1)) > LONG_EDGE * size
    tri.set_mask(far | ~finite[corners].all(axis=1))
    levels = MaxNLocator(nbins=8).tick_values(values[finite].min(), values[finite].max())
    lines = ax.tricontour(
        tri, np.where(finite, values, 0.0), levels=levels, colors=theme.roles["contour"],
        linewidths=theme.line_width * 0.6, alpha=0.7, zorder=6,
    )  # fmt: skip
    for text in ax.clabel(lines, fmt="%g", fontsize=theme.small, inline=True):
        text.set(**static.text_style(theme))


def _crs_name(crs: str | None) -> str:
    """Return a short name of the CRS for the axis labels, ``Lambert-93`` for RGF93 Lambert-93."""
    if not crs:
        return "mesh CRS"
    try:
        return CRS.from_user_input(crs).name.rsplit(" / ", 1)[-1]
    except CRSError:
        return "mesh CRS"


def draw(ax: object, data: MapData, theme: Theme) -> None:
    """Draw the cells as one PolyCollection, the colorbar on the right, map axes styled.

    Uses ``static.map_axes`` and ``static.colorbar``, a ``LogNorm`` when ``data.log``,
    a ``TwoSlopeNorm`` centred on zero for a diverging scale, and rasterises the cells.
    A categorical variable gets a legend of its class names in place of the colour bar.
    Isolines are drawn when ``data.contours`` is set.
    """
    table = data.table
    values = table["value"].to_numpy(dtype=float)
    cmap, norm = _ramp(data, theme), _norm(data, values)
    if "x_down" in table:
        segments = [
            [(r.x, r.y), (r.x_down, r.y_down)] for r in table.itertuples() if np.isfinite(r.x_down)
        ]
        drawn = np.array([np.isfinite(r.x_down) for r in table.itertuples()])
        artist = LineCollection(
            segments, array=values[drawn], cmap=cmap, norm=norm,
            linewidths=theme.data_line_width * 1.5, capstyle="round",
        )  # fmt: skip
        box = (table["x"].min(), table["y"].min(), table["x"].max(), table["y"].max())
    else:
        polygons = _polygons(data.mesh, table["cell"].to_numpy())
        shown = values
        if data.scale == "categorical":
            shown, cmap, norm = _classes(data, values, theme)
        artist = PolyCollection(
            polygons, array=np.ma.masked_invalid(shown), cmap=cmap, norm=norm,
            edgecolors="none", linewidths=0.0, antialiased=False,
        )  # fmt: skip
        artist.set_rasterized(True)
        flat = np.concatenate(polygons)
        box = (flat[:, 0].min(), flat[:, 1].min(), flat[:, 0].max(), flat[:, 1].max())
    ax.add_collection(artist)
    margin = 0.0 if "x_down" not in table else 0.05 * max(box[2] - box[0], box[3] - box[1])
    extent = (box[0] - margin, box[1] - margin, box[2] + margin, box[3] + margin)
    static.map_axes(ax, theme, extent=extent, crs=_crs_name(data.mesh.crs))
    if data.contours:
        _isolines(ax, data, theme)
    if data.scale == "categorical":
        for i, (_, name) in enumerate(data.classes):
            ax.fill([], [], color=cmap(i), label=name)
        static.legend(ax, theme)
    else:
        static.colorbar(ax.figure, artist, ax, theme, label=data.label)
    if not is_column(data.variable) and descriptor(data.variable).zarr_path.startswith(
        BUDGET_GROUP
    ):
        ax.set_title(
            textwrap.fill(BUDGET_SIGN_RULE, 42), loc="right", **static.text_style(theme, small=True)
        )
