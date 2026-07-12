"""Array / xarray provider bound to a single :class:`Run`.

Routes the heavy field-array readers (``dataset``, ``to_xarray_batch``)
off the :class:`Run` facade so the latter stays a slim orchestrator.
Each :class:`Run` instance owns one :class:`RunArrayProvider` exposed as
``run.array``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.core.logging import get_logger
from hydromodpy.results import field_registry
from hydromodpy.results.errors import FieldNotFoundError

if TYPE_CHECKING:
    import xarray as xr
    import xugrid as xu

    from hydromodpy.results.run import Run

logger = get_logger(__name__)

_DASK_FALLBACK_WARNED = False


def _optional_dask_array():
    """Return ``dask.array`` when installed, otherwise ``None``.

    Warns once when dask is absent: the array views then load eagerly (full
    ``np.asarray``), which can OOM on a large multi-year store.
    """
    global _DASK_FALLBACK_WARNED
    try:
        import dask.array as da
    except ModuleNotFoundError as exc:
        if exc.name != "dask":
            raise
        if not _DASK_FALLBACK_WARNED:
            logger.warning(
                "dask is not installed: field/xarray views load eagerly into RAM "
                "and can OOM on large stores. Install dask for lazy access."
            )
            _DASK_FALLBACK_WARNED = True
        return None
    return da


def lookup_zarr_path(root, zarr_path: str):
    """Resolve a registry zarr_path against a Zarr root, returning ``None`` if absent."""
    if "/" in zarr_path:
        grp_name, var_name = zarr_path.split("/", 1)
        grp = root.get(grp_name)
        if grp is None or var_name not in grp:
            return None
        return grp[var_name]
    return root.get(zarr_path)


class RunArrayProvider:
    """Field-array readers (UGRID / xarray) bound to a single :class:`Run`."""

    def __init__(self, run: Run) -> None:
        self._run = run

    def dataset(
        self,
        variable: str | None = None,
        *,
        bbox: tuple[float, float, float, float] | None = None,
    ) -> xu.UgridDataset:
        """Return a :class:`xugrid.UgridDataset` over the simulation's mesh.

        Single entry point for figures: same UGRID topology and dimension
        names regardless of the underlying solver layout (DIS, DISV, or
        triangle / DISU). Pass ``variable=None`` to load every face-aligned
        field present in the store; pass a name to load only that one.
        Variable attributes follow CF-1.11 from
        :mod:`hydromodpy.results.field_registry`.

        Parameters
        ----------
        variable
            Optional registry name to load. ``None`` loads all face-aligned
            fields present in the store.
        bbox
            Optional ``(xmin, ymin, xmax, ymax)`` in the simulation CRS;
            restricts the dataset to faces whose centroid falls inside.
        """
        import xarray as xr
        import xugrid as xu

        da = _optional_dask_array()
        run = self._run
        mesh = run.mesh
        verts = np.asarray(mesh.vertices, dtype=float)
        fnc = np.asarray(mesh.face_node_connectivity, dtype=int)
        grid = xu.Ugrid2d(
            node_x=verts[:, 0],
            node_y=verts[:, 1],
            fill_value=-1,
            face_node_connectivity=fnc,
        )
        face_dim = grid.face_dimension

        face_shapes = {
            field_registry.SHAPE_FACE: (face_dim,),
            field_registry.SHAPE_LAYER_FACE: ("layer", face_dim),
            field_registry.SHAPE_TIME_FACE: ("time", face_dim),
            field_registry.SHAPE_TIME_LAYER_FACE: ("time", "layer", face_dim),
        }

        sz = run._catalog.open_zarr(run._sim_id)
        try:
            if variable is None:
                names = [
                    n
                    for n, d in field_registry.FIELD_REGISTRY.items()
                    if d.shape in face_shapes and lookup_zarr_path(sz.root, d.zarr_path) is not None
                ]
            else:
                desc = field_registry.get(variable)
                if desc.shape not in face_shapes:
                    raise ValueError(
                        f"Field '{variable}' has shape '{desc.shape}', not face-aligned"
                    )
                if lookup_zarr_path(sz.root, desc.zarr_path) is None:
                    raise FieldNotFoundError(
                        f"Field '{variable}' not found in simulation '{run._sim_id}'",
                        sim_id=run._sim_id,
                        variable=variable,
                    )
                names = [variable]

            data_vars: dict[str, xr.DataArray] = {}
            for name in names:
                desc = field_registry.get(name)
                arr = lookup_zarr_path(sz.root, desc.zarr_path)
                dims = face_shapes[desc.shape]
                if len(dims) != arr.ndim:
                    continue
                if da is None:
                    values = np.asarray(arr)
                else:
                    chunks = arr.chunks if arr.chunks else "auto"
                    values = da.from_array(arr, chunks=chunks)
                data_vars[name] = xr.DataArray(
                    values,
                    dims=dims,
                    attrs=field_registry.cf_attrs(name),
                )
        except Exception:
            sz.close()
            raise

        if da is None or not data_vars:
            sz.close()
        ds = xu.UgridDataset(xr.Dataset(data_vars), grids=[grid])
        if bbox is not None:
            ds = _bbox_select_ugrid(ds, grid, bbox, face_dim)
        return ds

    def list_fields(self) -> list[str]:
        """Return the registry field names readable through ``run.field``.

        Mirrors ``read_field`` resolution: a name is listed when it is a
        direct key of the store root or of the ``state`` / ``derived`` /
        ``budget`` subgroups. Reads only the store layout, never the arrays.
        """
        run = self._run
        sz = run._catalog.open_zarr(run._sim_id)
        try:
            groups = [sz.root, *(sz.root.get(g) for g in ("state", "derived", "budget"))]
            present = {key for group in groups if group is not None for key in group.keys()}
            return sorted(name for name in field_registry.FIELD_REGISTRY if name in present)
        finally:
            sz.close()

    def to_xarray_batch(
        self,
        variables: tuple[str, ...] = ("head",),
        *,
        time_slice: slice | None = None,
        bbox: tuple[float, float, float, float] | None = None,
    ) -> xr.Dataset:
        """Return a lazy :class:`xarray.Dataset` over selected variables.

        Single entry point for ML pipelines that prefer ``xarray`` /
        ``xugrid`` over raw NumPy. Backed by the simulation's Zarr store
        (no copy on read). ``variables`` lists field-registry names to
        include; missing fields raise ``FieldNotFoundError``. ``time_slice``
        is an optional ``slice`` object applied to the time dimension.
        ``bbox`` restricts the dataset to cells whose centroid lies within
        the bounding box.
        """
        import xarray as xr

        da = _optional_dask_array()
        run = self._run
        sz = run._catalog.open_zarr(run._sim_id)
        try:
            data_vars: dict[str, xr.DataArray] = {}
            for name in variables:
                desc = field_registry.get(name)
                arr = lookup_zarr_path(sz.root, desc.zarr_path)
                if arr is None:
                    raise FieldNotFoundError(
                        f"Field '{name}' not found in simulation '{run._sim_id}'",
                        sim_id=run._sim_id,
                        variable=name,
                    )
                shape = desc.shape
                if shape == field_registry.SHAPE_TIME_FACE:
                    dims = ("time", "cell")
                elif shape == field_registry.SHAPE_TIME_LAYER_FACE:
                    dims = ("time", "layer", "cell")
                elif shape == field_registry.SHAPE_LAYER_FACE:
                    dims = ("layer", "cell")
                elif shape == field_registry.SHAPE_FACE:
                    dims = ("cell",)
                else:
                    dims = tuple(f"d{i}" for i in range(arr.ndim))
                if da is None:
                    values = np.asarray(arr)
                else:
                    chunks = arr.chunks if arr.chunks else "auto"
                    values = da.from_array(arr, chunks=chunks)
                if shape == field_registry.SHAPE_TIME_LAYER_FACE and values.ndim == 2:
                    values = values[:, np.newaxis, :]
                if time_slice is not None and dims and dims[0] == "time":
                    values = values[time_slice]
                data_vars[name] = xr.DataArray(
                    values,
                    dims=dims,
                    attrs=field_registry.cf_attrs(name),
                )
        except Exception:
            sz.close()
            raise
        if da is None or not data_vars:
            sz.close()
        ds = xr.Dataset(data_vars)
        if bbox is not None:
            ds = _bbox_select_flat(ds, run, bbox)
        return ds


def _bbox_select_ugrid(ds, grid, bbox, face_dim):
    """Slice a UGRID dataset along ``face_dim`` using a bbox in model CRS."""
    xmin, ymin, xmax, ymax = (float(v) for v in bbox)
    if not (xmin < xmax and ymin < ymax):
        raise ValueError(f"bbox must satisfy xmin<xmax and ymin<ymax; got {bbox!r}")
    xs = np.asarray(grid.face_x)
    ys = np.asarray(grid.face_y)
    inside = (xs >= xmin) & (xs <= xmax) & (ys >= ymin) & (ys <= ymax)
    idx = np.where(inside)[0]
    return ds.isel({face_dim: idx})


def _bbox_select_flat(ds, run, bbox):
    """Slice a flat xarray dataset using a bbox; assumes regular ``run.grid``."""
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
    idx = np.where(inside)[0]
    return ds.isel(cell=idx)
