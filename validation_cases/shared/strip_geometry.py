"""Model positions of a 1D strip profile and of its boundary conditions.

A cell-centred model holds a side Dirichlet head at the centroid of each cell
that owns a boundary edge, not on the domain face. On a structured MODFLOW grid
that is the centre of the boundary column, half a cell inside the face. A
no-flow side stays on the face itself. An analytical reference compared with
such a model must pose its heads where the model holds them, and must be read
where the model reports its profile. Posing them on the faces instead stretches
a domain of ``L - dx`` onto ``L``, a first-order error in ``dx``.

The validation loaders report a strip profile on ``ncol`` equal bins of the
cell centroids (``validation_cases.shared.loaders``). On a structured grid one
bin is one column. On an irregular triangle mesh one bin averages the triangles
whose centroid falls in it, so the reference is averaged the same way: it is
evaluated at each centroid, then binned.

A synthetic ``linear`` topography is defined on the raster columns: it takes
its west value at the centre of the first column and its east value at the
centre of the last one. A launcher run samples its cell tops from that raster.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np

# Relative tolerance that decides whether a mesh node lies on a strip face.
_FACE_RTOL = 1.0e-9


@dataclass(frozen=True, slots=True)
class StripGeometry:
    """Where a strip model reports its profile and holds its side heads.

    ``x`` is the abscissa of each profile column. ``west_x`` and ``east_x`` are
    where a west or east Dirichlet head sits in the model. ``xmin`` and
    ``xmax`` are the domain faces, where a no-flow side sits.
    ``surface_west_x`` and ``surface_east_x`` are where a linear surface law
    (topography, substratum) takes its west and east values.
    ``mean_cell_area`` is the mean plan area of the model cells, which turns a
    per-cell conductance into a rate per unit area; it is None when the run
    stores no mesh. On an irregular mesh, ``cell_x``, ``cell_column`` and
    ``cell_weight`` describe the binning the loader applied to the cell values.
    """

    xmin: float
    xmax: float
    x: np.ndarray
    west_x: float
    east_x: float
    surface_west_x: float
    surface_east_x: float
    mean_cell_area: float | None = None
    cell_x: np.ndarray | None = None
    cell_column: np.ndarray | None = None
    cell_weight: np.ndarray | None = None

    def profile(
        self,
        values_at: Callable[[np.ndarray], np.ndarray],
        *,
        within: tuple[float, float] | None = None,
    ) -> np.ndarray:
        """Return ``values_at(x)`` on the profile columns, averaged like the model.

        ``values_at`` returns one value per point, or one row per output time
        with one column per point. ``within`` clips the evaluation points to the
        span where the reference is defined. A cell beyond a Dirichlet position
        holds the boundary head, which the reference gives at that position.
        """
        points = self.x if self.cell_x is None else self.cell_x
        if within is not None:
            points = np.clip(points, float(within[0]), float(within[1]))
        values = np.asarray(values_at(points), dtype=float)
        if self.cell_x is None:
            return values
        assert self.cell_column is not None and self.cell_weight is not None
        return bin_cell_values(
            values,
            cell_column=self.cell_column,
            cell_weight=self.cell_weight,
            ncol=int(self.x.size),
        )


def column_centres(*, xmin: float, xmax: float, ncol: int) -> np.ndarray:
    """Return the centres of ``ncol`` equal columns between ``xmin`` and ``xmax``."""
    dx = (float(xmax) - float(xmin)) / int(ncol)
    return float(xmin) + (np.arange(int(ncol), dtype=float) + 0.5) * dx


def bin_cell_values(
    values: np.ndarray,
    *,
    cell_column: np.ndarray,
    cell_weight: np.ndarray,
    ncol: int,
) -> np.ndarray:
    """Average cell values per column, then fill empty columns by index.

    This is the binning of ``validation_cases.shared.loaders``: a weighted mean
    per column and a linear fill over the column index where no cell falls.
    ``values`` holds one value per cell, or one row of them per output time.
    """
    values = np.asarray(values, dtype=float)
    weight = np.asarray(cell_weight, dtype=float).reshape(-1)
    column = np.asarray(cell_column, dtype=int).reshape(-1)
    rows = np.atleast_2d(values)
    norm = np.bincount(column, weights=weight, minlength=int(ncol))
    filled = norm > 0.0
    index = np.flatnonzero(filled).astype(float)
    profiles = np.empty((rows.shape[0], int(ncol)), dtype=float)
    for row_index, row in enumerate(rows):
        total = np.bincount(column, weights=row * weight, minlength=int(ncol))
        profiles[row_index] = np.interp(
            np.arange(int(ncol), dtype=float), index, total[filled] / norm[filled]
        )
    return profiles[0] if values.ndim == 1 else profiles


def _read_store_layout(
    store: Any, sim_id: str | None
) -> tuple[np.ndarray, np.ndarray, int | None] | None:
    """Return the mesh vertices, the cell connectivity and the raster width of a run."""
    if store is None or sim_id is None:
        return None
    sz = store.open_zarr(sim_id)
    try:
        root = sz.root
        # A store written from column fields has an empty mesh group.
        if "mesh" not in root or "vertices" not in root["mesh"]:
            return None
        vertices = np.asarray(root["mesh"]["vertices"][:], dtype=float)
        connectivity = np.asarray(root["mesh"]["face_node_connectivity"][:], dtype=int)
        raster_ncol = None
        if "geographic" in root and "watershed_dem" in root["geographic"]:
            raster_ncol = int(root["geographic"]["watershed_dem"].shape[-1])
    finally:
        sz.close()
    return vertices, connectivity, raster_ncol


def _cell_centroid_x_and_area(
    vertices: np.ndarray, connectivity: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return the vertex-mean x, the area and the valid-node mask of each cell."""
    valid = connectivity >= 0
    safe = np.where(valid, connectivity, 0)
    px = np.where(valid, vertices[safe, 0], 0.0)
    py = np.where(valid, vertices[safe, 1], 0.0)
    centroid_x = px.sum(axis=1) / valid.sum(axis=1)
    area = np.zeros(connectivity.shape[0], dtype=float)
    for row in range(connectivity.shape[0]):
        ring_x = px[row, valid[row]]
        ring_y = py[row, valid[row]]
        area[row] = 0.5 * abs(
            float(np.dot(ring_x, np.roll(ring_y, -1)) - np.dot(ring_y, np.roll(ring_x, -1)))
        )
    return centroid_x, area, valid


def _face_owner_mean_x(
    vertices: np.ndarray,
    connectivity: np.ndarray,
    valid: np.ndarray,
    centroid_x: np.ndarray,
    *,
    face_x: float,
    atol: float,
) -> float:
    """Return the mean centroid x of the cells that own an edge on one face."""
    safe = np.where(valid, connectivity, 0)
    on_face = valid & np.isclose(vertices[safe, 0], float(face_x), rtol=0.0, atol=atol)
    owners = on_face.sum(axis=1) >= 2
    if not np.any(owners):
        raise ValueError(f"No cell owns an edge on the strip face x = {face_x}.")
    return float(np.mean(centroid_x[owners]))


def strip_geometry_from_mesh(
    *,
    vertices: np.ndarray,
    connectivity: np.ndarray,
    ncol: int,
    raster_ncol: int | None = None,
    xmin: float | None = None,
    xmax: float | None = None,
    area_weighted: bool = False,
) -> StripGeometry:
    """Build the strip geometry of one cell mesh.

    ``xmin`` and ``xmax`` default to the mesh extent, like the loader that
    bins an irregular mesh. ``area_weighted`` matches the loader that collapses
    an irregular mesh to an area-weighted x-profile. ``raster_ncol`` is the
    column count of the topography raster the cell tops were sampled from.
    """
    vertices = np.asarray(vertices, dtype=float)
    connectivity = np.asarray(connectivity, dtype=int)
    node_x = vertices[:, 0]
    x_lo = float(node_x.min()) if xmin is None else float(xmin)
    x_hi = float(node_x.max()) if xmax is None else float(xmax)
    atol = _FACE_RTOL * max(abs(x_hi - x_lo), 1.0)
    centroid_x, area, valid = _cell_centroid_x_and_area(vertices, connectivity)
    west_x = _face_owner_mean_x(vertices, connectivity, valid, centroid_x, face_x=x_lo, atol=atol)
    east_x = _face_owner_mean_x(vertices, connectivity, valid, centroid_x, face_x=x_hi, atol=atol)

    if raster_ncol is None:
        surface_west_x, surface_east_x = x_lo, x_hi
    else:
        raster_centres = column_centres(xmin=x_lo, xmax=x_hi, ncol=int(raster_ncol))
        surface_west_x, surface_east_x = float(raster_centres[0]), float(raster_centres[-1])

    dx = (x_hi - x_lo) / int(ncol)
    column = np.clip(((centroid_x - x_lo) / dx).astype(int), 0, int(ncol) - 1)
    centres = column_centres(xmin=x_lo, xmax=x_hi, ncol=int(ncol))
    common = {
        "xmin": x_lo,
        "xmax": x_hi,
        "x": centres,
        "west_x": west_x,
        "east_x": east_x,
        "surface_west_x": surface_west_x,
        "surface_east_x": surface_east_x,
        "mean_cell_area": float(np.mean(area)),
    }
    # On a column grid every centroid sits on its column centre, so the
    # reference is read on the centres directly.
    if np.allclose(centroid_x, centres[column], rtol=0.0, atol=atol):
        return StripGeometry(**common)
    return StripGeometry(
        **common,
        cell_x=centroid_x,
        cell_column=column,
        cell_weight=area if area_weighted else np.ones_like(centroid_x),
    )


def split_triangle_strip_geometry(*, xmin: float, xmax: float, ncol: int) -> StripGeometry:
    """Build the geometry of the structured triangle strip of the Boussinesq runtime.

    That runtime splits each rectangle of an ``ncol``-column strip into two
    triangles and prescribes a side head on the triangle that owns the side
    edge, whose centroid lies one third of a column inside the face. It samples
    its surfaces on the faces and writes column means, so the profile sits on
    the column centres.
    """
    dx = (float(xmax) - float(xmin)) / int(ncol)
    return StripGeometry(
        xmin=float(xmin),
        xmax=float(xmax),
        x=column_centres(xmin=xmin, xmax=xmax, ncol=int(ncol)),
        west_x=float(xmin) + dx / 3.0,
        east_x=float(xmax) - dx / 3.0,
        surface_west_x=float(xmin),
        surface_east_x=float(xmax),
    )


def strip_geometry_for_run(
    result: Any,
    *,
    ncol: int,
    xmin: float,
    xmax: float,
    area_weighted: bool = False,
) -> StripGeometry:
    """Return the strip geometry of one validation run.

    A launcher run stores its mesh and its topography raster, which give the
    true positions. A run of the Boussinesq validation runtime stores column
    fields only, and gets the geometry of its structured triangle strip.
    """
    layout = _read_store_layout(getattr(result, "store", None), getattr(result, "sim_id", None))
    if layout is None:
        return split_triangle_strip_geometry(xmin=xmin, xmax=xmax, ncol=int(ncol))
    vertices, connectivity, raster_ncol = layout
    return strip_geometry_from_mesh(
        vertices=vertices,
        connectivity=connectivity,
        ncol=int(ncol),
        raster_ncol=raster_ncol,
        xmin=float(xmin) if area_weighted else None,
        xmax=float(xmax) if area_weighted else None,
        area_weighted=area_weighted,
    )


__all__ = [
    "StripGeometry",
    "bin_cell_values",
    "column_centres",
    "split_triangle_strip_geometry",
    "strip_geometry_for_run",
    "strip_geometry_from_mesh",
]
