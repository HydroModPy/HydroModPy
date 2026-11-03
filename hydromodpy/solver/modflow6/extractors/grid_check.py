"""Check the grid MODFLOW 6 solved against the cell mesh the run stored.

The mesh is written once, before the run, from the cell mesh. The grid file
(``.grb``) that MODFLOW 6 leaves is what the heads are laid out on. If the two
differ, a field sealed into the store would sit on the wrong cells, so the
extractor compares them and refuses to go on when they do not agree.

Two differences are expected and accepted: flopy rounds every coordinate it
writes (see ``support.written_grid``), and DISV wants clockwise rings, so a
counter-clockwise cell comes back with its ring walked the other way.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from hydromodpy.core.exceptions import IncompatibleMeshError, MeshError
from hydromodpy.core.logging import get_logger
from hydromodpy.solver.modflow6.support.written_grid import reoriented_rows, written_step

logger = get_logger(__name__)

# Half a rounding step, plus a hair for the float64 spacing of the product.
_ROUNDING_SHARE = 0.505


@dataclass(frozen=True)
class GridCheck:
    """What the comparison measured: how far the solved grid sits from the stored mesh."""

    max_vertex_shift_m: float
    max_center_shift_m: float | None
    n_reversed_cells: int


def grb_rings(grd: Any) -> np.ndarray:
    """Return the cell rings of a grid file as padded ``int32`` rows, closing node dropped.

    MODFLOW 6 writes each DISV ring closed (first node repeated at the end).
    Rows are padded with ``-1`` to the longest ring.
    """
    iavert = getattr(grd, "iavert", None)
    javert = getattr(grd, "javert", None)
    if iavert is None or javert is None:
        raise MeshError(
            "the MODFLOW 6 grid file lists no cell vertices: only DISV grids can be checked"
        )
    starts = np.asarray(iavert, dtype=np.int64)[:-1]
    ends = np.asarray(iavert, dtype=np.int64)[1:]
    nodes = np.asarray(javert, dtype=np.int64)
    length = ends - starts
    closed = (length > 1) & (nodes[starts] == nodes[ends - 1])
    size = length - closed
    if size.size == 0 or int(size.min()) < 3:
        raise MeshError("the MODFLOW 6 grid file holds a cell with fewer than 3 vertices")
    columns = np.arange(int(size.max()))[None, :]
    rings = np.where(
        columns < size[:, None],
        nodes[np.minimum(starts[:, None] + columns, nodes.size - 1)],
        -1,
    )
    return rings.astype(np.int32)


def grb_geometry(grd: Any) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(vertices (n, 2), padded rings)`` of a DISV grid file."""
    verts = getattr(grd, "verts", None)
    if verts is None:
        raise MeshError("the MODFLOW 6 grid file lists no vertices: only DISV grids can be checked")
    return np.asarray(verts, dtype=np.float64)[:, :2], grb_rings(grd)


def _padded(rows: np.ndarray, width: int) -> np.ndarray:
    rows = np.asarray(rows, dtype=np.int64)
    if rows.shape[1] >= width:
        return rows
    pad = np.full((rows.shape[0], width - rows.shape[1]), -1, dtype=np.int64)
    return np.hstack([rows, pad])


def _ring_text(row: np.ndarray) -> str:
    return "[" + ", ".join(str(int(node)) for node in row if node >= 0) + "]"


def _coordinate_shift(
    solved: np.ndarray, stored: np.ndarray
) -> tuple[np.ndarray, tuple[int, int] | None]:
    """Return the absolute shifts and the first ``(row, axis)`` beyond half a rounding step."""
    shift = np.abs(solved - stored)
    within = shift <= _ROUNDING_SHARE * written_step(stored)
    if within.all():
        return shift, None
    row = int(np.flatnonzero(~within.all(axis=1))[0])
    return shift, (row, int(np.flatnonzero(~within[row])[0]))


def verify_disv_grid(
    grd: Any,
    *,
    vertices: np.ndarray,
    connectivity: np.ndarray,
    centers: np.ndarray | None = None,
) -> GridCheck:
    """Compare a DISV grid file with the stored mesh; raise ``IncompatibleMeshError`` on a difference.

    ``vertices`` and ``connectivity`` are the stored ``mesh/`` arrays and
    ``centers`` the stored cell centers, ``None`` for a store that has none (the
    centers are then left unchecked). The counts, then every ring, then the
    coordinates are compared; the first cell or vertex that differs is named.
    """
    solved_xy, solved_rings = grb_geometry(grd)
    stored_xy = np.asarray(vertices, dtype=np.float64)[:, :2]
    stored_rows = np.asarray(connectivity)
    if solved_xy.shape[0] != stored_xy.shape[0]:
        raise IncompatibleMeshError(
            f"the solved grid has {solved_xy.shape[0]} vertices, the stored mesh {stored_xy.shape[0]}"
        )
    if solved_rings.shape[0] != stored_rows.shape[0]:
        raise IncompatibleMeshError(
            f"the solved grid has {solved_rings.shape[0]} cells, the stored mesh {stored_rows.shape[0]}"
        )

    width = max(solved_rings.shape[1], stored_rows.shape[1])
    solved = _padded(solved_rings, width)
    stored = _padded(stored_rows, width)
    same = (solved == stored).all(axis=1)
    reversed_ring = ~same & (solved == reoriented_rows(stored)).all(axis=1)
    differs = ~(same | reversed_ring)
    if differs.any():
        cell = int(np.flatnonzero(differs)[0])
        raise IncompatibleMeshError(
            f"cell {cell} is {_ring_text(solved[cell])} in the solved grid and "
            f"{_ring_text(stored[cell])} in the stored mesh ({int(differs.sum())} cells differ)"
        )

    shift, outside = _coordinate_shift(solved_xy, stored_xy)
    if outside is not None:
        raise IncompatibleMeshError(
            _moved_message("vertex", outside, shift, stored_xy, using=stored_rows)
        )

    center_shift = None
    solved_centers = getattr(grd, "cellcenters", None)
    if centers is not None and solved_centers is not None:
        stored_centers = np.asarray(centers, dtype=np.float64)
        center_shift, outside = _coordinate_shift(
            np.asarray(solved_centers, dtype=np.float64)[:, :2], stored_centers
        )
        if outside is not None:
            raise IncompatibleMeshError(
                _moved_message("centre of cell", outside, center_shift, stored_centers)
            )
    return GridCheck(
        max_vertex_shift_m=float(shift.max()),
        max_center_shift_m=None if center_shift is None else float(center_shift.max()),
        n_reversed_cells=int(reversed_ring.sum()),
    )


def _moved_message(
    what: str,
    outside: tuple[int, int],
    shift: np.ndarray,
    stored: np.ndarray,
    *,
    using: np.ndarray | None = None,
) -> str:
    row, axis = outside
    text = (
        f"{what} {row} is {float(shift[row, axis]):.3g} m off along {'xy'[axis]} "
        f"(stored {float(stored[row, axis])!r}); largest shift {float(shift.max()):.3g} m"
    )
    if using is not None:
        cells = np.flatnonzero((using == row).any(axis=1))
        text += f"; first cell using it: {int(cells[0])}" if cells.size else ""
    return text


def verify_grid_against_store(grd: Any, root: Any, *, sim_id: str) -> GridCheck | None:
    """Compare a DISV grid file with the ``mesh/`` group of a run's store (``root``).

    A store that holds no geometry (a direct call of an extractor on a store
    created by hand) cannot be checked: the run is warned, and the caller adds
    its vertical part alone. Vertices are never written from the grid file.
    """
    mesh = root["mesh"] if "mesh" in root else {}
    if "vertices" not in mesh or "face_node_connectivity" not in mesh:
        logger.warning(
            "Run %s stores no mesh geometry: the solved grid is not checked and no vertex is written.",
            sim_id,
        )
        return None
    centers = None
    if "face_x" in mesh and "face_y" in mesh:
        centers = np.column_stack([np.asarray(mesh["face_x"][:]), np.asarray(mesh["face_y"][:])])
    try:
        check = verify_disv_grid(
            grd,
            vertices=np.asarray(mesh["vertices"][:]),
            connectivity=np.asarray(mesh["face_node_connectivity"][:]),
            centers=centers,
        )
    except IncompatibleMeshError as exc:
        raise IncompatibleMeshError(
            f"Run {sim_id}: the grid MODFLOW 6 solved is not the mesh the run stored: {exc}"
        ) from exc
    logger.info(
        "Run %s: the solved grid matches the stored mesh (largest vertex shift %.3g m, "
        "%d cells walked the other way).",
        sim_id,
        check.max_vertex_shift_m,
        check.n_reversed_cells,
    )
    return check
