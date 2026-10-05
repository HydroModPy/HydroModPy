"""Build the descent D of a ``SolverMesh``, the routing copy of its top.

Both MODFLOW backends build D once per build, from this module, so neither
imports the other. The adapter reads the planar mesh and the activity of the
solver mesh, takes the lake footprints and the constant-head cells as explicit
masks, and hands them to :func:`hydromodpy.core.descent.build_descent`. D never
goes back to the solver; the top it is built from is the one the solver sees,
after the lake carve and the optional top conditioning.

It also projects the generated river network A onto the mesh. A was traced on
the D8 pointer of the routing DEM. Without that projection, D descends its own
flats by flood order and runs beside A, so the hillslope joins it lower down.
With it, D follows A on the cells A crosses (pinned receivers) and the steepest
descent elsewhere.

The build leaves D beside the model as ``<model>.descent.npz``, the way it
leaves ``.conditioning_ref.npy``: the extractors never see the model, so they
read this sidecar back with :func:`read_descent_sidecar` and store D with the
run.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.core.depression_filling import DEFAULT_EPSILON_M
from hydromodpy.core.descent import Descent, build_descent
from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)

__all__ = (
    "DESCENT_SIDECAR_SUFFIX",
    "ChannelTree",
    "DescentRecord",
    "build_solver_mesh_descent",
    "channel_tree_for_run",
    "project_channel_tree",
    "read_channel_tree",
    "read_descent_sidecar",
    "write_descent_sidecar",
)

DESCENT_SIDECAR_SUFFIX = ".descent.npz"
"""Suffix of the file the build leaves beside the model for the extractor."""

DESCENT_EPSILON_M = DEFAULT_EPSILON_M
"""Flood step of D, recorded with it so a reader knows the drop it guarantees."""

_ADJACENCY_KINDS = ("shared_nodes", "shared_faces")
_REPORT_COUNTS = ("n_raised", "n_lake_flooded", "n_pinned_raised", "n_channel", "n_pinned")
_REPORT_MAXIMA_M = ("max_raise_m", "max_lake_flood_m", "max_pinned_raise_m")

# File names written by spatial.geographic.core.river_network.
_LINK_NAME = "dem_stream_link_id_full.tif"
_STREAMS_NAME = "dem_streams_full.tif"
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


def channel_tree_for_run(
    geographic: object, solver_mesh: Any, *, required: bool = False
) -> ChannelTree | None:
    """The generated network A around the mesh, or None when the run has none.

    A is the full-extent stream-link raster of the river-network step (the
    stream raster when links were not computed), with the D8 pointer it was
    traced on and its accumulation, all in ``geographic.correcflow_path``. The
    clipped rasters are cut to the watershed and miss the buffer.

    A belongs to the run only when ``geographic.river_network_enabled`` says the
    step ran for it; rasters an earlier configuration left in the folder are
    never read. The step writes the link raster from its stream raster, so a
    link raster older than the stream raster beside it was left by an earlier
    configuration with links on, and the stream raster is read instead.

    A burned routing DEM pins nothing: A then follows the observed map, and an
    observation never enters the routing. ``required`` is set when a network of
    the run was delineated from A, so missing rasters are an error.
    """
    from hydromodpy.spatial.geographic.core.flow_products import DIRECTION_NAME

    if getattr(geographic, "stream_burn_enabled", False):
        # Measured on example 21 (10 m burn): pinned on the burned network, D sent
        # 2.4 % of the catchment off the outlet and dropped the outlet flow by 2.7 %.
        logger.info(
            "The routing DEM carries the burned observed network "
            "([geographic.enforce_streams]): A is traced on the map and an observation "
            "never enters the routing, so the descent D is not pinned on A."
        )
        return None
    if not required and not getattr(geographic, "river_network_enabled", False):
        logger.info(
            "The river network is off for this run: the descent D has no pinned cell and "
            "follows the steepest descent everywhere."
        )
        return None
    folder = getattr(geographic, "correcflow_path", None)
    if folder is None:
        logger.info(
            "No corrected-flow folder for this run: the descent D has no pinned cell and "
            "follows the steepest descent everywhere."
        )
        return None
    streams = os.path.join(str(folder), _STREAMS_NAME)
    link = os.path.join(str(folder), _LINK_NAME)
    if not os.path.exists(link) or (
        os.path.exists(streams) and os.path.getmtime(link) < os.path.getmtime(streams)
    ):
        link = streams
    pointer = os.path.join(str(folder), DIRECTION_NAME)
    accumulation = os.path.join(str(folder), _ACCUMULATION_NAME)
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
            folder,
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
    from hydromodpy.spatial.mesh.ops.zonal_stats import rasterize_cell_ids
    from hydromodpy.spatial.terrain.port import D8_WBT_OFFSETS

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

    offsets = {int(code): step for code, step in D8_WBT_OFFSETS.items()}
    link = tree.link
    max_steps = nrows * ncols
    for cell, pixel in exit_pixel.items():
        row, col = divmod(int(pixel), ncols)
        for _ in range(max_steps):
            step = offsets.get(int(tree.pointer[row, col]))
            if step is None:
                break
            row, col = row + step[0], col + step[1]
            if not (0 <= row < nrows and 0 <= col < ncols):
                break
            other = int(labels[row, col])
            if other == cell:
                continue
            if other >= 0 and link[row, col] and channel[other]:
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


def build_solver_mesh_descent(
    solver_mesh: Any,
    *,
    lake_cells_by_lake: Mapping[Any, Sequence[int]],
    base_level_mask: np.ndarray | None,
    channel_tree: ChannelTree | None = None,
    active_column: np.ndarray | None = None,
) -> Descent:
    """Return D on ``solver_mesh``, its lakes traversed and its CHD cells seeded.

    A column is routable when it is active, or when it holds a lake cell: a
    fixed-area lake is inactive in the solver and must still be crossed.
    ``active_column`` defaults to the columns of ``solver_mesh`` with an active
    layer; a backend whose activity lives elsewhere (the NWT ``ibound``) passes
    its own. Lakes are numbered in the iteration order of
    ``lake_cells_by_lake``, the order build.py numbers LAK lakes in.
    ``base_level_mask`` holds the constant-head cells, where water leaves the
    model: they seed the flood and keep their steepest descent. ``channel_tree`` is the generated network A; without it D has no pin
    and follows the steepest descent everywhere. The adjacency is fixed by the
    mesh: shared nodes (D8) on quads, shared faces elsewhere.
    """
    planar_mesh = solver_mesh.planar_mesh
    n_cells = int(solver_mesh.n_cells)
    lake_of = np.full(n_cells, -1, dtype=int)
    for number, cells in enumerate(lake_cells_by_lake.values()):
        lake_of[np.asarray(list(cells), dtype=int)] = number
    if active_column is None:
        active_column = (~np.asarray(solver_mesh.inactive_mask, dtype=bool)).any(axis=0)
    routable = np.asarray(active_column, dtype=bool).reshape(-1) | (lake_of >= 0)
    pinned_receiver: np.ndarray | None = None
    channel: np.ndarray | None = None
    if channel_tree is not None:
        pinned_receiver, channel = project_channel_tree(
            channel_tree, planar_mesh, routable=routable, lake_of=lake_of
        )
        logger.info(
            "Channel tree A on the mesh: %d channel cell(s), %d pinned to the next cell "
            "of A, %d outlet(s) of A keeping the steepest descent.",
            int(channel.sum()),
            int((pinned_receiver >= 0).sum()),
            int((channel & (pinned_receiver < 0)).sum()),
        )
    descent = build_descent(
        np.asarray(solver_mesh.top, dtype=float),
        _padded_connectivity(planar_mesh.flat_connectivity, n_cells),
        vertices=np.asarray(planar_mesh.vertices, dtype=float)[:, :2],
        centroids=solver_mesh.cell_centroids(),
        routable=routable,
        base_level=base_level_mask,
        lake_of=lake_of,
        pinned_receiver=pinned_receiver,
        channel=channel,
        epsilon=DESCENT_EPSILON_M,
    )
    logger.info(
        "Descent D: %d cell(s) raised on the routing copy of the top (max +%.2f m), "
        "%d lake cell(s) flooded (max +%.2f m), %d of %d pinned channel cell(s) raised "
        "(max +%.2f m), adjacency by %s, %d seed cell(s), %d lake(s) traversed.",
        descent.n_raised,
        descent.max_raise_m,
        descent.n_lake_flooded,
        descent.max_lake_flood_m,
        descent.n_pinned_raised,
        descent.n_pinned,
        descent.max_pinned_raise_m,
        "shared nodes (D8)" if descent.diagonal_neighbors else "shared faces",
        int(descent.base_level.sum()),
        len(lake_cells_by_lake),
    )
    return descent


def _padded_connectivity(flat_connectivity: Any, n_cells: int) -> np.ndarray:
    """Return the per-cell node lists as one array padded with -1."""
    if isinstance(flat_connectivity, np.ndarray):
        return np.asarray(flat_connectivity, dtype=int)[:n_cells]
    rows = [np.asarray(nodes, dtype=int).reshape(-1) for nodes in flat_connectivity][:n_cells]
    width = max((row.size for row in rows), default=0)
    padded = np.full((n_cells, width), -1, dtype=int)
    for cell, row in enumerate(rows):
        padded[cell, : row.size] = row
    return padded


@dataclass(frozen=True, slots=True)
class DescentRecord:
    """D as the run stores it: per-cell arrays and the build report.

    ``receiver`` is -1 at an outlet (off the graph, or a seed with no lower
    neighbour); ``surface`` is the filled copy, NaN off the graph.
    ``constant_head`` flags the declared CHD seeds, ``raised`` the cells the
    flood raised. ``adjacency`` is ``"shared_nodes"`` or ``"shared_faces"``;
    ``epsilon`` is the flood step in metres.
    """

    receiver: np.ndarray
    surface: np.ndarray
    base_level: np.ndarray
    constant_head: np.ndarray
    raised: np.ndarray
    channel: np.ndarray
    pinned: np.ndarray
    adjacency: str
    epsilon: float
    n_raised: int
    max_raise_m: float
    n_lake_flooded: int
    max_lake_flood_m: float
    n_pinned_raised: int
    max_pinned_raise_m: float
    n_channel: int
    n_pinned: int

    def report(self) -> dict[str, int | float]:
        """The build report as plain scalars, counts then maxima in metres."""
        counts: dict[str, int | float] = {name: int(getattr(self, name)) for name in _REPORT_COUNTS}
        counts.update({name: float(getattr(self, name)) for name in _REPORT_MAXIMA_M})
        return counts


def write_descent_sidecar(descent: Descent, folder: str | Path, stem: str) -> Path | None:
    """Leave D beside the model as ``<stem>.descent.npz``; return its path.

    A file that cannot be written is a warning, not a failure: the run solves
    without it, and its readers rebuild an unpinned D from the stored top.
    """
    path = Path(folder) / f"{stem}{DESCENT_SIDECAR_SUFFIX}"
    payload: dict[str, np.ndarray] = {
        "receiver": np.asarray(descent.receiver, dtype=np.int64),
        "surface": np.asarray(descent.surface, dtype=np.float64),
        "base_level": np.asarray(descent.base_level, dtype=bool),
        "constant_head": np.asarray(descent.constant_head, dtype=bool),
        "raised": np.asarray(descent.raised, dtype=bool),
        "channel": np.asarray(descent.channel, dtype=bool),
        "pinned": np.asarray(descent.pinned, dtype=bool),
        "adjacency": np.asarray(_ADJACENCY_KINDS[0 if descent.diagonal_neighbors else 1]),
        "epsilon": np.asarray(DESCENT_EPSILON_M, dtype=np.float64),
    }
    for name in _REPORT_COUNTS:
        payload[name] = np.asarray(int(getattr(descent, name)), dtype=np.int64)
    for name in _REPORT_MAXIMA_M:
        payload[name] = np.asarray(float(getattr(descent, name)), dtype=np.float64)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(path, **payload)
    except OSError:
        logger.warning(
            "Could not write the descent sidecar %s: the run stores no descent, and its "
            "flow direction map and accumulation fluxes rebuild one without pins.",
            path,
            exc_info=True,
        )
        return None
    return path


def read_descent_sidecar(path: str | Path) -> DescentRecord | None:
    """Read the sidecar :func:`write_descent_sidecar` left, None when it is absent.

    Raises
    ------
    ValueError
        When the file lacks an array, its arrays disagree on the cell count,
        or its adjacency is not one this module writes.
    """
    path = Path(path)
    if not path.is_file():
        return None
    with np.load(path, allow_pickle=False) as payload:
        names = set(payload.files)
        expected = {
            "receiver",
            "surface",
            "base_level",
            "constant_head",
            "raised",
            "channel",
            "pinned",
            "adjacency",
            "epsilon",
            *_REPORT_COUNTS,
            *_REPORT_MAXIMA_M,
        }
        absent = sorted(expected - names)
        if absent:
            raise ValueError(f"the descent sidecar {path.name} lacks {', '.join(absent)}.")
        arrays = {
            "receiver": np.asarray(payload["receiver"], dtype=np.int64).reshape(-1),
            "surface": np.asarray(payload["surface"], dtype=np.float64).reshape(-1),
            "base_level": np.asarray(payload["base_level"], dtype=bool).reshape(-1),
            "constant_head": np.asarray(payload["constant_head"], dtype=bool).reshape(-1),
            "raised": np.asarray(payload["raised"], dtype=bool).reshape(-1),
            "channel": np.asarray(payload["channel"], dtype=bool).reshape(-1),
            "pinned": np.asarray(payload["pinned"], dtype=bool).reshape(-1),
        }
        adjacency = str(payload["adjacency"])
        scalars: dict[str, Any] = {"epsilon": float(payload["epsilon"])}
        scalars.update({name: int(payload[name]) for name in _REPORT_COUNTS})
        scalars.update({name: float(payload[name]) for name in _REPORT_MAXIMA_M})
    sizes = {name: int(values.size) for name, values in arrays.items()}
    if len(set(sizes.values())) != 1:
        raise ValueError(f"the descent sidecar {path.name} mixes cell counts: {sizes}.")
    if adjacency not in _ADJACENCY_KINDS:
        raise ValueError(
            f"the descent sidecar {path.name} names adjacency {adjacency!r}, "
            f"not one of {_ADJACENCY_KINDS}."
        )
    return DescentRecord(**arrays, adjacency=adjacency, **scalars)
