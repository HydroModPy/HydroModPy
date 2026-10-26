"""Build the descent D of a ``SolverMesh``, the routing copy of its top.

Both MODFLOW backends build D once per build, from this module, so neither
imports the other. The adapter reads the planar mesh and the activity of the
solver mesh, takes the lake footprints and the constant-head cells as explicit
masks, and hands them to :func:`hydromodpy.core.descent.build_descent`. D never
goes back to the solver; the top it is built from is the one the solver sees,
after the lake carve.

It also projects the generated river network A onto the mesh. A was traced on
the D8 pointer of the routing DEM. Without that projection, D descends its own
flats by flood order and runs beside A, so the hillslope joins it lower down.
With it, D follows A on the cells A crosses (pinned receivers) and the steepest
descent elsewhere.

It computes the basin of D at the catchment outlet, once per build
(:func:`run_basin`), the catchment every consumer of the run reads. On a domain
that is the catchment itself (``geographic.domain_extent = "watershed"``) D is
flooded from that outlet and the constant-head cells, not from the whole rim.
The basin carries the share of each cell's area inside the delineated polygon,
the weight of a catchment total of a spatial quantity.

The build leaves D and its basin beside the model as ``<model>.descent.npz``:
the extractors never see the model, so they read this sidecar back with
:func:`read_descent_sidecar` and store D with the run.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, get_args

import numpy as np

from hydromodpy.core.depression_filling import DEFAULT_EPSILON_M
from hydromodpy.core.descent import (
    BasinRule,
    Descent,
    DescentBasin,
    build_descent,
    descent_basin,
)
from hydromodpy.core.field_routing import accumulate_on_downhill_graph
from hydromodpy.core.logging import get_logger
from hydromodpy.core.stream_geometry import CATCHMENT_MISMATCH_WARNING_SHARE, resolve_outlet
from hydromodpy.solver.modflow_common.catchment_support import (
    polygon_cell_fraction,
    polygon_cell_mask,
)

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
    "resolve_dam_foot_cells",
    "run_basin",
    "write_descent_sidecar",
)

DESCENT_SIDECAR_SUFFIX = ".descent.npz"
"""Suffix of the file the build leaves beside the model for the extractor."""

DESCENT_EPSILON_M = DEFAULT_EPSILON_M
"""Flood step of D, recorded with it so a reader knows the drop it guarantees."""

_ADJACENCY_KINDS = ("shared_nodes", "shared_faces")
_REPORT_COUNTS = ("n_raised", "n_lake_flooded", "n_pinned_raised", "n_channel", "n_pinned")
_REPORT_MAXIMA_M = ("max_raise_m", "max_lake_flood_m", "max_pinned_raise_m")
_BASIN_KEYS = ("basin", "basin_outlet", "basin_rule", "basin_area_m2", "basin_seeded_at_outlet")
_FRACTION_KEY = "catchment_fraction"

# File names written by spatial.geographic.core.river_network.
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
    configuration with links on, and the stream raster is read instead (see
    :func:`active_channel_raster`). ``required`` is set when a network of the run
    was delineated from A, so missing rasters are an error.
    """
    from hydromodpy.spatial.geographic.core.flow_products import DIRECTION_NAME

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
    link = active_channel_raster(folder)
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
    geographic: object | None = None,
) -> Descent:
    """Return D on ``solver_mesh``, its lakes traversed and its CHD cells seeded.

    A column is routable when it is active, or when it holds a lake cell: a
    fixed-area lake is inactive in the solver and must still be crossed.
    ``active_column`` defaults to the columns of ``solver_mesh`` with an active
    layer; a backend whose activity lives elsewhere (the NWT ``ibound``) passes
    its own. Lakes are numbered in the iteration order of
    ``lake_cells_by_lake``, the order build.py numbers LAK lakes in.
    ``base_level_mask`` holds the constant-head cells, where water leaves the
    model: they seed the flood and keep their steepest descent.
    ``channel_tree`` is the generated network A; without it D has no pin and
    follows the steepest descent everywhere. The adjacency is fixed by the
    mesh: shared nodes (D8) on quads, shared faces elsewhere.

    ``geographic`` says where the catchment closes. When its domain is the
    catchment (``domain_extent = "watershed"``), D is built twice: seeded on
    the rim to find the outlet as :func:`run_basin` will, then seeded at that
    outlet and the constant-head cells only.
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

    def flood(outlet: int | None) -> Descent:
        return build_descent(
            np.asarray(solver_mesh.top, dtype=float),
            solver_mesh.cell_mesh.geometry.padded_connectivity,
            vertices=np.asarray(planar_mesh.vertices, dtype=float)[:, :2],
            centroids=solver_mesh.cell_mesh.centers,
            routable=routable,
            base_level=base_level_mask,
            lake_of=lake_of,
            pinned_receiver=pinned_receiver,
            channel=channel,
            epsilon=DESCENT_EPSILON_M,
            outlet=outlet,
        )

    descent = flood(None)
    if _domain_is_the_catchment(geographic):
        near, within = _outlet_search(geographic, solver_mesh, descent)
        if near is None and within is None:
            logger.warning(
                "geographic.domain_extent = 'watershed' but the run has neither an outlet "
                "point nor a watershed polygon: D stays seeded on the domain rim."
            )
        else:
            outlet = resolve_outlet(
                descent.metric,
                near=near,
                within=within,
                adjacency=descent.adjacency,
                cell_area_m2=_cell_areas(solver_mesh),
            )
            descent = flood(outlet)
            logger.info(
                "Descent D seeded at the outlet cell %d and the constant-head cells: the "
                "domain is the catchment.",
                outlet,
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


def run_basin(geographic: object | None, solver_mesh: Any, descent: Descent) -> DescentBasin:
    """Return the basin of D at the catchment outlet, the one call of this build.

    The outlet is searched near the point the catchment was closed on (the
    snapped outlet, else the declared one), else inside the watershed polygon
    (cells whose centre it covers), else the basin is only the largest one of
    the domain. Call it before D drops its adjacency. The polygon is compared
    with the basin: a gap above ``CATCHMENT_MISMATCH_WARNING_SHARE`` of its
    area is a warning, as in the stream criterion.

    A basin that closes a catchment carries the share of each cell's area
    inside the delineated polygon (``catchment_fraction``), when the run has
    one. It weights the catchment totals of a spatial quantity and leaves the
    cells of the basin as they are.
    """
    areas = _cell_areas(solver_mesh)
    near, within = _outlet_search(geographic, solver_mesh, descent)
    seeded = _domain_is_the_catchment(geographic) and (near is not None or within is not None)
    basin = descent_basin(
        descent, cell_area_m2=areas, near=near, within=within, seeded_at_outlet=seeded
    )
    if seeded and not descent.base_level[basin.outlet]:
        raise ValueError(
            f"the outlet cell {basin.outlet} of the basin is not the cell D was seeded at: "
            "the two outlet searches of a watershed domain disagree."
        )
    if within is not None:
        _compare_with_the_polygon(basin, within, areas)
    logger.info(
        "Basin of D: %d cells (%.3f km2), outlet cell %d by rule %s, seeded at the outlet: %s.",
        int(basin.mask.sum()),
        basin.area_m2 / 1.0e6,
        basin.outlet,
        basin.rule,
        basin.seeded_at_outlet,
    )
    _count_constant_head_sinks(descent, basin, within, areas)
    if basin.is_catchment:
        fraction = polygon_cell_fraction(geographic, solver_mesh)
        if fraction is not None:
            basin = replace(basin, catchment_fraction=fraction)
            _report_the_fraction(basin, fraction, areas)
    return basin


def _report_the_fraction(basin: DescentBasin, fraction: np.ndarray, areas: np.ndarray) -> None:
    """Log how many cells the polygon outline cuts and the area the fraction weighs."""
    cut = (fraction > 0.0) & (fraction < 1.0)
    logger.info(
        "Catchment fraction: the polygon outline cuts %d cell(s), %d of them in the basin "
        "of D (%.2f %% of its cells); the polygon weighs %.3f km2 on the mesh against "
        "%.3f km2 for the basin.",
        int(cut.sum()),
        int((cut & basin.mask).sum()),
        100.0 * float((cut & basin.mask).sum()) / max(1, int(basin.mask.sum())),
        float((areas * fraction).sum()) / 1.0e6,
        float(areas[basin.mask].sum()) / 1.0e6,
    )


def _domain_is_the_catchment(geographic: object | None) -> bool:
    """Whether the active domain is the catchment itself, so D floods from its outlet."""
    # A synthetic geographic has no delineated extent: its domain is a box.
    return getattr(geographic, "domain_extent", "box") == "watershed"


def _cell_areas(solver_mesh: Any) -> np.ndarray:
    areas = np.asarray(solver_mesh.cell_areas(), dtype=float)
    return np.where(np.isfinite(areas), areas, 0.0)


def _outlet_search(
    geographic: object | None, solver_mesh: Any, descent: Descent
) -> tuple[tuple[float, float] | None, np.ndarray | None]:
    """Return ``(near, within)``: the closing point and the routable polygon cells."""
    within = polygon_cell_mask(geographic, solver_mesh)
    if within is not None:
        within = within & descent.routable
        if not np.any(within):
            within = None
    return _catchment_outlet_xy(geographic), within


def _catchment_outlet_xy(geographic: object | None) -> tuple[float, float] | None:
    """The point the catchment was closed on: the snapped outlet, else the declared one."""
    for x_name, y_name in (("x_outlet_snapped", "y_outlet_snapped"), ("x_outlet", "y_outlet")):
        x = getattr(geographic, x_name, None)
        y = getattr(geographic, y_name, None)
        if x is None or y is None:
            continue
        point = (float(x), float(y))
        if np.all(np.isfinite(point)):
            return point
    return None


def _compare_with_the_polygon(basin: DescentBasin, polygon: np.ndarray, areas: np.ndarray) -> None:
    """Log how far the basin of D lies from the watershed polygon, a warning above the share."""
    polygon_area = float(areas[polygon].sum())
    outside = basin.mask & ~polygon
    missing = polygon & ~basin.mask
    outside_share = float(areas[outside].sum()) / polygon_area if polygon_area else 0.0
    missing_share = float(areas[missing].sum()) / polygon_area if polygon_area else 0.0
    mismatch = outside_share + missing_share
    log = logger.warning if mismatch > CATCHMENT_MISMATCH_WARNING_SHARE else logger.info
    log(
        "Watershed polygon and basin of D: %d basin cells against %d in the polygon; %d "
        "basin cells outside the polygon (%.1f %% of its area), %d polygon cells outside "
        "the basin (%.1f %%).%s",
        int(basin.mask.sum()),
        int(polygon.sum()),
        int(outside.sum()),
        100.0 * outside_share,
        int(missing.sum()),
        100.0 * missing_share,
        (
            " The gap is above the warning share: the outlet may sit on another branch, "
            "or the mesh is much coarser than the DEM the polygon came from."
            if mismatch > CATCHMENT_MISMATCH_WARNING_SHARE
            else ""
        ),
    )


def _count_constant_head_sinks(
    descent: Descent, basin: DescentBasin, within: np.ndarray | None, areas: np.ndarray
) -> None:
    """Warn about the constant-head sinks of the catchment that take its upslope off the basin.

    A sink is a constant-head cell D ends at. The one the basin itself ends at
    is the outlet and is no loss. With a watershed polygon, only the sinks
    inside it count: one far outside it drains its own land.
    """
    sinks = descent.constant_head & descent.routable & (descent.receiver < 0) & ~basin.mask
    if within is not None:
        sinks &= within
    if not np.any(sinks):
        return
    drained = accumulate_on_downhill_graph(descent.metric.graph, areas)
    logger.warning(
        "Constant-head sinks of D: %d constant-head cell(s) have no lower neighbour; %.3f km2 "
        "drain into them and stay outside the basin.",
        int(sinks.sum()),
        float(drained[sinks].sum()) / 1.0e6,
    )


def resolve_dam_foot_cells(
    descent: Descent, spillway_seed_by_lake: Mapping[str, int]
) -> dict[str, int]:
    """Return ``{lake_id: cell}``, the cell below the dam of each declared spillway.

    Only a lake whose spillway is declared has a dam foot: the toe cell the
    production path already resolves for it (``spillway_seed_by_lake``, the cell
    the SFR channel is extended to). A lake without one would put the foot on
    the cell D already leaves through, so it has none. A foot that is a cell of
    a lake is dropped: the downstream lake has its own foot.
    """
    return {
        lake_id: int(cell)
        for lake_id, cell in spillway_seed_by_lake.items()
        if 0 <= int(cell) < descent.lake_of.size and descent.lake_of[int(cell)] < 0
    }


@dataclass(frozen=True, slots=True)
class DescentRecord:
    """D as the run stores it: per-cell arrays and the build report.

    ``receiver`` is -1 at an outlet (off the graph, or a seed with no lower
    neighbour); ``surface`` is the filled copy, NaN off the graph.
    ``constant_head`` flags the declared CHD seeds, ``raised`` the cells the
    flood raised. ``dam_foot`` holds the cell ids below the dams, possibly
    none. ``adjacency`` is ``"shared_nodes"`` or ``"shared_faces"``;
    ``epsilon`` is the flood step in metres.

    ``basin`` is the basin of D at the catchment outlet (outlet included),
    with the fields of :class:`hydromodpy.core.descent.DescentBasin`. It is
    None for a sidecar written before the basin was stored.
    ``catchment_fraction`` is the share of each cell's area inside the
    delineated polygon, None without a polygon.
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
    dam_foot: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=np.int64))
    basin: np.ndarray | None = None
    basin_outlet: int = -1
    basin_rule: str = ""
    basin_area_m2: float = float("nan")
    basin_seeded_at_outlet: bool = False
    catchment_fraction: np.ndarray | None = None

    def report(self) -> dict[str, int | float]:
        """The build report as plain scalars, counts then maxima in metres."""
        counts: dict[str, int | float] = {name: int(getattr(self, name)) for name in _REPORT_COUNTS}
        counts.update({name: float(getattr(self, name)) for name in _REPORT_MAXIMA_M})
        return counts


def write_descent_sidecar(
    descent: Descent,
    folder: str | Path,
    stem: str,
    *,
    dam_foot_cells: Mapping[str, int] | None = None,
    basin: DescentBasin | None = None,
) -> Path | None:
    """Leave D beside the model as ``<stem>.descent.npz``; return its path.

    ``dam_foot_cells`` are the cells below the dams, one per lake
    (:func:`resolve_dam_foot_cells`); none when the run has no lake.
    ``basin`` is the basin of D at the catchment outlet (:func:`run_basin`).

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
        "dam_foot": np.asarray(sorted(set((dam_foot_cells or {}).values())), dtype=np.int64),
    }
    for name in _REPORT_COUNTS:
        payload[name] = np.asarray(int(getattr(descent, name)), dtype=np.int64)
    for name in _REPORT_MAXIMA_M:
        payload[name] = np.asarray(float(getattr(descent, name)), dtype=np.float64)
    if basin is not None:
        payload.update(
            {
                "basin": np.asarray(basin.mask, dtype=bool),
                "basin_outlet": np.asarray(int(basin.outlet), dtype=np.int64),
                "basin_rule": np.asarray(str(basin.rule)),
                "basin_area_m2": np.asarray(float(basin.area_m2), dtype=np.float64),
                "basin_seeded_at_outlet": np.asarray(bool(basin.seeded_at_outlet)),
            }
        )
        if basin.catchment_fraction is not None:
            payload[_FRACTION_KEY] = np.asarray(basin.catchment_fraction, dtype=np.float64)
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
        its adjacency is not one this module writes, a dam foot is not a cell
        of the mesh, its basin lacks a field, names an unknown rule or an
        outlet outside it, or its catchment fraction comes without a basin or
        leaves [0, 1].
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
        # Absent from a sidecar written before the dam foot was kept: no foot.
        dam_foot = (
            np.asarray(payload["dam_foot"], dtype=np.int64).reshape(-1)
            if "dam_foot" in names
            else np.empty(0, dtype=np.int64)
        )
        scalars: dict[str, Any] = {"epsilon": float(payload["epsilon"])}
        scalars.update({name: int(payload[name]) for name in _REPORT_COUNTS})
        scalars.update({name: float(payload[name]) for name in _REPORT_MAXIMA_M})
        # Absent from a sidecar written before the basin was stored: no basin.
        basin_fields: dict[str, Any] = {}
        if "basin" in names:
            missing = sorted(set(_BASIN_KEYS) - names)
            if missing:
                raise ValueError(
                    f"the descent sidecar {path.name} holds a basin without {', '.join(missing)}."
                )
            arrays["basin"] = np.asarray(payload["basin"], dtype=bool).reshape(-1)
            basin_fields = {
                "basin_outlet": int(payload["basin_outlet"]),
                "basin_rule": str(payload["basin_rule"]),
                "basin_area_m2": float(payload["basin_area_m2"]),
                "basin_seeded_at_outlet": bool(payload["basin_seeded_at_outlet"]),
            }
        if _FRACTION_KEY in names:
            if "basin" not in names:
                raise ValueError(
                    f"the descent sidecar {path.name} holds a catchment fraction without a basin."
                )
            arrays[_FRACTION_KEY] = np.asarray(payload[_FRACTION_KEY], dtype=np.float64).reshape(-1)
    sizes = {name: int(values.size) for name, values in arrays.items()}
    if len(set(sizes.values())) != 1:
        raise ValueError(f"the descent sidecar {path.name} mixes cell counts: {sizes}.")
    if adjacency not in _ADJACENCY_KINDS:
        raise ValueError(
            f"the descent sidecar {path.name} names adjacency {adjacency!r}, "
            f"not one of {_ADJACENCY_KINDS}."
        )
    if dam_foot.size and (dam_foot.min() < 0 or dam_foot.max() >= next(iter(sizes.values()))):
        raise ValueError(f"the descent sidecar {path.name} holds a dam foot outside the mesh.")
    if "basin" in arrays:
        _check_stored_basin(path.name, arrays["basin"], basin_fields)
    if _FRACTION_KEY in arrays:
        fraction = arrays[_FRACTION_KEY]
        if not np.all((fraction >= 0.0) & (fraction <= 1.0)):
            raise ValueError(
                f"the descent sidecar {path.name} holds a catchment fraction outside [0, 1]."
            )
    return DescentRecord(
        **arrays, dam_foot=dam_foot, adjacency=adjacency, **scalars, **basin_fields
    )


def _check_stored_basin(name: str, mask: np.ndarray, fields: Mapping[str, Any]) -> None:
    """Raise unless the stored basin names a known rule and holds its own outlet."""
    if fields["basin_rule"] not in get_args(BasinRule):
        raise ValueError(
            f"the descent sidecar {name} names basin rule {fields['basin_rule']!r}, "
            f"not one of {get_args(BasinRule)}."
        )
    outlet = int(fields["basin_outlet"])
    if not 0 <= outlet < mask.size or not mask[outlet]:
        raise ValueError(f"the descent sidecar {name} holds a basin outlet outside its basin.")
