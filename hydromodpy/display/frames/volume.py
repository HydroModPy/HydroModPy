"""Volume frame: the block of the model in 3D, coloured by one variable at one instant.

With an integer ``layer`` the block is that layer, between its own top and bottom interfaces,
coloured by its values. Otherwise it is the whole column, from the top of the first layer to the base
of the last, coloured by the variable reduced over the layers as a map reduces it. A cell
without a value is left out, and the walls go on the rim of the cells that remain. The frame
draws with the interactive engine only, since a still image of a block needs a point of view.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from hydromodpy.display import interactive
from hydromodpy.display.frames import map as map_frame
from hydromodpy.display.request import PanelRequest, is_column
from hydromodpy.display.subject import FigureNotApplicable, refuse_fields
from hydromodpy.display.theme import Theme
from hydromodpy.results.run.view import Run

FIELDS = ("variable", "time", "layer")
VOLUME_COLUMNS = ("cell", "x", "y", "top", "bottom", "value")
SLOPE = 0.25
"""The block is drawn about this fraction as high as it is wide, by stretching the vertical."""


@dataclass(frozen=True, slots=True)
class VolumeData:
    """What a block draws.

    ``table`` has the columns of ``VOLUME_COLUMNS``, one row per cell in mesh order: the
    face index, the centre in m, the top and the bottom of the block in m, and the value in
    the display unit. ``vertices`` is ``(n, 3)`` in m and ``triangles`` ``(t, 3)`` vertex
    numbers. Triangles of the top come first, one fan per cell with a finite value, then
    the walls. ``cells`` gives the cell of each triangle, -1 for a wall, and ``values`` its
    value, NaN for a wall. ``map`` is the map data of the same variable, which holds the
    label, the scale and the classes.
    """

    table: pd.DataFrame
    vertices: np.ndarray
    triangles: np.ndarray
    cells: np.ndarray
    values: np.ndarray
    map: map_frame.MapData


def _walls(faces: np.ndarray, vertices: np.ndarray, top: np.ndarray, base: np.ndarray, start: int):
    """Return the vertices and triangles of the walls on the edges that one given cell alone holds."""
    ring = np.where(faces >= 0, faces, faces[:, :1])
    after = np.roll(ring, -1, axis=1)
    sides = np.sort(np.stack([ring, after], -1), -1).reshape(-1, 2)
    _, inverse, count = np.unique(sides, axis=0, return_inverse=True, return_counts=True)
    rim = (count[inverse.ravel()] == 1).reshape(ring.shape) & (ring != after)
    cell, edge = np.nonzero(rim)
    p, q = vertices[ring[cell, edge], :2], vertices[after[cell, edge], :2]
    n = len(cell)
    xy = np.concatenate([p, q, q, p])
    z = np.concatenate([top[cell], top[cell], base[cell], base[cell]])
    walls = np.column_stack([xy, z])
    r = np.arange(n) + start
    first = np.concatenate([r, r])
    second = np.concatenate([r + n, r + 2 * n])
    third = np.concatenate([r + 2 * n, r + 3 * n])
    return walls, np.column_stack([first, second, third])


def data(subject: Run, panel: PanelRequest) -> VolumeData:
    """Read one variable at one instant, through the map frame, and build the block around it.

    A layered variable takes the layer of the panel, else the rule of its quantity, as a map
    does. With an integer layer the top is its upper interface and the bottom its lower one, in
    ``read_mesh``. Otherwise the top is the first interface and the bottom the last.
    """
    refuse_fields("volume", panel, FIELDS)
    if is_column(panel.variable[0]):
        raise FigureNotApplicable("A column of a table has no block to draw.")
    found = map_frame.data(subject, panel)
    mesh = found.mesh
    if mesh.interfaces is None:
        raise FigureNotApplicable("The mesh holds no layer interfaces, so it has no block.")
    if not isinstance(panel.layer, int):
        top, base = mesh.interfaces[0], mesh.interfaces[-1]
    else:
        layer = range(len(mesh.interfaces) - 1)[panel.layer]
        top, base = mesh.interfaces[layer], mesh.interfaces[layer + 1]
    values = found.table["value"].to_numpy(dtype=float)
    cells = np.flatnonzero(np.isfinite(values))
    x, y, triangles, k = interactive.fan(mesh, cells)
    owner = cells[np.arange(len(triangles)) // (k - 2)]
    surface = np.column_stack([x, y, np.repeat(top[cells], k)])
    walls, side = _walls(mesh.faces[cells], mesh.vertices, top[cells], base[cells], len(surface))
    table = found.table.assign(top=top, bottom=base)
    return VolumeData(
        table=table[list(VOLUME_COLUMNS)],
        vertices=np.vstack([surface, walls]),
        triangles=np.vstack([triangles, side]),
        cells=np.concatenate([owner, np.full(len(side), -1)]),
        values=np.concatenate([values[owner], np.full(len(side), np.nan)]),
        map=found,
    )


def _mesh(
    go: Any,
    vertices: np.ndarray,
    triangles: np.ndarray,
    labels: np.ndarray | None = None,
    **style: Any,
) -> Any:
    """Return a ``Mesh3d`` of some triangles with only the vertices they use.

    ``labels`` gives one hover text per triangle, which each of its vertices carries.
    """
    used, flat = np.unique(triangles, return_inverse=True)
    x, y, z = vertices[used].astype("float32").T
    i, j, k = flat.reshape(-1, 3).astype("int32").T
    if labels is not None:
        text = np.full(len(used), "", dtype=object)
        for corner in (i, j, k):
            text[corner] = labels
        style |= {"text": text, "hoverinfo": "text"}
    else:
        style |= {"hoverinfo": "skip", "showscale": False}
    return go.Mesh3d(x=x, y=y, z=z, i=i, j=j, k=k, flatshading=True, **style)


def draw_interactive(data: VolumeData, theme: Theme) -> tuple[list, dict]:
    """Return the top and the walls as plotly ``Mesh3d`` traces, and the scene settings.

    The vertical is stretched so the block is about ``SLOPE`` as high as it is wide, by a
    round factor that the panel title states. A block of more cells than
    ``interactive.MAX_CELLS`` is refused.
    """
    import plotly.graph_objects as go

    interactive.refuse_large(len(data.table))
    shown, colors = map_frame.interactive_color(data.map, theme)
    top = data.cells >= 0
    rows = np.where(top, data.cells, 0)
    drawn = top & np.isfinite(shown[rows])
    labels = map_frame.hover_text(data.map)[rows[drawn]]
    traces = [
        _mesh(
            go,
            data.vertices,
            data.triangles[drawn],
            labels,
            intensity=shown[rows[drawn]].astype("float32"),
            intensitymode="cell",
            **colors,
        ),  # fmt: skip
        _mesh(go, data.vertices, data.triangles[~top], color=theme.roles["layer_interface"]),
    ]
    span = np.ptp(data.vertices, axis=0)
    stretch = SLOPE * max(span[:2]) / span[2] if span[2] > 0 else 1.0
    stretch = max(1.0, float(f"{stretch:.1g}"))
    size = max(span[0], span[1], span[2] * stretch)
    crs = map_frame.crs_name(data.map.mesh.crs)
    scene = {
        "aspectmode": "manual",
        "aspectratio": {"x": span[0] / size, "y": span[1] / size, "z": span[2] * stretch / size},
        "camera": {"eye": {"x": 1.2, "y": -1.6, "z": 0.9}},
        "xaxis": {"title": f"x ({crs}, m)"},
        "yaxis": {"title": f"y ({crs}, m)"},
        "zaxis": {"title": "Elevation (m)"},
    }
    return traces, {"scene": scene, "title": f"vertical exaggeration x{stretch:g}"}
