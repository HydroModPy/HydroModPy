"""Section frame: a vertical cut through the model along a line, distance against elevation.

It draws the cells crossed by the line as one rectangle per cell and per layer,
coloured by a layered variable, with the land surface, the model base and the
layer interfaces. A variable without a layer axis whose values are elevations
(``watertable_elevation``, ``topography``) is drawn as a stepped line over the empty
cells. Under a water table the cells are filled as the saturated zone, and above it
as the unsaturated zone. It draws one instant and never a map overlay: the only
context it knows is the lake, barrier and seepage marks it reads itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
import shapely
from matplotlib.collections import PolyCollection

from hydromodpy.display import static, variables
from hydromodpy.display.frames.map import stored_field
from hydromodpy.display.request import PanelRequest, descriptor
from hydromodpy.display.subject import (
    FigureNotApplicable,
    period_text,
    read_field,
    read_mesh,
    read_network,
    refuse_fields,
)
from hydromodpy.display.theme import Theme, colormap
from hydromodpy.results.run.view import Run

FIELDS = ("variable", "time", "overlays", "line", "bbox", "scale", "share", "reduce", "change")
SECTION_COLUMNS = ("cell", "layer", "start", "end", "top", "bottom", "value")
LINE_COLUMNS = ("cell", "start", "end", "value")
SECTION_MARKS = ("lake", "barrier", "seepage")
"""Overlay names a section draws itself, as spans or points along the line."""
CELL_MARKS = {"lake": "lake", "seepage": "seepage_mask"}
"""The marks read from a field: the cells where it is not zero at the instant."""
DEEP = 2.0
"""A water table section is cut under the water table when the body under its lowest point
is more than this many times thicker than the ground above that point."""
HEADINGS = (
    "west to east", "south-west to north-east", "south to north", "south-east to north-west",
    "east to west", "north-east to south-west", "north to south", "north-west to south-east",
)  # fmt: skip
"""The way a line runs, by sector of 45 degrees counted from the east towards the north."""


@dataclass(frozen=True, slots=True)
class SectionData:
    """What a section draws.

    ``table`` has the columns of ``SECTION_COLUMNS``, one row per piece of cell
    crossed by the line and per layer, ordered by ``start`` then ``layer``. ``cell``
    is the face index (int64) and ``layer`` the layer index from 0 at the top
    (int64). ``start`` and ``end`` are the distances in m along the line where it
    enters and leaves the cell, so a cell crossed twice gives two rows. ``top`` and
    ``bottom`` are the elevations of the layer in m from ``MeshView.interfaces``.
    ``value`` is the variable in the display unit (float64, NaN for an inactive or
    dry cell, and NaN everywhere when the variable has no layer axis).

    ``line`` holds the variable drawn as a line over the cells, with the columns
    of ``LINE_COLUMNS`` and one row per piece of cell: the variable itself when it
    has no layer axis, else ``watertable_elevation`` at the same instant when the
    variable is ``head`` and the run holds it, else None. ``line_label`` is its
    legend text, and ``water`` says that it is a water table. ``marks`` holds
    ``(overlay name, start, end)`` spans in m for the names of ``SECTION_MARKS`` the
    panel asked, one span per cell for ``seepage``. ``trace`` is the line used, points
    ``(x, y)`` in m in the mesh CRS. ``caption`` says the way the line runs and
    ``period`` the time drawn. ``window`` is the ``bbox`` of the panel, ``(start, low,
    end, high)`` in m along the line and in elevation. ``label``, ``scale``, ``ramp``, ``log``, ``classes`` and ``limits``
    mean what they mean on ``MapData``, so a shared norm reaches a section as it
    reaches a map.
    """

    table: pd.DataFrame
    variable: str
    label: str
    scale: str
    ramp: str
    log: bool
    trace: tuple[tuple[float, float], ...]
    line: pd.DataFrame | None = None
    line_label: str = ""
    marks: tuple[tuple[str, float, float], ...] = ()
    classes: tuple[tuple[int, str], ...] = ()
    limits: tuple[float, float] | None = None
    water: bool = False
    caption: str = ""
    period: str = ""
    window: tuple[float, float, float, float] | None = None


def data(subject: Run, panel: PanelRequest) -> SectionData:
    """Read one variable on every layer of the cells the line crosses, at one instant.

    The line is ``panel.line``, else the straight line from ``MeshView.outlet`` to
    the centre of the catchment cell farthest from it. A run without an outlet and
    without ``line`` is refused, naming ``line``. The pieces come from the exact
    intersection of the line with each face polygon of ``read_mesh``, so their
    lengths sum to the length of the line inside the mesh. A line that runs along an
    edge shared by two cells is kept for the lower cell index, so pieces never overlap.

    ``time`` is one instant, ``"last"`` when unset, and a static field ignores it.
    A list of instants is split by ``render`` through ``facet = "time"`` and refused
    here. A layered variable is read with ``read_field(..., layer=k)`` for every
    layer of the run. A ``layer`` is refused, since the section shows every layer. A
    variable without a layer axis is accepted only when its quantity is ``head`` or
    ``elevation``, because the vertical axis is an elevation; any other one is
    refused, pointing at a map. ``reduce`` and ``change`` follow the map rules;
    ``against``, ``cumulative``, ``observed``, ``scores``, ``stack`` and ``by`` are
    refused. ``bbox`` is the window drawn, distances along the line and elevations. An overlay outside ``SECTION_MARKS`` is refused. ``lake``
    and ``seepage`` mark the cells whose ``lake`` term or ``seepage_mask`` is not zero
    at the instant. ``seepage`` is marked only where a water table is drawn, and a run
    without the mask has no such mark. ``barrier`` marks the
    places where a feature of ``read_network(run, "barrier")`` crosses the line.
    The scale, ramp, log and classes follow ``variables`` as on a map.

    Raises ``FigureNotApplicable`` when the line misses the mesh, when the mesh has
    no ``interfaces``, or for any refusal above.
    """
    name = panel.variable[0]
    refuse_fields("section", panel, FIELDS)
    found = _check(panel, name)
    layered = "layer" in found.shape
    mesh = read_mesh(subject)
    if mesh.interfaces is None:
        raise FigureNotApplicable("The mesh holds no layer interfaces, so it has no section.")
    trace = _trace(panel, mesh)
    pieces = _pieces(mesh, trace)
    if not len(pieces):
        raise FigureNotApplicable("The line does not cross the mesh.")
    cells = pieces["cell"].to_numpy()
    table = _layer_table(subject, panel, mesh, pieces, name if layered else None)
    line, line_label = None, ""
    if not layered:
        line = pieces.assign(value=_read(subject, panel, mesh, name)[cells])
        line_label = "Water table" if found.quantity == "head" else variables.label(name)
    elif found.quantity == "head":
        try:
            water = _read(subject, panel, mesh, "watertable_elevation")[cells]
            line, line_label = pieces.assign(value=water), "Water table"
        except FigureNotApplicable:
            pass  # A run without a water table draws the cells alone.
    if line is not None:
        line = line[list(LINE_COLUMNS)].sort_values("start", ignore_index=True)
    water = line is not None and found.quantity == "head"
    scale, label, log = _scale(panel, name, layered, table["value"].dropna().to_numpy())
    classes = tuple(found.classes) if scale == "categorical" else ()
    return SectionData(
        table, name, label, scale, variables.ramp(name, Theme()) if layered else "", log,
        trace, line, line_label, _marks(subject, panel, pieces, trace, water), classes,
        water=water,
        caption=_caption(trace),
        period=period_text(subject, panel) if "time" in found.shape else "",
        window=panel.bbox,
    )  # fmt: skip


def _caption(trace) -> str:
    """Say the way the line runs and its length, as ``north to south, 2.1 km``."""
    (x0, y0), (x1, y1) = trace[0], trace[-1]
    sector = int(((np.degrees(np.arctan2(y1 - y0, x1 - x0)) + 22.5) % 360.0) // 45.0)
    length = shapely.LineString(trace).length
    span = f"{length / 1000.0:.1f} km" if length >= 1000.0 else f"{length:.0f} m"
    return f"{HEADINGS[sector]}, {span}"


def _check(panel: PanelRequest, name: str) -> Any:
    """Refuse what a section cannot show and return the descriptor of the variable."""
    if isinstance(panel.time, list):
        raise FigureNotApplicable("A section shows one instant. Use facet = 'time' for several.")
    for overlay in panel.overlays or ():
        if overlay not in SECTION_MARKS:
            raise FigureNotApplicable(
                f"A section draws only the marks {', '.join(SECTION_MARKS)}, not {overlay!r}."
            )
    found = descriptor(name)
    if "layer" not in found.shape and found.quantity not in ("head", "elevation"):
        raise FigureNotApplicable(
            f"{name!r} has no layer axis and is not an elevation, so a section cannot "
            "place it. Draw it as a map."
        )
    return found


def _read(subject: Run, panel: PanelRequest, mesh, name: str, layer: int | None = None):
    """Return one layer of a field in the display unit, or the raw share for ``frequency``."""
    values = stored_field(subject, name, panel.model_copy(update={"layer": layer}))
    if panel.reduce == "frequency":
        return values
    return variables.to_display(name, values, area=mesh.areas)


def _layer_table(
    subject: Run, panel: PanelRequest, mesh, pieces: pd.DataFrame, name
) -> pd.DataFrame:
    """Return one row per piece and layer, with the layer elevations and the value."""
    cells = pieces["cell"].to_numpy()
    rows = []
    for k in range(len(mesh.interfaces) - 1):
        value = np.nan if name is None else _read(subject, panel, mesh, name, k)[cells]
        rows.append(
            pieces.assign(
                layer=k, top=mesh.interfaces[k, cells], bottom=mesh.interfaces[k + 1, cells],
                value=value,
            )
        )  # fmt: skip
    table = pd.concat(rows).sort_values(["start", "layer"], kind="stable", ignore_index=True)
    return table[list(SECTION_COLUMNS)].astype(
        {"cell": "int64", "layer": "int64", "value": "float64"}
    )


def _scale(
    panel: PanelRequest, name: str, layered: bool, seen: np.ndarray
) -> tuple[str, str, bool]:
    """Return the colour scale, the label and the log flag, by the rules of the map frame."""
    scale, label = (variables.scale(name) if layered else "sequential"), variables.label(name)
    if panel.reduce == "frequency":
        label, scale = variables.FREQUENCY_LABEL, "sequential"
    elif panel.change is not None:
        scale, label = "diverging", f"Change in {label[0].lower()}{label[1:]}"
    if scale == "diverging" and panel.change is None and seen.size:
        scale = "sequential" if (seen.min() >= 0 or seen.max() <= 0) else scale
    log = layered and variables.is_log(name, panel.scale) and scale in ("sequential", "cyclic")
    return scale, label, log


def _trace(panel: PanelRequest, mesh) -> tuple[tuple[float, float], ...]:
    """Return the line of the panel, else the outlet to the farthest catchment centre."""
    if panel.line:
        return tuple((float(x), float(y)) for x, y in panel.line)
    if mesh.outlet is None:
        raise FigureNotApplicable("The run has no outlet, so a section needs a `line`.")
    centres = mesh.centres[mesh.zones["catchment"]]
    far = centres[np.hypot(*(centres - np.array(mesh.outlet)).T).argmax()]
    return (tuple(mesh.outlet), (float(far[0]), float(far[1])))


def _pieces(mesh, trace) -> pd.DataFrame:
    """Cut every face by the line, one row per piece with its start and end distance."""
    line = shapely.LineString(trace)
    rings = [mesh.vertices[ring[ring >= 0]] for ring in mesh.faces]
    polygons = np.array(
        [shapely.Polygon(r) if len(r) > 2 else shapely.Polygon() for r in rings], dtype=object
    )
    rows = []
    for cell in np.flatnonzero(shapely.intersects(polygons, line)):
        edge = polygons[cell].boundary.buffer(1e-6)
        for part in shapely.get_parts(shapely.intersection(polygons[cell], line)):
            if part.length < 1e-6:
                continue
            ends = [line.project(shapely.Point(c)) for c in part.coords]
            rows.append((cell, min(ends), max(ends), edge.covers(part)))
    frame = pd.DataFrame(rows, columns=["cell", "start", "end", "edge"])
    # A piece along an edge of two cells is kept for the lower cell only.
    twice = frame[frame["edge"]].round(3).duplicated(["start", "end"])
    return frame.drop(index=twice[twice].index)[["cell", "start", "end"]].astype({"cell": "int64"})


def _marks(subject, panel, pieces, trace, water: bool) -> tuple[tuple[str, float, float], ...]:
    marks = []
    time = "last" if panel.time is None else panel.time
    for name in panel.overlays or ():
        if name not in CELL_MARKS:
            continue
        # Seepage is asked by default, so it never refuses a section.
        if name == "seepage" and not (water and subject.has_field(CELL_MARKS[name])):
            continue
        values = read_field(subject, CELL_MARKS[name], time=time)[pieces["cell"].to_numpy()]
        hit = pieces[np.isfinite(values) & (values != 0)].sort_values("start")
        spans: list[list[float]] = []
        for start, end in zip(hit["start"], hit["end"], strict=True):
            # A lake is one span over its cells, a seepage cell keeps its own land elevation.
            if name == "lake" and spans and start <= spans[-1][1] + 1e-6:
                spans[-1][1] = max(spans[-1][1], end)
            else:
                spans.append([start, end])
        marks += [(name, start, end) for start, end in spans]
    if "barrier" in (panel.overlays or ()):
        line = shapely.LineString(trace)
        crossing = shapely.intersection(read_network(subject, "barrier").geometry.union_all(), line)
        for part in shapely.get_parts(crossing):
            if not part.is_empty:
                at = [line.project(shapely.Point(c)) for c in part.coords]
                marks.append(("barrier", min(at), max(at)))
    return tuple((n, float(a), float(b)) for n, a, b in marks)


# ----------------------------------------------------------------------- draw
def _stepped(table: pd.DataFrame, column: str) -> tuple[np.ndarray, np.ndarray]:
    x = table[["start", "end"]].to_numpy().ravel()
    return x, np.repeat(table[column].to_numpy(dtype=float), 2)


def _profile(table: pd.DataFrame, column: str, smooth: bool) -> tuple[np.ndarray, np.ndarray]:
    """Return ``column`` along the line: through the middle of each cell, or as steps."""
    if not smooth:
        return _stepped(table, column)
    start, end = table["start"].to_numpy(), table["end"].to_numpy()
    values = table[column].to_numpy(dtype=float)
    return (
        np.concatenate([start[:1], (start + end) / 2, end[-1:]]),
        np.concatenate([values[:1], values, values[-1:]]),
    )


def _window(data: SectionData, land, water, base) -> tuple[float, float, float, float]:
    """Return the window drawn, ``(start, low, end, high)`` in m.

    The window asked wins. Else the whole model is drawn, unless the section shows a
    water table alone over a body more than ``DEEP`` times thicker than what lies above
    its lowest point. The view then keeps as much aquifer under that point as there is
    ground above it, since the model base would flatten the water table.
    """
    if data.window is not None:
        return data.window
    start, end = float(data.table["start"].min()), float(data.table["end"].max())
    low, high = float(np.nanmin(base)), float(np.nanmax(land))
    if water is not None and np.isfinite(water).any():
        above = high - float(np.nanmin(water))
        if float(np.nanmin(water)) - low > DEEP * above > 0:
            low = float(np.nanmin(water)) - above
    pad = 0.04 * (high - low or 1.0)
    return start, low - pad, end, high + pad


def draw(ax: Any, data: SectionData, theme: Theme) -> None:
    """Draw the cells as one PolyCollection of rectangles, the colorbar on the right.

    Rectangles are ``(start, bottom)`` to ``(end, top)``, rasterised, with the
    norm rules of the map frame (``LogNorm``, ``TwoSlopeNorm`` centred on zero,
    categorical classes in a legend). Over them: the layer interfaces as thin
    dashed lines, the land surface, the model base, then ``line``. When a cell is
    coloured the lines are steps that follow the cells. When none is, the lines run
    through the middle of each cell, a water table takes the ``water_table`` role,
    the body under it is filled as the saturated zone and the ground above it as the
    unsaturated zone. A dry column is unsaturated down to the base. Each mark is a
    span of the ``bounds`` role with its name in the legend, and a seepage cell is a
    point on the land surface. The left title says what is drawn, the right title
    the time, the way the line runs and the vertical exaggeration. The legend sits in
    the axes. A model base left under the window is given in a note.
    """
    table = data.table
    values = table["value"].to_numpy(dtype=float)
    colored = bool(np.isfinite(values).any())
    shown, norm = values, variables.color_norm(data.scale, data.log, values, data.limits)
    cmap = colormap(data.ramp or theme.ramps["sequential"])
    if data.scale == "categorical":
        shown, cmap, norm = variables.class_scale(values, data.classes, theme)
    elif data.scale != variables.scale(data.variable):
        cmap = colormap(theme.ramps[data.scale])
    cmap = cmap.with_extremes(bad=theme.roles["no_data"])
    x0, x1 = table["start"].to_numpy(), table["end"].to_numpy()
    bottom, top = table["bottom"].to_numpy(), table["top"].to_numpy()
    corners = [(x0, bottom), (x1, bottom), (x1, top), (x0, top)]
    cells = PolyCollection(
        np.stack([np.stack(corner, axis=-1) for corner in corners], axis=1),
        array=np.ma.masked_invalid(shown), cmap=cmap, norm=norm,
        edgecolors="none", linewidths=0.0, antialiased=False,
    )  # fmt: skip
    cells.set_rasterized(True)
    if colored:
        ax.add_collection(cells)
    smooth = not colored
    n_layers = int(table["layer"].max())
    first, last = table[table["layer"] == 0], table[table["layer"] == n_layers]
    (x, land), (_, base) = _profile(first, "top", smooth), _profile(last, "bottom", smooth)
    water = None
    if data.line is not None:
        water = _profile(data.line, "value", smooth)[1]
    if data.water and not colored:
        wet = np.fmin(np.where(np.isnan(water), base, water), land)
        for low, high, role in ((base, wet, "saturated"), (wet, land, "unsaturated")):
            ax.fill_between(
                x, low, high, color=theme.roles[role], linewidth=0.0, zorder=1,
                label=f"{role.capitalize()} zone",
            )  # fmt: skip
    for k in range(1, n_layers + 1):
        inner = table[table["layer"] == k]
        ax.plot(
            *_profile(inner, "top", smooth), color=theme.roles["layer_interface"],
            linewidth=theme.line_width, linestyle="--",
            label="Layer interface" if k == 1 else None, zorder=3,
        )  # fmt: skip
    ax.plot(
        x, base, label="Model base", zorder=4,
        color=theme.roles["layer_interface"], linewidth=theme.line_width * 1.4,
    )  # fmt: skip
    ax.plot(x, land, label="Land surface", zorder=4, **static.line_style(theme, "ground"))
    if data.line is not None and (data.water or colored):
        ax.plot(
            x, water, label=data.line_label, zorder=5,
            **{**static.line_style(theme, "water_table"), "linewidth": theme.data_line_width * 1.3},
        )  # fmt: skip
    seeps = np.array([(start + end) / 2 for name, start, end in data.marks if name == "seepage"])
    if seeps.size:
        ground = first["top"].to_numpy()[np.searchsorted(first["start"].to_numpy(), seeps) - 1]
        ax.scatter(
            seeps, ground, s=14, color=theme.roles["seepage"], edgecolors=theme.ink,
            linewidths=theme.line_width, zorder=6, label="Seepage",
        )  # fmt: skip
    shown_marks = set()
    for name, start, end in data.marks:
        if name == "seepage":
            continue
        text = None if name in shown_marks else name.capitalize()
        shown_marks.add(name)
        if end - start > 0:
            ax.axvspan(start, end, color=theme.roles["bounds"], alpha=0.2, label=text, zorder=2)
        else:
            ax.axvline(
                start, color=theme.roles["bounds"], linewidth=theme.data_line_width * 1.5,
                linestyle=":", label=text, zorder=6,
            )  # fmt: skip
    start, low, end, high = _window(data, land, water if data.water and not colored else None, base)
    ax.set_xlim(start, end)
    ax.set_ylim(low, high)
    ax.set_xlabel("Distance along the section (m)")
    ax.set_ylabel("Elevation (m)")
    static.style_axes(ax, theme)
    if colored:
        static.colorbar(ax.figure, cells, ax, theme, label="")
    if low > float(np.nanmax(base)):
        static.note(
            ax, f"Model base at {np.nanmin(base):.0f} to {np.nanmax(base):.0f} m, under the frame",
            theme, loc="lower right",
        )  # fmt: skip
    box = ax.get_position()
    size = ax.figure.get_size_inches()
    drawn_width = box.width * size[0] / max(end - start, 1e-9)
    drawn_height = box.height * size[1] / max(high - low, 1e-9)
    # The layout still moves after this, so the ratio is only given to two digits.
    ratio = float(f"{drawn_height / drawn_width:.2g}")
    when = ", ".join(filter(None, [data.period, data.caption, f"vertical exaggeration x{ratio:g}"]))
    static.titles(ax, theme, data.label if colored else data.line_label, when)
    static.legend(ax, theme, inside="best")
