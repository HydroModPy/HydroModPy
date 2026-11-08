"""The generated river network A: its rasters, read around a mesh and projected onto the cells.

A was traced by the river network step on the D8 pointer of the routing DEM. A
run keeps three full-extent rasters of it, the links, the pointer and the
accumulation, in one folder. ``channel_raster_paths`` names them and
``read_channel_tree`` reads a window of them around a mesh.

The projection of A onto the mesh cells has two stages. ``channel_exits`` reads
the cell of every pixel and nothing else, so it is a fact of the mesh. For each
cell that holds a pixel of A, it keeps the first other cell the pointer reaches
from the exit pixel of the cell, and whether that pixel is on A. ``pin_channel``
then reads what a backend knows at its build, the active columns and the lake
cells. A channel cell drains to the next channel cell along A, and the pins must
not close a loop.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import numpy as np

# File names written by catchment.algorithms.river_network.
_LINK_NAME = "dem_stream_link_id_full.tif"

_STREAMS_NAME = "dem_streams_full.tif"

_STREAMS_PRUNED_NAME = "dem_streams_pruned_full.tif"

_ACCUMULATION_NAME = "dem_acc_cells.tif"


@dataclass(frozen=True, slots=True)
class ChannelTree:
    """The generated network A on a window of its raster grid.

    ``link`` is true on the pixels of A. ``pointer`` is the WhiteboxTools D8
    code of the routing DEM A was traced on, and ``accumulation`` its flow
    accumulation. ``transform`` is the affine of the window.
    """

    link: np.ndarray
    pointer: np.ndarray
    accumulation: np.ndarray
    transform: Any


@dataclass(frozen=True, slots=True, eq=False)
class ChannelExits:
    """What a mesh says about A, one entry per cell, before any backend decision.

    ``holds_a`` is true for a cell that holds at least one pixel of A.
    ``next_cell`` is the first other cell that the D8 pointer reaches from the
    exit pixel of the cell, the pixel of A with the largest accumulation, and
    ``-1`` when the pointer ends before it reaches one or the pixel is off the
    mesh. ``next_on_a`` says whether the pixel where it enters ``next_cell`` is
    on A. The three arrays are read-only.
    """

    holds_a: np.ndarray
    next_cell: np.ndarray
    next_on_a: np.ndarray

    def __post_init__(self) -> None:
        holds_a = np.asarray(self.holds_a, dtype=bool).reshape(-1)
        next_cell = np.asarray(self.next_cell, dtype=int).reshape(-1)
        next_on_a = np.asarray(self.next_on_a, dtype=bool).reshape(-1)
        if not holds_a.size == next_cell.size == next_on_a.size:
            raise ValueError(
                "the channel exits hold one entry per cell: got "
                f"{holds_a.size}, {next_cell.size} and {next_on_a.size}."
            )
        for name, values in (
            ("holds_a", holds_a),
            ("next_cell", next_cell),
            ("next_on_a", next_on_a),
        ):
            values.setflags(write=False)
            object.__setattr__(self, name, values)

    @property
    def n_cells(self) -> int:
        """The number of cells of the mesh the exits were read on."""
        return int(self.holds_a.size)


def channel_raster_paths(folder: str | os.PathLike[str]) -> tuple[str, str, str]:
    """Return the ``(link, pointer, accumulation)`` rasters of A in ``folder``.

    The link raster is the one :func:`active_channel_raster` picks. The paths
    are returned whether or not the files exist, and the reader checks.
    """
    from hydromodpy.catchment.algorithms.flow_products import DIRECTION_NAME

    return (
        active_channel_raster(folder),
        os.path.join(str(folder), DIRECTION_NAME),
        os.path.join(str(folder), _ACCUMULATION_NAME),
    )


def active_channel_raster(folder: str | os.PathLike[str]) -> str:
    """The full-extent raster that holds A in ``folder``, the one rule of every reader.

    The link raster when it is not older than ``dem_streams_full.tif`` (the step
    writes it from the active streams, so an older one was left by an earlier
    configuration). Else the pruned stream raster when it exists and is not older
    than ``dem_streams_full.tif``: with ``prune_short_streams`` A is the pruned
    network, never the raw one. Else ``dem_streams_full.tif``. The returned path
    may not exist; the caller checks.
    """
    streams = os.path.join(str(folder), _STREAMS_NAME)
    streams_time = os.path.getmtime(streams) if os.path.exists(streams) else None
    candidates = (
        os.path.join(str(folder), _LINK_NAME),
        os.path.join(str(folder), _STREAMS_PRUNED_NAME),
    )
    for candidate in candidates:
        if not os.path.exists(candidate):
            continue
        if streams_time is None or os.path.getmtime(candidate) >= streams_time:
            return candidate
    return streams


def read_channel_tree(
    *,
    link_tif: str,
    pointer_tif: str,
    accumulation_tif: str,
    bounds: tuple[float, float, float, float],
) -> ChannelTree:
    """Read A, its pointer and its accumulation over ``bounds`` plus one pixel.

    The rasters cover the regional DEM. Only the window around the mesh is
    read; a pointer that leaves it leaves the mesh too. The three rasters must
    share one grid, as the SFR delineation requires.
    """
    import rasterio
    from rasterio.windows import Window
    from rasterio.windows import transform as window_transform

    sources = {"link": link_tif, "pointer": pointer_tif, "accumulation": accumulation_tif}
    arrays: dict[str, np.ndarray] = {}
    reference: tuple[str, Any, tuple[int, int]] | None = None
    window: Window | None = None
    for name, path in sources.items():
        with rasterio.open(path) as dataset:
            shape = (int(dataset.height), int(dataset.width))
            if reference is None:
                reference = (name, dataset.transform, shape)
                window = _window_around(dataset.transform, shape, bounds)
            elif dataset.transform != reference[1] or shape != reference[2]:
                raise ValueError(
                    f"The channel tree rasters are misaligned: '{name}' ({path}) does not "
                    f"share the grid of '{reference[0]}'."
                )
            data = dataset.read(1, window=window)
            nodata = dataset.nodata
        if name == "link":
            valid = np.isfinite(data) & (data > 0)
            if nodata is not None and float(nodata) > 0:
                valid &= data != nodata
            arrays[name] = valid
        elif name == "pointer":
            arrays[name] = np.nan_to_num(data, nan=0.0).astype(np.int64)
        else:
            arrays[name] = np.nan_to_num(np.asarray(data, dtype=float), nan=0.0)
    assert reference is not None and window is not None
    return ChannelTree(
        link=arrays["link"],
        pointer=arrays["pointer"],
        accumulation=arrays["accumulation"],
        transform=window_transform(window, reference[1]),
    )


def _window_around(
    transform: Any, shape: tuple[int, int], bounds: tuple[float, float, float, float]
) -> Any:
    """Pixel window covering ``bounds`` with one pixel of margin, clipped to the raster."""
    from rasterio.windows import Window

    xmin, ymin, xmax, ymax = bounds
    inverse = ~transform
    cols, rows = zip(*(inverse @ (x, y) for x in (xmin, xmax) for y in (ymin, ymax)), strict=True)
    row0 = max(int(np.floor(min(rows))) - 1, 0)
    col0 = max(int(np.floor(min(cols))) - 1, 0)
    row1 = min(int(np.ceil(max(rows))) + 1, shape[0])
    col1 = min(int(np.ceil(max(cols))) + 1, shape[1])
    return Window(col0, row0, max(col1 - col0, 0), max(row1 - row0, 0))


def channel_exits(tree: ChannelTree, cell_labels: np.ndarray, *, n_cells: int) -> ChannelExits:
    """Project A onto the cells of a mesh, up to the choices a backend makes.

    ``cell_labels`` is the raster of the cell number of every pixel of the
    window of ``tree`` (``-1`` where no cell lies, and a number of ``n_cells``
    or more is read as no cell). It is only read when A has a pixel, so a tree
    with none may come with an empty array.

    The exit pixel of a cell is its pixel of A with the largest accumulation.
    The pointer is followed from it to the first pixel in another cell, which
    gives ``next_cell`` and ``next_on_a``. Neither reads the active columns or
    the lakes, which :func:`pin_channel` reads.
    """
    from hydromodpy.catchment.terrain.d8 import d8_receivers

    holds_a = np.zeros(n_cells, dtype=bool)
    next_cell = np.full(n_cells, -1, dtype=int)
    next_on_a = np.zeros(n_cells, dtype=bool)
    if not np.any(tree.link):
        return ChannelExits(holds_a, next_cell, next_on_a)
    labels = np.asarray(cell_labels)
    if labels.shape != tree.link.shape:
        raise ValueError(
            f"the cell numbers have shape {labels.shape} and the window of A {tree.link.shape}."
        )
    nrows, ncols = tree.link.shape
    labels = np.where(labels < n_cells, labels, -1)
    a_pixels = np.flatnonzero(tree.link.reshape(-1))
    a_labels = labels.reshape(-1)[a_pixels]
    keep = a_labels >= 0
    a_pixels, a_labels = a_pixels[keep], a_labels[keep]
    if a_pixels.size == 0:
        return ChannelExits(holds_a, next_cell, next_on_a)
    holds_a[a_labels] = True

    # Exit pixel of each cell: the last of its A pixels sorted by accumulation.
    accumulation = tree.accumulation.reshape(-1)
    order = np.lexsort((accumulation[a_pixels], a_labels))
    sorted_labels = a_labels[order]
    last = np.r_[sorted_labels[1:] != sorted_labels[:-1], True]
    exit_pixel = dict(
        zip(sorted_labels[last].tolist(), a_pixels[order][last].tolist(), strict=True)
    )

    receivers = d8_receivers(tree.pointer, pit="none")
    flat_labels = labels.reshape(-1)
    flat_link = tree.link.reshape(-1)
    max_steps = nrows * ncols
    for cell, pixel in exit_pixel.items():
        current = int(pixel)
        for _ in range(max_steps):
            current = int(receivers[current])
            if current < 0:
                break
            other = int(flat_labels[current])
            if other == cell:
                continue
            next_cell[cell] = other
            next_on_a[cell] = bool(flat_link[current])
            break
    return ChannelExits(holds_a, next_cell, next_on_a)


def pin_channel(
    exits: ChannelExits, *, routable: np.ndarray, lake_of: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(pinned_receiver, channel)``: A projected onto the cells of a backend.

    A channel cell is a routable, non-lake cell that holds a pixel of A. It is
    pinned to ``next_cell`` when the pointer enters that cell on a pixel of A
    and that cell is a channel cell too. Otherwise A leaves through a lake, off
    the graph or off the raster, the cell is an outlet of A and keeps the
    steepest descent (pin ``-1``).

    Pins are acyclic: the accumulation grows strictly along the pointer, so the
    largest accumulation of a cell grows strictly along its pins. A cycle means
    the pointer and the accumulation disagree, and it is refused.
    """
    on_graph = np.asarray(routable, dtype=bool).reshape(-1)
    lakes = np.asarray(lake_of, dtype=int).reshape(-1)
    if not on_graph.size == lakes.size == exits.n_cells:
        raise ValueError(
            f"the exits of A hold {exits.n_cells} cells, the routable mask {on_graph.size} "
            f"and the lake numbers {lakes.size}."
        )
    channel = exits.holds_a & on_graph & (lakes < 0)
    pinned = np.full(exits.n_cells, -1, dtype=int)
    follows = channel & exits.next_on_a & (exits.next_cell >= 0)
    follows[follows] = channel[exits.next_cell[follows]]
    pinned[follows] = exits.next_cell[follows]
    _refuse_pin_cycles(pinned)
    return pinned, channel


def _refuse_pin_cycles(pinned: np.ndarray) -> None:
    """Raise ``ValueError`` naming a cell when the pins close a loop."""
    state = np.zeros(pinned.size, dtype=np.int8)  # 0 new, 1 on the current walk, 2 settled
    for start in np.flatnonzero(pinned >= 0).tolist():
        walk: list[int] = []
        cell = start
        while cell >= 0 and state[cell] == 0:
            state[cell] = 1
            walk.append(cell)
            cell = int(pinned[cell])
        if cell >= 0 and state[cell] == 1:
            raise ValueError(
                f"The channel tree A closes a loop through cell {cell} on the mesh: its D8 "
                "pointer and its accumulation disagree."
            )
        state[walk] = 2
