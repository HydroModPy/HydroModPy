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
import pandas as pd

from hydromodpy.results import field_registry
from hydromodpy.results.errors import FieldNotFoundError
from hydromodpy.results.run.array import lookup_zarr_path
from hydromodpy.results.run.contracts import Mesh, RasterField

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    import geopandas as gpd

    from hydromodpy.results.grid import Grid
    from hydromodpy.results.run import Run


def crs_proj_from_metadata(metadata: Mapping[str, object]) -> str | None:
    """Return the run's projected CRS, ``None`` when absent or empty.

    The single place ``crs_proj`` is read out of ``geographic_metadata``, so the
    mesh payload and :class:`~hydromodpy.results.grid.Grid` cannot drift apart on
    what counts as an unknown frame.
    """
    crs = metadata.get("crs_proj")
    return None if crs in (None, "") else str(crs)


def crs_epsg(run: Run) -> int | None:
    """Return the EPSG code the catalog recorded for ``run``, ``None`` when unknown.

    A module function rather than a ``Run`` attribute: ``Run`` is capped at 50
    public attributes (``tests/unit/results/test_run_surface.py``).
    """
    frame = run._catalog.backend.query(
        "SELECT crs_epsg FROM simulations WHERE sim_id = ?",
        [run.sim_id],
    )
    if frame.empty:
        return None
    value = frame.iloc[0]["crs_epsg"]
    return None if pd.isna(value) else int(value)


def geographic_metadata(run: Run) -> dict[str, str]:
    """Return the ``key -> value`` geographic metadata the geographic step wrote.

    Holds the declared outlet (``x_outlet``, ``y_outlet``), the snapped one
    (``x_outlet_snapped``, ``y_outlet_snapped``, ``outlet_snap_distance_m``)
    and the projected CRS (``crs_proj``). Values are the stored text; an empty
    dict when the run recorded none.
    """
    return run._catalog.read_geographic_metadata(run.sim_id)


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
        """Read one field, persisted or recomputed on the fly.

        Delegates to ``Catalog.query_field``, which falls back to the virtual
        derivations (watertable elevation/depth, seepage mask, drain outflow)
        when the field is not persisted. This keeps ``has_field`` honest: a
        variable it reports as available always reads back as an array.
        Each call opens the store: many steps read through :func:`field_range`.

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
        n_ts = self._load_row().get("n_timesteps")
        if n_ts is not None and timestep < 0:
            timestep = n_ts + timestep
        try:
            arr = self._catalog.query_field(self._sim_id, variable, timestep, layer=layer)
        except KeyError as exc:
            raise _field_not_found(self._sim_id, variable) from exc
        if bbox is not None:
            arr = _apply_bbox_mask(self, arr, bbox)
        return arr

    def has_field(self, variable: str, *, subgroup: str | None = None) -> bool:
        """Return true when a field is available for this run.

        A field counts as available when it is persisted, or when it is a
        virtual field this store can rebuild (watertable elevation/depth and
        seepage mask from the stored head, drain outflow from the per-cell
        budget), so figures find them even though ``results.derived.*`` is
        off by default.
        """
        from hydromodpy.results.derive.virtual_fields import available_virtual_fields

        sz = self._catalog.open_zarr(self._sim_id)
        try:
            if subgroup is not None:
                group = sz.root.get(subgroup)
                return group is not None and variable in group
            if field_registry.has(variable):
                if lookup_zarr_path(sz.root, field_registry.get(variable).zarr_path) is not None:
                    return True
            elif any(
                variable in group
                for group in (
                    sz.root,
                    sz.root.get("derived"),
                    sz.root.get("budget"),
                    sz.root.get("mesh"),
                )
                if group is not None
            ):
                return True
            return variable in available_virtual_fields(sz.root)
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
        crs = crs_proj_from_metadata(self._catalog.read_geographic_metadata(self._sim_id))
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
                crs=crs,
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


def field_range(
    run: Run,
    variable: str,
    start: int,
    stop: int,
    layer: int | None = None,
) -> np.ndarray:
    """Read one field over timesteps ``[start, stop)``, the store opened once.

    Row ``i`` is ``run.field(variable, timestep=start + i, layer=layer)``, bit
    for bit: a stored array is sliced in one read, a field rebuilt on read is
    rebuilt over the whole range. Negative bounds count from the end, as the
    timestep of ``Run.field`` does. A module function rather than a ``Run``
    attribute, and read on the catalog's reader pair rather than through a
    ``Catalog`` method: both classes sit at their public-surface caps.

    Raises
    ------
    FieldNotFoundError
        The field is neither stored nor derivable, as ``Run.field`` raises it.
    IndexError
        The range leaves the time axis of the run.
    """
    from hydromodpy.results.derive.virtual_fields import read_field_range_or_virtual

    n_ts = run._load_row().get("n_timesteps")
    if n_ts is not None:
        start = n_ts + start if start < 0 else start
        stop = n_ts + stop if stop < 0 else stop
    try:
        return read_field_range_or_virtual(
            run._catalog, run.sim_id, variable, start, stop, layer=layer
        )
    except KeyError as exc:
        raise _field_not_found(run.sim_id, variable) from exc


def field_steps(run: Run, variable: str, steps: Sequence[int]) -> np.ndarray:
    """Read one field at ``steps``, one row per step in the order given.

    Each run of consecutive steps is read with :func:`field_range`, a lone
    step with ``run.field``. A run view whose catalog opens no store, a
    stand-in for instance, is read step by step; the rows are the same.
    """
    order = [int(step) for step in steps]
    if not order:
        return np.empty((0, 0), dtype="float64")
    if not callable(getattr(getattr(run, "_catalog", None), "open_zarr", None)):
        return np.stack([np.asarray(run.field(variable, timestep=step)) for step in order])
    n_ts = run._load_row().get("n_timesteps")
    if n_ts is not None:
        order = [n_ts + step if step < 0 else step for step in order]
    parts: list[np.ndarray] = []
    for first, last in _consecutive_runs(order):
        if last - first == 1:
            parts.append(np.asarray(run.field(variable, timestep=order[first]))[None])
        else:
            parts.append(field_range(run, variable, order[first], order[last - 1] + 1))
    return np.concatenate(parts)


def _consecutive_runs(order: list[int]) -> list[tuple[int, int]]:
    """Return the ``[first, last)`` positions of each run of consecutive steps.

    A negative step, left when the run recorded no step count, stays alone.
    """
    bounds: list[tuple[int, int]] = []
    first = 0
    for position in range(1, len(order) + 1):
        joined = (
            position < len(order)
            and order[position - 1] >= 0
            and order[position] == order[position - 1] + 1
        )
        if not joined:
            bounds.append((first, position))
            first = position
    return bounds


def _field_not_found(sim_id: str, variable: str) -> FieldNotFoundError:
    """Return the error a field read raises when nothing stores or rebuilds the field."""
    from hydromodpy.results.derive.config_flags import config_option_for, enable_options_hint

    option = config_option_for(variable)
    hint = "" if option is None else f" {enable_options_hint([option])}"
    return FieldNotFoundError(
        f"Field '{variable}' not found in simulation '{sim_id}'.{hint}",
        sim_id=sim_id,
        variable=variable,
    )


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
