"""Named context layers drawn over a map or a section.

The names and the fields each layer reads are ``request.OVERLAY_FIELDS``. This
module holds one function per name, called like the name, and ``OVERLAYS`` finds
them by name. An overlay is a function ``overlay(ax, subject, theme)`` that draws on
axes already holding the frame, in the mesh CRS, and reads the subject through
``display.subject`` only. An overlay whose signature declares ``time`` receives the
instant of the panel. An overlay that finds nothing to draw logs one line and
returns: it never refuses a figure.
"""

from __future__ import annotations

import functools
import inspect
from collections import Counter
from collections.abc import Callable
from typing import Any

import numpy as np
import shapely
from matplotlib.collections import LineCollection, PolyCollection
from matplotlib.colors import LightSource, to_rgba
from matplotlib.tri import CubicTriInterpolator, Triangulation
from scipy import ndimage

from hydromodpy.core.logging import get_logger
from hydromodpy.display import subject as reads
from hydromodpy.display.request import OVERLAY_FIELDS, Instant
from hydromodpy.display.static import line_style
from hydromodpy.display.static import scale_bar as draw_scale_bar
from hydromodpy.display.subject import FigureNotApplicable
from hydromodpy.display.theme import Theme
from hydromodpy.results.run.view import Run

logger = get_logger(__name__)

Z_RELIEF, Z_FILL, Z_LINE, Z_MARK = 1, 3, 5, 8
SUN_AZIMUTH, SUN_ALTITUDE = 315.0, 40.0
"""Light direction of the hillshade, in degrees: from the north west, 40 degrees up."""
RELIEF_EXAGGERATION = 2.0
"""Vertical exaggeration of the hillshade."""
RELIEF_STRENGTH = 1.1
"""Opacity of the shade per unit of difference to flat ground, black on the dark side."""
RELIEF_MAX_ALPHA = 0.35
"""Largest opacity of the shade, so that the colour under it still reads."""
MAX_PATHLINES = 250
"""Pathlines the overlay draws at most, evenly through the release order."""
FILL_ALPHA = 0.5
"""Opacity of the face of filled cells, so that what lies under them still shows."""
CASING = 2.2
"""Width of the white line under a network line, as a multiple of the line."""
MIN_RELIEF_CELLS = 3
"""Fewest cells with a topography that make a hillshade."""
RELIEF_PIXELS = (96, 480)
"""Fewest and most pixels on a side of the shade, which is four per cell between the two."""


def quiet(draw: Callable[..., None]) -> Callable[..., None]:
    """Turn a missing read into one log line, so an overlay never refuses a figure.

    The instant of the panel reaches the overlays whose signature declares ``time``.
    """
    timed = "time" in inspect.signature(draw).parameters

    @functools.wraps(draw)
    def wrapped(ax: Any, subject: Run, theme: Theme, time: Instant = "last") -> None:
        try:
            draw(ax, subject, theme, **({"time": time} if timed else {}))
        except FigureNotApplicable as exc:
            logger.info("Overlay %s skipped: %s", draw.__name__, exc)

    return wrapped


def _polygons(mesh: reads.MeshView, mask: np.ndarray | None = None) -> list[np.ndarray]:
    faces = mesh.faces if mask is None else mesh.faces[mask]
    return [mesh.vertices[row[row >= 0]] for row in faces]


def _geometry_lines(geometry: Any) -> list[np.ndarray]:
    """Return the coordinates of every line or polygon ring of a shapely geometry."""
    if geometry is None or geometry.is_empty:
        return []
    if hasattr(geometry, "geoms"):
        return [line for part in geometry.geoms for line in _geometry_lines(part)]
    if hasattr(geometry, "exterior"):
        return [np.asarray(geometry.exterior.coords)[:, :2]]
    if geometry.geom_type in ("LineString", "LinearRing"):
        return [np.asarray(geometry.coords)[:, :2]]
    return []


def _add_lines(
    ax: Any, lines: list[np.ndarray], theme: Theme, role: str, *, width: float, **extra: Any
) -> None:
    if not lines:
        logger.info("Overlay %s has no line to draw.", role)
        return
    style = line_style(theme, role)
    ax.add_collection(
        LineCollection(
            lines, colors=style["color"], linewidths=width, zorder=Z_LINE,
            capstyle="round", joinstyle="round", **extra,
        )
    )  # fmt: skip


def cells(
    ax: Any, run: Run, theme: Theme, field: str, role: str, time: Instant, *, fill: bool = False
) -> None:
    """Outline the cells where ``field`` is finite and not zero at ``time``, or fill them.

    The collection carries the role as its label, for a figure that draws a legend.
    """
    mesh = reads.read_mesh(run)
    values = reads.read_field(run, field, time=time)
    mask = np.isfinite(values) & (values != 0)
    if not mask.any():
        logger.info("Overlay %s has no cell where %s is not zero.", role, field)
        return
    color = line_style(theme, role)["color"]
    ax.add_collection(
        PolyCollection(
            _polygons(mesh, mask),
            facecolors=to_rgba(color, FILL_ALPHA) if fill else "none",
            edgecolors=color,
            label=role.capitalize(),
            linewidths=theme.line_width,
            zorder=Z_FILL,
            rasterized=True,
        )
    )


@quiet
def relief(ax: Any, subject: Run, theme: Theme) -> None:
    """Shade the map by the relief of ``topography``, dark on the slopes away from the sun.

    The shade is black or white with an opacity that grows with the slope, so flat ground
    keeps the colour of the map.
    """
    mesh = reads.read_mesh(subject)
    top = reads.read_field(subject, "topography")
    keep = np.isfinite(top)
    if keep.sum() < MIN_RELIEF_CELLS:
        logger.info("Overlay relief has too few cells with a topography.")
        return
    x, y = mesh.centres[keep, 0], mesh.centres[keep, 1]
    side = int(np.clip(4 * np.sqrt(keep.sum()), *RELIEF_PIXELS))
    half = np.sqrt(mesh.areas[keep].mean()) / 2
    gx = np.linspace(x.min() - half, x.max() + half, side)
    gy = np.linspace(y.min() - half, y.max() + half, side)
    step = (gx[1] - gx[0], gy[1] - gy[0])
    # A smooth surface through the cell centres, so the shade has no facet.
    interp = CubicTriInterpolator(Triangulation(x, y), top[keep], kind="geom")
    grid = interp(*np.meshgrid(gx, gy))
    # The surface stops at the centres, so the nearest value covers the last half cell.
    far, nearest = ndimage.distance_transform_edt(grid.mask, return_indices=True)
    filled = grid.filled(np.nan)[tuple(nearest)]
    outside = far > half / min(step) + 1
    shade = LightSource(azdeg=SUN_AZIMUTH, altdeg=SUN_ALTITUDE).hillshade(
        filled, vert_exag=RELIEF_EXAGGERATION, dx=step[0], dy=step[1]
    )
    flat = np.sin(np.radians(SUN_ALTITUDE))
    tone = np.zeros((*shade.shape, 4))
    tone[..., :3] = (shade > flat)[..., None]
    tone[..., 3] = np.clip(np.abs(shade - flat) * RELIEF_STRENGTH, 0.0, RELIEF_MAX_ALPHA)
    tone[outside, 3] = 0.0
    limits = (ax.get_xlim(), ax.get_ylim()) if ax.has_data() else None
    ax.imshow(
        tone,
        extent=(
            gx[0] - step[0] / 2,
            gx[-1] + step[0] / 2,
            gy[0] - step[1] / 2,
            gy[-1] + step[1] / 2,
        ),
        origin="lower",
        interpolation="bilinear",
        aspect="equal",
        zorder=Z_RELIEF,
    )
    if limits:
        ax.set_xlim(limits[0])
        ax.set_ylim(limits[1])


@quiet
def outline(ax: Any, subject: Run, theme: Theme) -> None:
    """Draw the outline of the ``catchment`` zone of ``read_mesh``."""
    mesh = reads.read_mesh(subject)
    faces = mesh.faces[mesh.zones["catchment"]]
    edges: Counter = Counter()
    for row in faces:
        ring = row[row >= 0]
        for a, b in zip(ring, np.roll(ring, -1), strict=True):
            edges[(min(a, b), max(a, b))] += 1
    border = [mesh.vertices[list(edge)][:, :2] for edge, n in edges.items() if n == 1]
    # Merged into rings, the outline is one stroke with clean corners.
    rings = shapely.line_merge(shapely.MultiLineString(border)) if border else None
    _add_lines(ax, _geometry_lines(rings), theme, "outline", width=theme.line_width * 2.5)


@quiet
def network(ax: Any, subject: Run, theme: Theme) -> None:
    """Draw the reference network, intermittent reaches dashed when ``reference_permanent`` exists."""
    reference = reads.read_network(subject, "reference")
    solid, width = "reference_network", theme.line_width * 2
    # A white line under the network keeps it readable on any colour.
    ax.add_collection(
        LineCollection(
            _all_lines(reference), colors=theme.face, linewidths=width * CASING,
            zorder=Z_LINE, capstyle="round",
        )
    )  # fmt: skip
    try:
        permanent = {g.wkb for g in reads.read_network(subject, "reference_permanent").geometry}
    except FigureNotApplicable:
        permanent = None
    if permanent is None:
        _add_lines(ax, _all_lines(reference), theme, solid, width=theme.line_width * 2)
        return
    is_permanent = [g.wkb in permanent for g in reference.geometry]
    for flag, role, dashes in (
        (True, solid, "-"),
        (False, "intermittent_reach", "--"),
    ):
        part = reference.geometry[[p is flag for p in is_permanent]]
        _add_lines(
            ax,
            [line for g in part for line in _geometry_lines(g)],
            theme,
            role,
            width=theme.line_width * 2,
            linestyles=dashes,
        )


def _all_lines(frame: Any) -> list[np.ndarray]:
    return [line for g in frame.geometry for line in _geometry_lines(g)]


@quiet
def generated_network(ax: Any, subject: Run, theme: Theme) -> None:
    """Draw the network generated from the DEM."""
    frame = reads.read_network(subject, "generated")
    _add_lines(ax, _all_lines(frame), theme, "generated_network", width=theme.line_width * 2)


@quiet
def outlet(ax: Any, subject: Run, theme: Theme) -> None:
    """Mark the outlet of ``read_mesh``."""
    point = reads.read_mesh(subject).outlet
    if point is None:
        logger.info("Overlay outlet skipped: the run has no outlet.")
        return
    ax.scatter(
        [point[0]],
        [point[1]],
        marker="v",
        s=30,
        color=line_style(theme, "outlet")["color"],
        edgecolors=theme.ink,
        linewidths=theme.line_width,
        zorder=Z_MARK,
    )


@quiet
def stations(ax: Any, subject: Run, theme: Theme) -> None:
    """Mark the observation points the run declared, from its ``observation_points`` table."""
    frame = reads.read_table(subject, "observation_points")
    if frame.empty:
        logger.info("Overlay stations has no observation point to draw.")
        return
    ax.scatter(
        frame["x"],
        frame["y"],
        marker="^",
        s=18,
        color=line_style(theme, "piezometer")["color"],
        edgecolors=theme.ink,
        linewidths=theme.line_width,
        zorder=Z_MARK,
    )


@quiet
def lake(ax: Any, subject: Run, theme: Theme, time: Instant = "last") -> None:
    """Outline the cells that exchange with a lake at the instant of the panel."""
    cells(ax, subject, theme, "lake", "lake", time)


@quiet
def barrier(ax: Any, subject: Run, theme: Theme) -> None:
    """Draw the cut-off walls of the ``barrier`` layer."""
    frame = reads.read_network(subject, "barrier")
    _add_lines(ax, _all_lines(frame), theme, "barrier", width=theme.line_width * 3)


@quiet
def wells(ax: Any, subject: Run, theme: Theme, time: Instant = "last") -> None:
    """Mark the cells where the ``well`` term is not zero at the instant of the panel."""
    cells(ax, subject, theme, "well", "well", time)


@quiet
def seepage(ax: Any, subject: Run, theme: Theme, time: Instant = "last") -> None:
    """Fill the cells where the water table reaches the land surface at the instant."""
    cells(ax, subject, theme, "seepage_mask", "seepage", time, fill=True)


@quiet
def pathlines(ax: Any, subject: Run, theme: Theme) -> None:
    """Draw the paths of the tracked particles as thin lines, one in n beyond ``MAX_PATHLINES``."""
    paths, _ = reads.read_pathlines(subject)
    shown = paths[:: -(-len(paths) // MAX_PATHLINES)]
    _add_lines(ax, shown, theme, "pathline", width=theme.line_width / 2, alpha=0.7)


@quiet
def scale_bar(ax: Any, subject: Run, theme: Theme) -> None:
    """Draw the scale bar of ``static.scale_bar``."""
    draw_scale_bar(ax, theme)


@quiet
def mesh(ax: Any, subject: Run, theme: Theme) -> None:
    """Draw the cell edges in thin grey."""
    view = reads.read_mesh(subject)
    ax.add_collection(
        PolyCollection(
            _polygons(view),
            facecolors="none",
            edgecolors=line_style(theme, "trial")["color"],
            linewidths=theme.line_width / 3,
            zorder=Z_FILL,
            rasterized=True,
        )
    )


def _overlay(name: str) -> Callable[[Any, Run, Theme], None]:
    try:
        return globals()[name]
    except KeyError:
        raise KeyError(
            f"Overlay {name!r} has no function in hydromodpy/display/overlays.py. Add one."
        ) from None


OVERLAYS: dict[str, Callable[[Any, Run, Theme], None]] = {
    name: _overlay(name) for name in OVERLAY_FIELDS
}
