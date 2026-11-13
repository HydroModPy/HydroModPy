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
from matplotlib.colors import to_hex
from matplotlib.ticker import MaxNLocator
from matplotlib.tri import Triangulation
from pyproj import CRS
from pyproj.exceptions import CRSError

from hydromodpy.display import interactive, static, variables
from hydromodpy.display.request import (
    COLUMN_SEPARATOR,
    MAP_TABLE,
    PanelRequest,
    descriptor,
    is_column,
    unknown_column,
)
from hydromodpy.display.subject import (
    Compared,
    FigureNotApplicable,
    MeshView,
    read_field,
    read_mesh,
    read_table,
    refuse_fields,
)
from hydromodpy.display.theme import Theme
from hydromodpy.results.field_registry import (
    BUDGET_GROUP,
    BUDGET_SIGN_RULE,
    COLUMN_REGISTRY,
    REBUILT_FIELDS,
)
from hydromodpy.results.run.view import Run

MAP_COLUMNS = ("cell", "x", "y", "value")
REACH_COLUMNS = (*MAP_COLUMNS, "x_down", "y_down")
FIELDS = (
    "variable", "time", "layer", "overlays", "bbox", "contours", "scale", "share", "reduce",
    "change", "against",
)  # fmt: skip
LABEL_WIDTH = 34
"""A colour bar label is wrapped at this many characters, so a long difference label fits."""
FREQUENCY_HEAD = "share of steps with a non-zero value"
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
def _instants(subject: Run, name: str) -> list[int]:
    """Return every period, or the first alone for a field that does not change in time."""
    if name in REBUILT_FIELDS and "time" not in REBUILT_FIELDS[name].shape:
        return [0]
    return list(range(int(subject.n_timesteps or 1)))


def stored_field(subject: Run, name: str, panel: PanelRequest) -> np.ndarray:
    """Return the field of one run in the stored unit, after the time operation."""
    layer = panel.layer
    if panel.change is not None:
        if panel.time is not None or panel.reduce is not None:
            raise FigureNotApplicable("change replaces time and reduce, so give none of them.")
        first, last = (read_field(subject, name, time=t, layer=layer) for t in panel.change)
        return last - first
    if isinstance(panel.time, list):
        raise FigureNotApplicable("A field is read at one instant, not over a window of time.")
    time = "last" if panel.time is None else panel.time
    if panel.reduce is None:
        return read_field(subject, name, time=time, layer=layer)
    stack = np.stack(
        [read_field(subject, name, time=t, layer=layer) for t in _instants(subject, name)]
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
    if panel.variable[0] not in COLUMN_REGISTRY:
        raise FigureNotApplicable(unknown_column(panel.variable[0]))
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


def _reach_map(subject: Run, panel: PanelRequest, mesh: MeshView) -> MapData:
    """Draw one column of the reaches, the label and the classes coming from its registry row."""
    name = panel.variable[0]
    table = _reaches(subject, panel, mesh)
    label = variables.label(name)
    log = panel.scale == "log"
    if variables.scale(name) == "categorical":
        classes = tuple((int(v), str(int(v))) for v in sorted(table["value"].dropna().unique()))
        return MapData(table, mesh, name, label, "categorical", "", log, False, classes)
    scale = "diverging" if (table["value"] < 0).any() else "sequential"
    return MapData(table, mesh, name, label, scale, Theme().ramps[scale], log, False)


def _difference(subject: Compared, name: str, panel: PanelRequest) -> np.ndarray:
    """Return the run minus its reference in the stored unit, each after its own time operation."""
    if variables.scale(name) == "categorical" and panel.reduce != "frequency":
        raise FigureNotApplicable(
            f"{name!r} is categorical, so two runs are subtracted through reduce = 'frequency'."
        )
    return stored_field(subject.run, name, panel) - stored_field(subject.reference, name, panel)


def data(subject: Run | Compared, panel: PanelRequest) -> MapData:
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
    refuse_fields("map", panel, FIELDS)
    name = panel.variable[0]
    if panel.against == "observed":
        raise FigureNotApplicable(f"{name!r} has no observed field to subtract on a map.")
    compared = isinstance(subject, Compared)
    if panel.against is not None and not compared:
        raise FigureNotApplicable(
            f"against = {panel.against!r} compares with another run, which render hands over "
            "resolved. Draw the figure through run.figure or render."
        )
    run = subject.run if compared else subject
    mesh = read_mesh(run)
    difference = panel.change is not None or panel.against is not None
    log = panel.scale == "log"
    if is_column(name):
        if compared:
            raise FigureNotApplicable("A column of the reaches cannot be subtracted between runs.")
        return _reach_map(subject, panel, mesh)
    values = _difference(subject, name, panel) if compared else stored_field(subject, name, panel)
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
        label, scale = variables.FREQUENCY_LABEL, "diverging" if difference else "sequential"
    elif difference:
        label = f"{label[0].lower()}{label[1:]}" if label[1:2].islower() else label
        label = f"Change in {label}" if panel.change is not None else f"Difference in {label}"
    if compared:
        head, unit = variables.label_parts(name)
        head = FREQUENCY_HEAD if frequency else f"{head[:1].lower()}{head[1:]}"
        label = variables.join_unit(
            f"Difference in {head}, {subject.run.name} - {subject.reference.name}",
            "" if frequency else unit,
        )
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
    if data.scale == "categorical":
        return ""
    registered = not is_column(data.variable) and data.scale == variables.scale(data.variable)
    return variables.ramp(data.variable, theme) if registered else theme.ramps[data.scale]


def _polygons(mesh: MeshView, cells: np.ndarray) -> list[np.ndarray]:
    return [mesh.vertices[ring[ring >= 0]][:, :2] for ring in mesh.faces[cells]]


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


def crs_name(crs: str | None) -> str:
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
    cmap = _ramp(data, theme)
    norm = variables.color_norm(data.scale, data.log, values, data.limits)
    if "x_down" in table:
        shown = values
        if data.scale == "categorical":
            shown, cmap, norm = variables.class_scale(values, data.classes, theme)
        segments = [
            [(r.x, r.y), (r.x_down, r.y_down)] for r in table.itertuples() if np.isfinite(r.x_down)
        ]
        drawn = np.array([np.isfinite(r.x_down) for r in table.itertuples()])
        artist = LineCollection(
            segments, array=shown[drawn], cmap=cmap, norm=norm,
            linewidths=theme.data_line_width * 1.5, capstyle="round",
        )  # fmt: skip
        box = (table["x"].min(), table["y"].min(), table["x"].max(), table["y"].max())
    else:
        polygons = _polygons(data.mesh, table["cell"].to_numpy())
        shown = values
        if data.scale == "categorical":
            shown, cmap, norm = variables.class_scale(values, data.classes, theme)
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
    static.map_axes(ax, theme, extent=extent, crs=crs_name(data.mesh.crs))
    if data.contours:
        _isolines(ax, data, theme)
    if data.scale == "categorical":
        for i, (_, name) in enumerate(data.classes):
            ax.fill([], [], color=cmap(i), label=name)
        static.legend(ax, theme)
    else:
        static.colorbar(ax.figure, artist, ax, theme, label=textwrap.fill(data.label, LABEL_WIDTH))
    if not is_column(data.variable) and descriptor(data.variable).zarr_path.startswith(
        BUDGET_GROUP
    ):
        ax.set_title(
            textwrap.fill(BUDGET_SIGN_RULE, 42), loc="right", **static.text_style(theme, small=True)
        )


# ---------------------------------------------------------------- interactive
def interactive_color(data: MapData, theme: Theme) -> tuple[np.ndarray, dict]:
    """Return the intensity of each row of the table and the colour keywords of a plotly trace.

    The limits, the centre of a diverging scale, the classes and the label are those of the
    static figure. A log scale is drawn on the log10 of the values, with the ticks written
    back in the unit. A row that cannot take a colour has NaN intensity.
    """
    values = data.table["value"].to_numpy(dtype=float)
    label = {"text": interactive.plain(textwrap.fill(data.label, LABEL_WIDTH).replace("\n", "<br>")), "side": "right"}  # fmt: skip
    if data.scale == "categorical":
        shown, cmap, _ = variables.class_scale(values, data.classes, theme)
        n = len(data.classes)
        colors = [to_hex(cmap(i)) for i in range(n)]
        bar = {"title": label, "tickvals": list(range(n)), "ticktext": [name for _, name in data.classes]}  # fmt: skip
        keys = {"colorscale": interactive.class_colorscale(colors), "cmin": -0.5, "cmax": n - 0.5}
        return shown, {**keys, "colorbar": bar}
    norm = variables.color_norm(data.scale, data.log, values, data.limits)
    low, high = norm.vmin, norm.vmax
    keys = {"colorscale": interactive.colorscale(_ramp(data, theme))}
    if data.log:
        shown = np.where(values > 0, np.log10(np.where(values > 0, values, 1.0)), np.nan)
        low, high = np.log10(low), np.log10(high)
        ticks = np.linspace(low, high, 5)
        bar = {"title": label, "tickvals": ticks, "ticktext": [f"{10**t:.3g}" for t in ticks]}
    else:
        shown, bar = values, {"title": label}
    if data.scale == "diverging":
        keys["cmid"] = 0.0
    return shown, {**keys, "cmin": low, "cmax": high, "colorbar": bar}


def hover_text(data: MapData) -> np.ndarray:
    """Return the hover text of each row of the table: the cell and its value or class name."""
    names = dict(data.classes)
    return np.array(
        [
            f"cell {c}: {names.get(int(v), v) if names else format(v, '.4g')}"
            for c, v in zip(data.table["cell"], data.table["value"], strict=True)
        ],
        dtype=object,
    )


def draw_interactive(data: MapData, theme: Theme) -> tuple[list, dict]:
    """Return the cells as one plotly ``Mesh3d`` seen from above, and the scene settings.

    Each cell is a fan of triangles with its own vertices, so a hover names the cell and its
    value. Cells without a value are left out. The overlays a map takes by default (outline,
    outlet, scale bar) are not drawn. A table of reaches is refused, and so is a
    mesh of more cells than ``interactive.MAX_CELLS``.
    """
    import plotly.graph_objects as go

    if "x_down" in data.table:
        raise FigureNotApplicable("The reaches of a table are drawn by the static engine only.")
    shown, colors = interactive_color(data, theme)
    kept = np.isfinite(shown)
    interactive.refuse_large(int(kept.sum()))
    table = data.table[kept]
    x, y, triangles, k = interactive.fan(data.mesh, table["cell"].to_numpy())
    mesh = go.Mesh3d(
        x=x.astype("float32"), y=y.astype("float32"), z=np.zeros(len(x), "float32"),
        i=triangles[:, 0].astype("int32"), j=triangles[:, 1].astype("int32"),
        k=triangles[:, 2].astype("int32"), intensity=np.repeat(shown[kept], k).astype("float32"),
        text=np.repeat(hover_text(data)[kept], k), hoverinfo="text", flatshading=True, **colors,
    )  # fmt: skip
    crs = crs_name(data.mesh.crs)
    span = (x.max() - x.min(), y.max() - y.min())
    axis = {"showgrid": False, "showspikes": False}
    scene = {
        "aspectmode": "manual",
        "aspectratio": {"x": span[0] / max(span), "y": span[1] / max(span), "z": 0.01},
        "camera": {"eye": {"x": 0, "y": 0, "z": 2}, "up": {"x": 0, "y": 1, "z": 0}, "projection": {"type": "orthographic"}},  # fmt: skip
        "xaxis": {**axis, "title": f"x ({crs}, m)"},
        "yaxis": {**axis, "title": f"y ({crs}, m)"},
        "zaxis": {"visible": False, "range": [-1, 1]},
        "dragmode": "pan",
    }  # fmt: skip
    return [mesh], {"scene": scene}
