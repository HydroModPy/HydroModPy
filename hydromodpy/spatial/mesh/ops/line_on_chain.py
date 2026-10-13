"""Share the length of a line among the cells of a mesh, in order along it.

Two rules, one per kind of mesh:

* the mesh carries the cell chains of the line family (``rivers``): every chain
  cell goes to the line nearest its centre, when that line passes within one
  cell size of it, and each line shares its length among its cells in 1D. The
  cells are ordered by the projection of their centres on the line and the
  cuts sit halfway between two consecutive projections, so the shares add up
  to the line length and no length is counted twice;
* the mesh carries no chain: the line is cut where it crosses the cell
  boundaries and each cell receives the length of the line inside it. A piece
  lying on a shared edge goes to the cell of smaller id.

Both return, per cell, the length and the distance along the line of the middle
of its share, ordered from the start of the line to its end.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import shapely
from shapely.strtree import STRtree

from hydromodpy.spatial.mesh.ops.vector_cell_mask import cell_polygons

if TYPE_CHECKING:
    from shapely.geometry import LineString

    from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh

__all__ = ["LinePiece", "chain_pieces", "crossing_pieces"]

MIN_PIECE_LENGTH_M = 1.0e-6
"""A share shorter than this [m] is a corner graze, not a reach."""


@dataclass(frozen=True)
class LinePiece:
    """The share of one line held by one cell.

    ``length`` [m] is the length of the share and ``middle`` [m] the distance
    along the line of its middle.
    """

    cell: int
    length: float
    middle: float


def chain_pieces(
    cell_mesh: PlanarCellMesh, lines: Sequence[LineString], *, family: str
) -> list[list[LinePiece]]:
    """Share each line among the chain cells of ``family`` nearest to it.

    A chain cell belongs to the nearest line within its size ``sqrt(area)``,
    the smallest line index on a tie. A line that owns no cell takes the chain
    cell nearest to it, when one lies within its size. A line with no chain
    cell within one cell size gets no piece. The shares of a line add up to its
    length; a share shorter than ``MIN_PIECE_LENGTH_M`` joins the one before it,
    or the one after it at the start of the line.
    """
    chains = cell_mesh.chains(family)
    if not chains or not lines:
        return [[] for _ in lines]
    cells = np.unique(np.concatenate([chain.cell_ids for chain in chains]))
    centres = shapely.points(cell_mesh.centers[cells])
    sizes = np.sqrt(cell_mesh.geometry.areas[cells])
    line_array = np.asarray(lines, dtype=object)
    (point_index, line_index), distance = STRtree(line_array).query_nearest(
        centres, return_distance=True, all_matches=True
    )
    order = np.lexsort((line_index, point_index))
    point_index, line_index, distance = point_index[order], line_index[order], distance[order]
    first = np.ones(point_index.size, dtype=bool)
    first[1:] = point_index[1:] != point_index[:-1]
    near = first & (distance <= sizes[point_index])
    owner = np.full(cells.size, -1, dtype=np.int64)
    owner[point_index[near]] = line_index[near]

    pieces: list[list[LinePiece]] = []
    for index, line in enumerate(lines):
        owned = np.flatnonzero(owner == index)
        if owned.size == 0:
            gap = shapely.distance(line, centres)
            within = np.flatnonzero(gap <= sizes)
            owned = within[np.argmin(gap[within])][None] if within.size else owned
        pieces.append(_shared_along(line, cells[owned], cell_mesh.centers[cells[owned]]))
    return pieces


def _shared_along(line: LineString, cells: np.ndarray, centres: np.ndarray) -> list[LinePiece]:
    """Share the line among cells cut halfway between their projections."""
    if cells.size == 0:
        return []
    along = shapely.line_locate_point(line, shapely.points(centres))
    order = np.lexsort((cells, along))
    cells, along = cells[order], along[order]
    length = float(line.length)
    cuts = np.concatenate([[0.0], 0.5 * (along[1:] + along[:-1]), [length]])
    shares = np.diff(cuts)
    keep = shares >= MIN_PIECE_LENGTH_M
    if not keep.any():
        keep[np.argmax(shares)] = True
    starts = cuts[:-1][keep]
    starts[0] = 0.0
    stops = np.concatenate([starts[1:], [length]])
    return [
        LinePiece(cell=int(cell), length=float(stop - start), middle=float(0.5 * (start + stop)))
        for cell, start, stop in zip(cells[keep], starts, stops, strict=True)
    ]


def crossing_pieces(cell_mesh: PlanarCellMesh, line: LineString) -> list[LinePiece]:
    """Cut the line at the cell boundaries and give each cell the length inside it.

    The cells are ordered by the point halfway along their share; a cell whose
    share is shorter than ``MIN_PIECE_LENGTH_M`` is left out, and so is the
    length of the line outside the mesh.
    """
    polygons = cell_polygons(cell_mesh.mesh.vertices, cell_mesh.geometry.padded_connectivity)
    candidates = np.sort(STRtree(polygons).query(line, predicate="intersects"))
    if candidates.size == 0:
        return []
    length = float(line.length)
    crossings = shapely.get_coordinates(
        shapely.intersection(line, shapely.boundary(polygons[candidates]))
    )
    cuts = np.unique(
        np.concatenate([[0.0, length], shapely.line_locate_point(line, shapely.points(crossings))])
    )
    middles = 0.5 * (cuts[1:] + cuts[:-1])
    pieces = np.diff(cuts)
    points = shapely.line_interpolate_point(line, middles)
    point_index, candidate_index = STRtree(polygons[candidates]).query(
        points, predicate="covered_by"
    )
    holder = np.full(middles.size, np.iinfo(np.int64).max, dtype=np.int64)
    np.minimum.at(holder, point_index, candidates[candidate_index])
    inside = holder != np.iinfo(np.int64).max
    holder, starts, pieces = holder[inside], cuts[:-1][inside], pieces[inside]
    out: list[LinePiece] = []
    for cell in np.unique(holder):
        mine = holder == cell
        total = float(pieces[mine].sum())
        if total < MIN_PIECE_LENGTH_M:
            continue
        walked = np.cumsum(pieces[mine])
        half = int(np.searchsorted(walked, 0.5 * total))
        middle = starts[mine][half] + 0.5 * total - (walked[half] - pieces[mine][half])
        out.append(LinePiece(cell=int(cell), length=total, middle=float(middle)))
    out.sort(key=lambda piece: (piece.middle, piece.cell))
    return out
