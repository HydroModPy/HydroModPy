"""The generated river network A: which rasters a run reads, read and projected onto the mesh cells.

A was traced by the river network step on the D8 pointer of the routing DEM.
``channel_rasters_for_run`` chooses its rasters once, before the solve, and the
choice sits in ``Model.geometry.raster.channel``. ``channel_tree_for_run`` reads
them around the mesh. The projection gives the pinned receivers of D: each cell
A crosses drains to the next cell along A, and the pins must not close a loop.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.model.domain.geometry import ChannelRasters

__all__ = [
    "ChannelTree",
    "active_channel_raster",
    "channel_rasters_for_run",
    "channel_tree_for_run",
    "project_channel_tree",
    "read_channel_tree",
]

logger = get_logger(__name__)

# File names written by catchment.algorithms.river_network.
_LINK_NAME = "dem_stream_link_id_full.tif"

_STREAMS_NAME = "dem_streams_full.tif"

_STREAMS_PRUNED_NAME = "dem_streams_pruned_full.tif"

_ACCUMULATION_NAME = "dem_acc_cells.tif"


@dataclass(frozen=True, slots=True)
class ChannelTree:
    """The generated network A on a window of its raster grid.

    ``link`` is positive on the pixels of A. ``pointer`` is the WhiteboxTools D8
    code of the routing DEM A was traced on, and ``accumulation`` its flow
    accumulation. ``transform`` is the affine of the window.
    """

    link: np.ndarray
    pointer: np.ndarray
    accumulation: np.ndarray
    transform: Any


def channel_rasters_for_run(geographic: object | None) -> ChannelRasters | None:
    """The rasters of the generated network A that this run reads, chosen once.

    A is the full-extent stream-link raster of the river-network step (the
    stream raster when links were not computed, see :func:`active_channel_raster`),
    with the D8 pointer it was traced on and its accumulation, all in
    ``geographic.correcflow_path``. Their paths are returned whether or not the
    files exist, and the reader checks. The rasters cut to the watershed
    (``river_stream_link_id_tif`` then ``river_streams_tif``) that exist are
    kept in ``clipped``: they miss the buffer, so the zonal top sampling reads
    them only when the full-extent raster is missing.

    ``enabled`` is ``geographic.river_network_enabled``. Nothing is returned for a
    run that has no corrected-flow folder, no clipped raster and no river
    network step, which is the run without A.
    """
    from hydromodpy.catchment.algorithms.flow_products import DIRECTION_NAME

    enabled = bool(getattr(geographic, "river_network_enabled", False))
    folder = getattr(geographic, "correcflow_path", None)
    clipped = tuple(
        str(candidate)
        for name in ("river_stream_link_id_tif", "river_streams_tif")
        if (candidate := getattr(geographic, name, None)) and os.path.exists(str(candidate))
    )
    if folder is None and not clipped and not enabled:
        return None
    if folder is None:
        return ChannelRasters(
            enabled=enabled, link=None, pointer=None, accumulation=None, clipped=clipped
        )
    return ChannelRasters(
        enabled=enabled,
        link=active_channel_raster(folder),
        pointer=os.path.join(str(folder), DIRECTION_NAME),
        accumulation=os.path.join(str(folder), _ACCUMULATION_NAME),
        clipped=clipped,
    )


def channel_tree_for_run(
    rasters: ChannelRasters | None, solver_mesh: Any, *, required: bool = False
) -> ChannelTree | None:
    """The generated network A around the mesh, or None when the run has none.

    ``rasters`` is ``Model.geometry.raster.channel``, the choice of
    :func:`channel_rasters_for_run`. The clipped rasters are cut to the
    watershed and miss the buffer, so they are never read here.

    A belongs to the run only when ``rasters.enabled`` says the river-network
    step ran for it; rasters an earlier configuration left in the folder are
    never read. ``required`` is set when a network of the run was delineated
    from A, so missing rasters are an error.
    """
    if not required and not (rasters is not None and rasters.enabled):
        logger.info(
            "The river network is off for this run: the descent D has no pinned cell and "
            "follows the steepest descent everywhere."
        )
        return None
    if rasters is None or rasters.link is None:
        logger.info(
            "No corrected-flow folder for this run: the descent D has no pinned cell and "
            "follows the steepest descent everywhere."
        )
        return None
    link, pointer, accumulation = rasters.link, rasters.pointer, rasters.accumulation
    missing = [path for path in (link, pointer, accumulation) if not os.path.exists(path)]
    if missing and required:
        raise FileNotFoundError(
            "The SFR reaches lie on the generated river network A, but its rasters are "
            f"missing: {', '.join(missing)}. Rerun the geographic preprocessing."
        )
    if missing:
        logger.info(
            "No generated river network A in %s: the descent D has no pinned cell and "
            "follows the steepest descent everywhere.",
            os.path.dirname(link),
        )
        return None
    vertices = np.asarray(solver_mesh.planar_mesh.vertices, dtype=float)[:, :2]
    return read_channel_tree(
        link_tif=link,
        pointer_tif=pointer,
        accumulation_tif=accumulation,
        bounds=(
            float(vertices[:, 0].min()),
            float(vertices[:, 1].min()),
            float(vertices[:, 0].max()),
            float(vertices[:, 1].max()),
        ),
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


def project_channel_tree(
    tree: ChannelTree,
    planar_mesh: Any,
    *,
    routable: np.ndarray,
    lake_of: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(pinned_receiver, channel)``: A projected onto the mesh cells.

    A channel cell is a routable, non-lake cell holding at least one pixel of A.
    Its pin is found from its exit pixel, the A pixel of largest accumulation:
    the pointer is followed to the first pixel in another cell. When that pixel
    is on A and its cell is a channel cell, that cell is the pin. Otherwise A
    leaves through a lake, off the graph or off the raster, the cell is an
    outlet of A and keeps the steepest descent (pin -1).

    Pins are acyclic: the accumulation grows strictly along the pointer, so the
    largest accumulation of a cell grows strictly along its pins. A cycle means
    the pointer and the accumulation disagree, and it is refused.
    """
    from hydromodpy.catchment.terrain.d8 import d8_receivers
    from hydromodpy.mesh.cells.zonal_stats import rasterize_cell_ids

    on_graph = np.asarray(routable, dtype=bool).reshape(-1)
    lakes = np.asarray(lake_of, dtype=int).reshape(-1)
    n_cells = int(on_graph.size)
    pinned = np.full(n_cells, -1, dtype=int)
    channel = np.zeros(n_cells, dtype=bool)
    nrows, ncols = tree.link.shape
    if nrows == 0 or ncols == 0 or not np.any(tree.link):
        return pinned, channel

    labels = rasterize_cell_ids(planar_mesh, transform=tree.transform, out_shape=(nrows, ncols))
    labels = np.where(labels < n_cells, labels, -1)
    can_hold = on_graph & (lakes < 0)
    a_pixels = np.flatnonzero(tree.link.reshape(-1))
    a_labels = labels.reshape(-1)[a_pixels]
    keep = a_labels >= 0
    keep[keep] = can_hold[a_labels[keep]]
    a_pixels, a_labels = a_pixels[keep], a_labels[keep]
    if a_pixels.size == 0:
        return pinned, channel
    channel[a_labels] = True

    # Exit pixel of each channel cell: the last of its A pixels sorted by accumulation.
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
            if other >= 0 and flat_link[current] and channel[other]:
                pinned[cell] = other
            break
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
