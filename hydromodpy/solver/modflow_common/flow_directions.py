"""Build the descent D of a ``SolverMesh``, the routing copy of its top.

D gives every cell one receiver, the neighbour its water goes to, on a copy of
the model top filled until each cell drains (:mod:`hydromodpy.core.descent`).
D never goes back to the solver, and the top it is built from is the one the
solver sees, after the lake carve. Both MODFLOW backends build D once per build,
from this module, so neither imports the other. The adapter reads the planar
mesh and the activity of the solver mesh, takes the lake footprints and the
constant-head cells as explicit masks, and hands them to
:func:`hydromodpy.core.descent.build_descent`.

A is the generated river network, traced on the D8 pointer of the routing DEM.
Without it, D descends its own flats by flood order and runs beside A, so the
hillslope joins it lower down. With it, a cell A crosses has a pinned receiver,
the next cell along A (``channel_tree.py``), and every other cell takes the
steepest descent. On a domain that is the catchment itself
(``geographic.domain_extent = "watershed"``) D is flooded from the catchment
outlet and the constant-head cells, not from the whole rim.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from hydromodpy.core.depression_filling import DEFAULT_EPSILON_M
from hydromodpy.core.descent import Descent, build_descent
from hydromodpy.core.logging import get_logger
from hydromodpy.core.stream_geometry import resolve_outlet
from hydromodpy.solver.modflow_common.catchment_basin import (
    domain_is_the_catchment,
    finite_cell_areas,
    outlet_search,
)
from hydromodpy.solver.modflow_common.channel_tree import ChannelTree, project_channel_tree

__all__ = ["build_solver_mesh_descent", "resolve_dam_foot_cells"]

logger = get_logger(__name__)

DESCENT_EPSILON_M = DEFAULT_EPSILON_M
"""Flood step of D, recorded with it so a reader knows the drop it guarantees."""


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
    if domain_is_the_catchment(geographic):
        near, within = outlet_search(geographic, solver_mesh, descent)
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
                cell_area_m2=finite_cell_areas(solver_mesh),
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
