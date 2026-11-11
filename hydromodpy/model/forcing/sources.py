"""Readers of a gridded or located source, shared by the forcing discretizers.

A nodata pixel under a cell is refused with the cell and the period
(``refuse_nodata_under_cells``). The values are multiplied by the unit factor of the record, so
they come out in m/s, and several records of one period are averaged with equal weights.

The source is whatever the data managers return: an xarray dataset, a NetCDF or
GeoTIFF file, station series. The target is always a flat list of cell centers,
whatever the mesh engine. The ``"area"`` method also reads the cell polygons of
the planar mesh, so each pixel weighs by the area it shares with a cell.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
from scipy import sparse

from hydromodpy.core.config_kit.types import InterpolationMethod
from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.core.logging import get_logger
from hydromodpy.core.units.quantities import factor_to_m_per_s
from hydromodpy.model.forcing.area_weights import area_mean, area_weights
from hydromodpy.model.forcing.interpolation import (
    interpolate_points_to_grid,
    interpolate_stack_to_grid,
    interpolate_to_grid,
)

if TYPE_CHECKING:
    from hydromodpy.mesh.planar.hydro_mesh import HydroMesh

logger = get_logger(__name__)


class ForcingGridError(DataContractViolation, ValueError):
    """A gridded forcing with no pixel, or with no X and Y axis to read it by.

    It is a ``ValueError`` too, so a caller that catches the ``ValueError``
    these checks raised before still catches it.
    """


def unit_to_m_per_s_factor(unit: str) -> float:
    """Return multiplication factor to convert from *unit* to m/s."""
    token = "".join(str(unit).strip().lower().split())
    french_aliases = {
        "mm/jour": "mm/day",
        "cm/jour": "cm/day",
        "m/jour": "m/day",
    }
    resolved_unit = french_aliases.get(token, unit)
    return factor_to_m_per_s(resolved_unit)


def pick_field_variable(ds: object) -> str | None:
    """Return the data variable of a gridded dataset that carries the field.

    A CF dataset stores its coordinate reference as a scalar data variable
    sitting next to the field, and a land-surface export carries several
    fields at once. Taking the first variable blindly picks the grid mapping,
    which has no dimension at all: skip anything a field points at as its
    ``grid_mapping``, skip anything with fewer than two dimensions, and keep
    the first of what is left.
    """
    data_vars = list(getattr(ds, "data_vars", ()) or ())
    if not data_vars:
        return None
    grid_mappings = {
        str(ds[name].attrs.get("grid_mapping"))
        for name in data_vars
        if ds[name].attrs.get("grid_mapping")
    }
    for name in data_vars:
        if str(name) in grid_mappings:
            continue
        if len(ds[name].dims) < 2:
            continue
        return str(name)
    return str(data_vars[0])


def _earth_crs(crs: object) -> Any:
    """Return *crs* as a pyproj CRS when it places the data on the Earth, else None.

    A CRS is absent, unreadable or a local frame (``LOCAL_CS``, an engineering
    CRS) when it is neither projected nor geographic. Such a CRS declares no
    place, so nothing can be compared with it.
    """
    text = str(crs or "").strip()
    if not text:
        return None
    from pyproj import CRS
    from pyproj.exceptions import CRSError

    try:
        parsed = CRS.from_user_input(text)
    except CRSError:
        return None
    return parsed if parsed.is_projected or parsed.is_geographic else None


def crs_mismatch(source_crs: object, mesh_crs: str | None) -> tuple[str, str] | None:
    """Return the names of the source CRS and the mesh CRS when they differ, else None.

    A forcing is never reprojected, so a source in another CRS than the mesh
    puts each value in another place. When the source or the mesh declares no
    CRS that places it on the Earth, see :func:`_earth_crs`, the two cannot be
    compared and None is returned. Two CRS compare through
    :func:`~hydromodpy.core.io.crs.same_crs`.
    """
    source, mesh = _earth_crs(source_crs), _earth_crs(mesh_crs)
    if source is None or mesh is None:
        return None
    from hydromodpy.core.io.crs import same_crs

    if same_crs(str(source_crs), str(mesh_crs)):
        return None
    return source.to_string(), mesh.to_string()


def find_xy_dims(da: object, *, source: str = "dataset") -> tuple[str, str]:
    """Identify X and Y dimension names in a DataArray, or refuse it naming *source*."""
    dims = [str(d) for d in da.dims]
    x_candidates = ("x", "lon", "longitude", "easting", "X")
    y_candidates = ("y", "lat", "latitude", "northing", "Y")
    x_dim = next((d for d in dims if d in x_candidates), None)
    y_dim = next((d for d in dims if d in y_candidates), None)
    # Fallback: use last two spatial dims.
    spatial_dims = [d for d in dims if d != "time"]
    if x_dim is None and len(spatial_dims) >= 1:
        x_dim = spatial_dims[-1]
    if y_dim is None and len(spatial_dims) >= 2:
        y_dim = spatial_dims[-2]
    if x_dim is None or y_dim is None:
        raise ForcingGridError(
            f"The gridded forcing {source} has the variable {getattr(da, 'name', None)!r} on "
            f"the dimensions {tuple(dims)}, among which no X and Y axis. Name them x and y "
            "(or lon and lat, easting and northing), or give two dimensions besides time."
        )
    return x_dim, y_dim


# The interpolation module takes a 2-D target. A column of cells is one: it has
# as many rows as cells and one column, whatever the mesh topology.


def _as_column(centers: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return the x and y of ``(n, 2)`` centers as two ``(n, 1)`` columns."""
    xy = np.asarray(centers, dtype=float)
    return xy[:, 0].reshape(-1, 1), xy[:, 1].reshape(-1, 1)


def interpolate_on_cells(
    source_values: np.ndarray,
    source_x: np.ndarray,
    source_y: np.ndarray,
    centers: np.ndarray,
    method: InterpolationMethod,
    *,
    mesh: HydroMesh | None = None,
) -> np.ndarray:
    """Interpolate one source slice onto the cells, one value per cell.

    ``mesh`` is the planar mesh of the cells, read by ``"area"`` only. Without
    it the interpolators refuse ``"area"``.
    """
    if method == "area" and mesh is not None:
        stack = np.asarray(source_values, dtype=float)[None, ...]
        return _area_on_cells(stack, source_x, source_y, centers, mesh)[0]
    target_x, target_y = _as_column(centers)
    values = interpolate_to_grid(
        np.asarray(source_values, dtype=float),
        source_x,
        source_y,
        target_x,
        target_y,
        target_x.shape[0],
        1,
        method,
    )
    return values.reshape(-1)


def interpolate_stack_on_cells(
    source_stack: np.ndarray,
    source_x: np.ndarray,
    source_y: np.ndarray,
    centers: np.ndarray,
    method: InterpolationMethod,
    *,
    mesh: HydroMesh | None = None,
) -> np.ndarray:
    """Interpolate a stack of source slices onto the cells, ``(n_slices, n_cells)``.

    ``mesh`` is the planar mesh of the cells, read by ``"area"`` only. Without
    it the interpolators refuse ``"area"``.
    """
    if method == "area" and mesh is not None:
        return _area_on_cells(
            np.asarray(source_stack, dtype=float), source_x, source_y, centers, mesh
        )
    target_x, target_y = _as_column(centers)
    values = interpolate_stack_to_grid(
        source_stack,
        source_x,
        source_y,
        target_x,
        target_y,
        target_x.shape[0],
        1,
        method,
    )
    return values.reshape(values.shape[0], -1)


def interpolate_points_on_cells(
    point_x: np.ndarray,
    point_y: np.ndarray,
    point_values: np.ndarray,
    centers: np.ndarray,
    method: InterpolationMethod,
    *,
    idw_power: float = 2.0,
) -> np.ndarray:
    """Interpolate scattered station values onto the cell centers, one value per cell.

    ``idw_power`` is the exponent of the IDW weights, read by ``"idw"`` only.
    """
    target_x, target_y = _as_column(centers)
    values = interpolate_points_to_grid(
        point_x=point_x,
        point_y=point_y,
        point_values=point_values,
        target_x=target_x,
        target_y=target_y,
        nrow=target_x.shape[0],
        ncol=1,
        method=method,
        idw_power=idw_power,
    )
    return values.reshape(-1)


_IDW_NEIGHBOURS = 16
"""Pixels an IDW cell reads, as in :mod:`hydromodpy.model.forcing.interpolation`."""


def refuse_nodata_under_cells(
    source_stack: np.ndarray,
    source_x: np.ndarray,
    source_y: np.ndarray,
    centers: np.ndarray,
    method: InterpolationMethod,
    *,
    source: str,
    slice_labels: list[str],
    mesh: HydroMesh | None = None,
) -> None:
    """Refuse a grid the cells cannot read, a slice with no valid pixel, and a cell on nodata.

    ``"linear"`` triangulates the pixel centers, so it refuses a grid of one
    row or one column, where every center sits on one line. A nodata pixel is a non-finite value. The interpolators drop such pixels,
    so a cell that sits on one would silently take a neighbor, and a slice
    with no valid pixel would give zero. A cell reads the nearest pixel
    (``"nearest"``), the vertices of the pixel triangle around its center
    (``"linear"``), its nearest pixels (``"idw"``) or the pixels it overlaps
    (``"area"``). A cell outside the reach of these rules reads its nearest
    pixel, as the interpolators do.
    """
    if method == "linear":
        n_rows, n_columns = np.asarray(source_y).size, np.asarray(source_x).size
        if min(n_rows, n_columns) < 2:
            raise DataContractViolation(
                f"The gridded forcing {source} is a grid of {n_rows} row(s) and {n_columns} "
                "column(s). interpolation_method 'linear' triangulates the pixel centres, "
                "which needs at least two rows and two columns. Use 'nearest', 'idw' or 'area'."
            )
    flat = np.asarray(source_stack, dtype=float).reshape(len(slice_labels), -1)
    nodata = ~np.isfinite(flat)
    if not nodata.any():
        return
    empty = np.flatnonzero(nodata.all(axis=1))
    if empty.size:
        raise DataContractViolation(
            f"The gridded forcing {source} holds no valid pixel in {slice_labels[empty[0]]}."
        )
    read = _pixels_read(source_x, source_y, centers, method, mesh)
    # Only the pixels nodata in some slice can hit a cell: keep the product small.
    columns = np.flatnonzero(nodata.any(axis=0))
    hit = (read[:, columns] @ nodata[:, columns].T.astype(float)) > 0.0
    touched = np.flatnonzero(hit.any(axis=0))
    if touched.size:
        k = touched[0]
        cells = np.flatnonzero(hit[:, k])
        raise DataContractViolation(
            f"The gridded forcing {source} has a nodata pixel under {cells.size} cell(s) in "
            f"{slice_labels[k]}, first cell {int(cells[0])}. Every cell must read valid "
            "pixels only: cover the model domain with valid pixels."
        )


def _pixels_read(
    source_x: np.ndarray,
    source_y: np.ndarray,
    centers: np.ndarray,
    method: InterpolationMethod,
    mesh: HydroMesh | None,
) -> sparse.csr_array:
    """Pixels each cell reads, ``(n_cells, n_pixels)``, pixels laid out ``(y, x)``.

    ``source_x`` and ``source_y`` are the 1-D pixel centers of the grid, as a
    GeoTIFF or the dimension coordinates of a dataset give them.
    """
    from scipy.spatial import cKDTree

    x, y = np.meshgrid(
        np.asarray(source_x, dtype=float), np.asarray(source_y, dtype=float), indexing="xy"
    )
    pixels = np.column_stack([x.ravel(), y.ravel()])
    xy = np.asarray(centers, dtype=float)
    n_cells, n_pixels = xy.shape[0], pixels.shape[0]
    tree = cKDTree(pixels)
    distance, nearest = tree.query(xy)
    rows = [np.arange(n_cells)]
    columns = [nearest]
    if method == "area" and mesh is not None:
        overlap = area_weights(mesh, source_x, source_y).tocoo()
        rows.append(overlap.row)
        columns.append(overlap.col)
    elif method == "idw":
        k = min(n_pixels, _IDW_NEIGHBOURS)
        _, neighbours = tree.query(xy, k=k)
        neighbours = neighbours.reshape(n_cells, k)
        apart = np.flatnonzero(distance > 0.0)
        rows.append(np.repeat(apart, k))
        columns.append(neighbours[apart].ravel())
    elif method == "linear" and n_pixels >= 3:
        from scipy.spatial import Delaunay

        triangles = Delaunay(pixels)
        simplex = triangles.find_simplex(xy)
        inside = np.flatnonzero((simplex >= 0) & (distance > 0.0))
        corners = triangles.simplices[simplex[inside]]
        rows.append(np.repeat(inside, corners.shape[1]))
        columns.append(corners.ravel())
    row = np.concatenate(rows)
    column = np.concatenate(columns)
    return sparse.csr_array((np.ones(row.size), (row, column)), shape=(n_cells, n_pixels))


def refuse_area_for_stations(method: InterpolationMethod) -> None:
    """Refuse ``"area"`` for station values, which have no pixel to weigh."""
    if method == "area":
        raise ValueError(
            "interpolation_method 'area' weighs the pixels of a gridded source by their area "
            "in each cell; a station source has no pixel. Use 'nearest', 'linear' or 'idw'."
        )


def _area_on_cells(
    stack: np.ndarray,
    source_x: np.ndarray,
    source_y: np.ndarray,
    centers: np.ndarray,
    mesh: HydroMesh,
) -> np.ndarray:
    """Area-weighted mean of each slice over each cell, ``(n_slices, n_cells)``.

    A cell that shares no area with a finite pixel takes the nearest pixel, as
    ``"linear"`` does outside the hull of its source.
    """
    if mesh.n_cells != centers.shape[0]:
        raise ValueError(
            f"the planar mesh holds {mesh.n_cells} cells for {centers.shape[0]} centres."
        )
    values = area_mean(area_weights(mesh, source_x, source_y), stack)
    missing = ~np.isfinite(values)
    if missing.any():
        cells = np.flatnonzero(missing.any(axis=0))
        logger.info(
            "%d cell(s) share no area with a finite pixel of the source; "
            "they take the nearest pixel.",
            cells.size,
        )
        nearest = interpolate_stack_on_cells(stack, source_x, source_y, centers[cells], "nearest")
        values[:, cells] = np.where(missing[:, cells], nearest, values[:, cells])
    return values
