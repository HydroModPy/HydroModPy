"""Geographic and mesh accessors for :class:`hydromodpy.results.run.Run`.

Mixin that bundles persisted geographic features, raster reads, the scalar
grid metadata, the catchment mask, DEM, outlet, unstructured mesh and the
Zarr-backed field readers (``field``, ``has_field``, ``fields``). Mixed
into :class:`Run`; ``self`` is the :class:`Run` instance whose ``_sim_id``,
``_catalog`` and ``_load_row`` are consumed.
"""

from __future__ import annotations

from functools import cached_property
from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.results import field_registry
from hydromodpy.results.errors import FieldNotFoundError
from hydromodpy.results.run.array import lookup_zarr_path
from hydromodpy.results.run.contracts import Mesh, RasterField

if TYPE_CHECKING:
    import geopandas as gpd

    from hydromodpy.results.grid import Grid


class RunGeographicMixin:
    """Geographic, raster, mesh and field accessors mixed into :class:`Run`."""

    def geographic(self, feature_name: str) -> gpd.GeoDataFrame:
        """Return a persisted geographic feature for this run.

        Parameters
        ----------
        feature_name
            Feature table name stored in the catalog.

        Returns
        -------
        geopandas.GeoDataFrame
            Geographic feature rows for this simulation.
        """
        return self._catalog.read_geographic_feature(self._sim_id, feature_name)

    def geographic_raster(self, name: str) -> RasterField:
        """Return one geographic raster persisted for this run.

        Parameters
        ----------
        name
            Raster name stored in the simulation Zarr store.

        Returns
        -------
        RasterField
            Array data and raster metadata.
        """
        sz = self._catalog.open_zarr(self._sim_id)
        try:
            data, meta = sz.read_geographic_raster(name)
            return RasterField(
                data=data,
                transform=tuple(meta["transform"]),
                crs=str(meta["crs"]),
                nodata=float(meta["nodata"]),
                shape=tuple(meta["shape"]),
            )
        finally:
            sz.close()

    @cached_property
    def grid(self) -> Grid:
        """Scalar grid metadata: cell_size, shape, extent, CRS, area.

        Raises ``RuntimeError`` for lumped simulations (``solver_category``
        ``"lumped"``) which have no spatial discretisation, or when
        geographic metadata has not been ingested.
        """
        from hydromodpy.results.grid import build_grid

        return build_grid(self)

    @cached_property
    def catchment_mask(self) -> np.ndarray:
        """2D boolean mask of active catchment cells on the DEM raster.

        Shape matches ``run.grid.shape``. ``True`` where the DEM has a
        valid positive elevation. Cached on first access.
        """
        raster = self.geographic_raster("watershed_dem")
        dem = raster.data.astype(float)
        return np.isfinite(dem) & (dem > 0)

    @cached_property
    def dem(self) -> np.ndarray:
        """DEM as ``float64`` with the source nodata sentinel replaced by NaN.

        Use this when plotting or applying NaN-aware reductions. For a
        bit-for-bit copy of the stored raster (native dtype, sentinel
        preserved), use ``run.geographic_raster("watershed_dem").data``.
        """
        raster = self.geographic_raster("watershed_dem")
        arr = raster.data.astype("float64", copy=True)
        nodata = raster.nodata
        if nodata is not None:
            arr[arr == float(nodata)] = np.nan
        return arr

    @cached_property
    def outlet(self) -> tuple[float, float]:
        """Outlet coordinates ``(x, y)`` in the simulation CRS.

        Reads ``x_outlet`` / ``y_outlet`` from ``geographic_metadata``.
        Raises ``RuntimeError`` if either is absent (e.g. catchment
        defined by a pre-drawn shapefile rather than a pour point).
        """
        meta = self._catalog.read_geographic_metadata(self._sim_id)
        missing = [k for k in ("x_outlet", "y_outlet") if k not in meta]
        if missing:
            raise RuntimeError(
                f"Outlet coordinates missing in geographic_metadata for "
                f"'{self._sim_id}' ({missing}). The catchment may have "
                "been defined by a shapefile (catch_def != 'from_outlet_coord')."
            )
        return (float(meta["x_outlet"]), float(meta["y_outlet"]))

    def field(
        self,
        variable: str,
        timestep: int = -1,
        layer: int | None = None,
        *,
        bbox: tuple[float, float, float, float] | None = None,
    ) -> np.ndarray:
        """Read one field array from the simulation Zarr store.

        Parameters
        ----------
        variable
            Public field name registered in ``hydromodpy.results.field_registry``.
        timestep
            Timestep index. Negative values count from the end.
        layer
            Optional layer index for three-dimensional fields.
        bbox
            Optional ``(xmin, ymin, xmax, ymax)`` in the simulation CRS.
            Cells whose centroid falls outside the bounding box are set to
            ``NaN`` (for float dtypes) or ``0`` (for integer dtypes).

        Returns
        -------
        numpy.ndarray
            Field values for the requested time and layer selection.
        """
        sz = self._catalog.open_zarr(self._sim_id)
        try:
            n_ts = self._load_row().get("n_timesteps")
            if n_ts is not None and timestep < 0:
                timestep = n_ts + timestep
            try:
                arr = sz.read_field(variable, timestep, layer=layer)
            except KeyError as exc:
                raise FieldNotFoundError(
                    f"Field '{variable}' not found in simulation '{self._sim_id}'",
                    sim_id=self._sim_id,
                    variable=variable,
                ) from exc
        finally:
            sz.close()
        if bbox is not None:
            arr = _apply_bbox_mask(self, arr, bbox)
        return arr

    def has_field(self, variable: str, *, subgroup: str | None = None) -> bool:
        """Return true when a field array is persisted in this run's Zarr store."""
        sz = self._catalog.open_zarr(self._sim_id)
        try:
            if subgroup is not None:
                group = sz.root.get(subgroup)
                return group is not None and variable in group
            if field_registry.has(variable):
                return lookup_zarr_path(sz.root, field_registry.get(variable).zarr_path) is not None
            return any(
                variable in group
                for group in (
                    sz.root,
                    sz.root.get("derived"),
                    sz.root.get("budget"),
                    sz.root.get("mesh"),
                )
                if group is not None
            )
        finally:
            sz.close()

    @property
    def mesh(self) -> Mesh:
        """Unstructured simulation mesh used by field arrays.

        Raises
        ------
        RuntimeError
            Raised for lumped simulations that have no spatial grid.
        """
        if self._load_row().get("solver_category") == "lumped":
            raise RuntimeError("lumped simulation has no spatial grid")
        sz = self._catalog.open_zarr(self._sim_id)
        try:
            mesh_grp = sz.root["mesh"]
            topo = mesh_grp.get("topography")
            topo_ref = mesh_grp.get("topography_reference")
            return Mesh(
                vertices=mesh_grp["vertices"][:],
                face_node_connectivity=mesh_grp["face_node_connectivity"][:],
                z_interfaces=mesh_grp["z_interfaces"][:],
                topography=None if topo is None else topo[:],
                topography_reference=None if topo_ref is None else topo_ref[:],
            )
        finally:
            sz.close()

    def _regular_shape_for_field_size(self, root, n_cells: int) -> tuple[int, int]:
        mesh = root.get("mesh")
        if mesh is not None:
            raw_shape = mesh.attrs.get("structured_shape")
            if raw_shape is not None:
                shape = tuple(int(v) for v in raw_shape)
                if len(shape) == 2 and shape[0] * shape[1] == int(n_cells):
                    return shape[0], shape[1]
        try:
            grid_shape = self.grid.shape
        except Exception as exc:
            raise ValueError(
                f"Field has {n_cells} cells but this run has no regular grid shape metadata."
            ) from exc
        if int(grid_shape[0]) * int(grid_shape[1]) != int(n_cells):
            raise ValueError(
                f"Field has {n_cells} cells; grid shape {grid_shape} "
                f"requires {int(grid_shape[0]) * int(grid_shape[1])} cells."
            )
        return int(grid_shape[0]), int(grid_shape[1])


def _apply_bbox_mask(
    run: RunGeographicMixin,
    array: np.ndarray,
    bbox: tuple[float, float, float, float],
) -> np.ndarray:
    """Mask cells outside ``bbox`` (xmin, ymin, xmax, ymax) in-place style."""
    xmin, ymin, xmax, ymax = (float(v) for v in bbox)
    if not (xmin < xmax and ymin < ymax):
        raise ValueError(f"bbox must satisfy xmin<xmax and ymin<ymax; got {bbox!r}")
    try:
        grid = run.grid
    except Exception as exc:
        raise ValueError(
            "bbox= filter requires a structured grid; this run has no grid metadata."
        ) from exc
    xs, ys = grid.cell_centers_xy()
    inside = (xs >= xmin) & (xs <= xmax) & (ys >= ymin) & (ys <= ymax)
    arr = np.asarray(array)
    if arr.ndim == 0 or arr.size != inside.size:
        if arr.ndim >= 1 and arr.shape[-1] == inside.size:
            mask = ~inside.reshape((1,) * (arr.ndim - 1) + (-1,))
        elif arr.shape == grid.shape:
            mask = ~inside.reshape(grid.shape)
        else:
            raise ValueError(
                f"bbox= mask requires array shape compatible with grid; "
                f"got array {arr.shape}, grid {grid.shape}."
            )
    else:
        mask = ~inside.reshape(arr.shape)
    if arr.dtype.kind == "f":
        out = arr.astype("float64", copy=True)
        out[mask] = np.nan
    else:
        out = arr.copy()
        out[mask] = 0
    return out
