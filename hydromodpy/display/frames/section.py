"""Section frame: a vertical cut through the model along a line, distance against elevation.

It draws the cells crossed by the line as one rectangle per cell and per layer,
coloured by a layered variable, with the land surface, the model base and the
layer interfaces. A variable without a layer axis whose values are elevations
(``watertable_elevation``, ``topography``) is drawn as a stepped line over the empty
cells. It draws one instant and never a map overlay: the only context it knows is
the lake and barrier marks it reads itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import matplotlib
import numpy as np
import pandas as pd
import shapely
from matplotlib.collections import PolyCollection

from hydromodpy.display import static, variables
from hydromodpy.display.frames.map import stored_field
from hydromodpy.display.request import PanelRequest, descriptor
from hydromodpy.display.subject import (
    FigureNotApplicable,
    read_field,
    read_mesh,
    read_network,
    refuse_fields,
)
from hydromodpy.display.theme import Theme
from hydromodpy.results.run.view import Run

FIELDS = ("variable", "time", "overlays", "line", "scale", "share", "reduce", "change")
SECTION_COLUMNS = ("cell", "layer", "start", "end", "top", "bottom", "value")
LINE_COLUMNS = ("cell", "start", "end", "value")
SECTION_MARKS = ("lake", "barrier")
"""Overlay names a section draws itself, as spans along the line."""


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
    legend text. ``marks`` holds ``(overlay name, start, end)`` spans in m for the
    names of ``SECTION_MARKS`` the panel asked. ``trace`` is the line used, points
    ``(x, y)`` in m in the mesh CRS. ``label``, ``scale``, ``ramp``, ``log``,
    ``classes`` and ``limits`` mean what they mean on ``MapData``, so a shared norm
    reaches a section as it reaches a map.
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
    ``against``, ``cumulative``, ``observed``, ``scores``, ``stack``, ``by`` and
    ``bbox`` are refused. An overlay outside ``SECTION_MARKS`` is refused. ``lake``
    marks the cells whose ``lake`` term is not zero at the instant, ``barrier`` the
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
        line, line_label = (
            pieces.assign(value=_read(subject, panel, mesh, name)[cells]),
            variables.label(name),
        )
    elif found.quantity == "head":
        try:
            water = _read(subject, panel, mesh, "watertable_elevation")[cells]
            line, line_label = pieces.assign(value=water), "Water table"
        except FigureNotApplicable:
            pass  # A run without a water table draws the cells alone.
    if line is not None:
        line = line[list(LINE_COLUMNS)].sort_values("start", ignore_index=True)
    scale, label, log = _scale(panel, name, layered, table["value"].dropna().to_numpy())
    classes = tuple(found.classes) if scale == "categorical" else ()
    return SectionData(
        table, name, label, scale, variables.ramp(name, Theme()) if layered else "", log,
        trace, line, line_label, _marks(subject, panel, pieces, trace), classes,
    )  # fmt: skip


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


def _marks(subject, panel, pieces, trace) -> tuple[tuple[str, float, float], ...]:
    marks = []
    if "lake" in (panel.overlays or ()):
        time = "last" if panel.time is None else panel.time
        flow = read_field(subject, "lake", time=time)[pieces["cell"].to_numpy()]
        hit = pieces[np.isfinite(flow) & (flow != 0)].sort_values("start")
        span = None
        for start, end in zip(hit["start"], hit["end"], strict=True):
            if span is not None and start <= span[2] + 1e-6:
                span = ("lake", span[1], max(span[2], end))
            else:
                marks += [span] if span else []
                span = ("lake", start, end)
        marks += [span] if span else []
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
    return x, np.repeat(table[column].to_numpy(), 2)


def draw(ax: Any, data: SectionData, theme: Theme) -> None:
    """Draw the cells as one PolyCollection of rectangles, the colorbar on the right.

    Rectangles are ``(start, bottom)`` to ``(end, top)``, rasterised, with the
    norm rules of the map frame (``LogNorm``, ``TwoSlopeNorm`` centred on zero,
    categorical classes in a legend). Over them: the layer interfaces as thin
    dashed lines, the land surface and the model base as outline lines, then
    ``line`` as a stepped line of the ``simulated`` role. Each mark is a span of
    the ``bounds`` role with its name in the legend. The x axis reads ``Distance
    along the section (m)``, the y axis ``Elevation (m)``, and a small note writes
    the vertical exaggeration as the atlas does. Legend above the axes.
    """
    table = data.table
    values = table["value"].to_numpy(dtype=float)
    colored = bool(np.isfinite(values).any())
    shown, norm = values, variables.color_norm(data.scale, data.log, values, data.limits)
    cmap = matplotlib.colormaps[data.ramp or "viridis"]
    if data.scale == "categorical":
        shown, cmap, norm = variables.class_scale(values, data.classes, theme)
    elif data.scale != variables.scale(data.variable):
        cmap = matplotlib.colormaps[theme.ramps[data.scale]]
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
    ax.add_collection(cells)
    n_layers = int(table["layer"].max())
    first, last = table[table["layer"] == 0], table[table["layer"] == n_layers]
    outline = {**static.line_style(theme, "outline"), "linewidth": theme.line_width * 1.4}
    ax.plot(*_stepped(first, "top"), label="Land surface", **{**outline, "zorder": 4})
    ax.plot(*_stepped(last, "bottom"), label="Model base", **{**outline, "zorder": 4})
    for k in range(1, n_layers + 1):
        inner = table[table["layer"] == k]
        ax.plot(
            *_stepped(inner, "top"), color=theme.roles["bounds"], linewidth=theme.line_width,
            linestyle="--", label="Layer interface" if k == 1 else None, zorder=3,
        )  # fmt: skip
    if data.line is not None:
        ax.plot(
            *_stepped(data.line, "value"), label=data.line_label, zorder=5,
            **static.line_style(theme, "simulated"),
        )  # fmt: skip
    shown_marks = set()
    for name, start, end in data.marks:
        text = None if name in shown_marks else name.capitalize()
        shown_marks.add(name)
        if end - start > 0:
            ax.axvspan(start, end, color=theme.roles["bounds"], alpha=0.2, label=text, zorder=2)
        else:
            ax.axvline(
                start, color=theme.roles["bounds"], linewidth=theme.data_line_width * 1.5,
                linestyle=":", label=text, zorder=6,
            )  # fmt: skip
    low, high = float(bottom.min()), float(top.max())
    pad = 0.04 * (high - low or 1.0)
    ax.set_xlim(float(x0.min()), float(x1.max()))
    ax.set_ylim(low - pad, high + pad)
    ax.set_xlabel("Distance along the section (m)")
    ax.set_ylabel("Elevation (m)")
    static.style_axes(ax, theme)
    if colored:
        static.colorbar(ax.figure, cells, ax, theme, label=data.label)
    box = ax.get_position()
    size = ax.figure.get_size_inches()
    drawn_width = box.width * size[0] / max(float(x1.max() - x0.min()), 1e-9)
    drawn_height = box.height * size[1] / (high - low + 2 * pad)
    # The layout still moves after this, so the ratio is only given to two digits.
    ratio = float(f"{drawn_height / drawn_width:.2g}")
    static.note(ax, f"Vertical exaggeration about x{ratio:g}", theme, loc="lower right")
    if ax.get_legend_handles_labels()[0]:
        static.legend(ax, theme)
