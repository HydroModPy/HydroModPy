"""The cells of a mesh read on a property map, one value per cell from the pixels it covers.

Any mesh reads a map, regular or not. A cell takes the mean of the map at points spread
evenly over its area (``cell_sampling``), whether it is a quadrilateral, a triangle or a
Voronoi polygon. The points are read in the CRS of the map, so a map in another CRS than
the mesh is read where it lies and its pixels are never resampled. They are about two per
pixel along a side of the cell, so each pixel weighs by the share of the cell it covers,
within a few percent of the size of the cell: the lattice of a triangle leans a little
towards its first corner, as it does for the zone fractions of a support. A
point outside the map or on a nodata pixel holds no value, and a cell with no point left
holds none either.

The mean of a cell is one of three: ``arithmetic`` adds the values, ``geometric`` their
logarithms and ``harmonic`` their inverses, which a conductivity in series follows. The two
last take positive values only.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np
from pyproj import Transformer
from pyproj.exceptions import CRSError

from hydromodpy.catchment.surface import Surface
from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.io.crs import same_crs
from hydromodpy.core.logging import get_logger
from hydromodpy.mesh.planar.planar_cell_mesh import PlanarCellMesh
from hydromodpy.model.properties.cell_sampling import (
    quadrilateral_points_in_cells,
    sample_points_in_cell,
)
from hydromodpy.model.properties.mesh_cells import MeshCell, mesh_cells

__all__ = [
    "MEANS",
    "POINTS_PER_SIDE",
    "RasterCells",
    "points_per_side",
    "raster_cells",
    "read_property_maps",
]

logger = get_logger(__name__)

POINTS_PER_SIDE = (4, 16)
"""Fewest and most sample points along a side of a cell, so 16 to 256 points per cell."""

CELLS_PER_BATCH = 4096
"""Cells sampled at once: a batch holds at most a million points."""

MEANS: dict[str, tuple[Callable[[np.ndarray], np.ndarray], Callable[[np.ndarray], np.ndarray]]] = {
    "arithmetic": (np.asarray, np.asarray),
    "geometric": (np.log, np.exp),
    "harmonic": (np.reciprocal, np.reciprocal),
}
"""Each mean as the transform its values are averaged under, then the inverse of it."""


@dataclass(frozen=True)
class RasterCells:
    """The values of one property map on the cells of a mesh, in the unit of the map.

    ``values`` holds one value per cell, NaN on a cell the map gives no value.
    """

    mesh: PlanarCellMesh
    values: np.ndarray
    map_name: str

    @property
    def covered(self) -> np.ndarray:
        """True on each cell the map gives a value."""
        return np.isfinite(self.values)


def read_property_maps(profiles: Mapping[str, object], data: object | None) -> dict[str, Surface]:
    """Read, by name, the maps of ``[data.property_map]`` the raster profiles read.

    *profiles* are the ``FieldParam`` of the flow and *data* the ``[data]`` section.
    Each map is read on its own grid, once, however many profiles read it.

    Raises
    ------
    ConfigError
        When a profile reads a map ``[data.property_map]`` does not declare.
    """
    wanted = {
        str(profile.raster_map): name
        for name, profile in profiles.items()
        if getattr(profile, "is_raster", False)
    }
    if not wanted:
        return {}
    section = getattr(data, "property_map", None)
    declared = {} if section is None else {source.name: source for source in section.sources}
    missing = sorted(set(wanted) - set(declared))
    if missing:
        readers = ", ".join(f"flow.param.{wanted[map_name]}" for map_name in missing)
        raise ConfigError(
            f"{readers} reads the map(s) {missing}, and [data.property_map] declares "
            f"{sorted(declared) or 'none'}. Add one [[data.property_map.sources]] entry per "
            "name, with its raster."
        )
    return {
        name: Surface.from_raster(
            declared[name].path, name=f"{name}_map", default_crs=declared[name].default_crs
        )
        for name in sorted(wanted)
    }


def points_per_side(cell_mesh: PlanarCellMesh, pixel_size: float) -> int:
    """Sample points along a side of a cell: about two per pixel the median cell spans."""
    side = float(np.sqrt(np.median(np.asarray(cell_mesh.cell_areas(), dtype=float))))
    if not np.isfinite(pixel_size) or pixel_size <= 0.0 or not np.isfinite(side):
        return POINTS_PER_SIDE[0]
    return int(np.clip(np.ceil(2.0 * side / pixel_size), *POINTS_PER_SIDE))


def raster_cells(
    cell_mesh: PlanarCellMesh, surface: Surface, *, mean: str, map_name: str
) -> RasterCells:
    """Read ``surface`` on each cell of ``cell_mesh``, as the ``mean`` of the pixels it covers.

    Raises
    ------
    ValueError
        When the map has no complete georeferencing, or when a geometric or a harmonic
        mean meets a value at or below zero.
    """
    support = surface.support
    if support is None:
        raise ValueError(f"The map {map_name!r} has no georeferencing to place it on the mesh.")
    support.assert_complete_domain()
    grid = surface.as_array().copy()
    if support.nodata is not None:
        grid[grid == float(support.nodata)] = np.nan
    to_map = _transformer(cell_mesh.crs_wkt, support.crs)
    n = points_per_side(cell_mesh, _pixel_size_on_the_mesh(support, to_map))
    forward, inverse = MEANS[mean]
    sums = np.zeros(cell_mesh.n_cells, dtype=float)
    counts = np.zeros(cell_mesh.n_cells, dtype=float)
    cells = mesh_cells(cell_mesh)
    for start in range(0, len(cells), CELLS_PER_BATCH):
        index, x, y = _points(cells[start : start + CELLS_PER_BATCH], n)
        if to_map is not None:
            x, y = to_map.transform(x, y)
        sampled = _pixel_values(grid, support, np.asarray(x), np.asarray(y))
        read = np.isfinite(sampled)
        if mean != "arithmetic" and np.any(sampled[read] <= 0.0):
            below = np.unique(index[read][sampled[read] <= 0.0]).size
            raise ValueError(
                f"The map {map_name!r} holds a value at or below zero under {below} cell(s), "
                f"and a {mean} mean takes positive values only. Write mean = 'arithmetic', "
                "or set those pixels to nodata."
            )
        sums += np.bincount(index[read], weights=forward(sampled[read]), minlength=sums.size)
        counts += np.bincount(index[read], minlength=counts.size)
    values = np.full(cell_mesh.n_cells, np.nan, dtype=float)
    held = counts > 0
    values[held] = inverse(sums[held] / counts[held])
    return RasterCells(mesh=cell_mesh, values=values, map_name=map_name)


def _transformer(mesh_crs: str, map_crs: str | None) -> Transformer | None:
    """The transform from the mesh to the map, None when both share one CRS or one is unknown.

    A CRS pyproj cannot read leaves the map read in the coordinates of the mesh, and
    says so: a project CRS always reads, so this is a mesh built by hand.
    """
    if not mesh_crs or not map_crs or same_crs(mesh_crs, map_crs):
        return None
    try:
        return Transformer.from_crs(mesh_crs, map_crs, always_xy=True)
    except CRSError:
        logger.warning(
            "The CRS of the mesh or of a property map cannot be read; the map is read in "
            "the coordinates of the mesh."
        )
        return None


def _pixel_size_on_the_mesh(support: object, to_map: Transformer | None) -> float:
    """The side of a pixel in the units of the mesh."""
    if to_map is None:
        return float(min(abs(support.dx), abs(support.dy)))
    corners = (
        (support.xmin, support.xmin, support.xmax, support.xmax),
        (support.ymin, support.ymax, support.ymin, support.ymax),
    )
    x, y = to_map.transform(*corners, direction="INVERSE")
    area = (max(x) - min(x)) * (max(y) - min(y))
    return float(np.sqrt(area / (int(support.nrows) * int(support.ncols))))


def _points(cells: Sequence[MeshCell], n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The sample points of *cells*: the index of the cell of each point, then x and y.

    The quadrilaterals of a regular grid take the batch path of ``cell_sampling``, the
    other cells one at a time.
    """
    quads = [cell for cell in cells if cell.kind == "quadrilateral"]
    others = [cell for cell in cells if cell.kind != "quadrilateral"]
    index: list[np.ndarray] = []
    xs: list[np.ndarray] = []
    ys: list[np.ndarray] = []
    if quads:
        x, y = quadrilateral_points_in_cells(np.stack([cell.vertices for cell in quads]), n)
        index.append(np.repeat([cell.index for cell in quads], x.shape[1]))
        xs.append(x.reshape(-1))
        ys.append(y.reshape(-1))
    for cell in others:
        x, y = sample_points_in_cell(cell, n_sub_per_axis=n)
        index.append(np.full(x.size, cell.index))
        xs.append(np.asarray(x).reshape(-1))
        ys.append(np.asarray(y).reshape(-1))
    if not index:
        empty = np.empty(0)
        return empty.astype(np.int64), empty, empty
    return np.concatenate(index).astype(np.int64), np.concatenate(xs), np.concatenate(ys)


def _pixel_values(grid: np.ndarray, support: object, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """The value of the pixel under each point, NaN outside the map."""
    col = np.floor((x - float(support.xmin)) / abs(float(support.dx))).astype(np.int64)
    row = np.floor((float(support.ymax) - y) / abs(float(support.dy))).astype(np.int64)
    inside = (col >= 0) & (col < grid.shape[1]) & (row >= 0) & (row < grid.shape[0])
    values = np.full(x.shape, np.nan, dtype=float)
    values[inside] = grid[row[inside], col[inside]]
    return values
