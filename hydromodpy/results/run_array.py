"""Array / xarray provider bound to a single :class:`Run`.

Routes the heavy field-array readers (``dataset``, ``to_xarray_batch``)
and the chainable ``at(timestep, layer)`` accessor off the :class:`Run`
facade so the latter stays a slim orchestrator. Each :class:`Run`
instance owns one :class:`RunArrayProvider` exposed as ``run.array``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.results import field_registry

if TYPE_CHECKING:
    import xarray as xr
    import xugrid as xu

    from hydromodpy.results.run import Run


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

    def dataset(self, variable: str | None = None) -> xu.UgridDataset:
        """Return a :class:`xugrid.UgridDataset` over the simulation's mesh.

        Single entry point for figures: same UGRID topology and dimension
        names regardless of the underlying solver layout (DIS, DISV, or
        triangle / DISU). Pass ``variable=None`` to load every face-aligned
        field present in the store; pass a name to load only that one.
        Variable attributes follow CF-1.11 from
        :mod:`hydromodpy.results.field_registry`.
        """
        import dask.array as da
        import xarray as xr
        import xugrid as xu

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
                    raise KeyError(f"Field '{variable}' not found in simulation '{run._sim_id}'")
                names = [variable]

            data_vars: dict[str, xr.DataArray] = {}
            for name in names:
                desc = field_registry.get(name)
                arr = lookup_zarr_path(sz.root, desc.zarr_path)
                dims = face_shapes[desc.shape]
                if len(dims) != arr.ndim:
                    continue
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

        if not data_vars:
            sz.close()
        return xu.UgridDataset(xr.Dataset(data_vars), grids=[grid])

    def to_xarray_batch(
        self,
        variables: tuple[str, ...] = ("head",),
        *,
        time_slice: slice | None = None,
    ) -> xr.Dataset:
        """Return a lazy :class:`xarray.Dataset` over selected variables.

        Single entry point for ML pipelines that prefer ``xarray`` /
        ``xugrid`` over raw NumPy. Backed by the simulation's Zarr store
        (no copy on read). ``variables`` lists field-registry names to
        include; missing fields raise ``KeyError``. ``time_slice`` is an
        optional ``slice`` object applied to the time dimension.
        """
        import dask.array as da
        import xarray as xr

        run = self._run
        sz = run._catalog.open_zarr(run._sim_id)
        try:
            data_vars: dict[str, xr.DataArray] = {}
            for name in variables:
                desc = field_registry.get(name)
                arr = lookup_zarr_path(sz.root, desc.zarr_path)
                if arr is None:
                    raise KeyError(f"Field '{name}' not found in simulation '{run._sim_id}'")
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
                chunks = arr.chunks if arr.chunks else "auto"
                values = da.from_array(arr, chunks=chunks)
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
        if not data_vars:
            sz.close()
        return xr.Dataset(data_vars)

    def at(self, timestep: int = -1, layer: int | None = None) -> _AtAccessor:
        """Return a chainable accessor bound to ``(timestep, layer)``.

        Enables ``run.array.at(timestep=5).field("head")`` - the dual
        spelling of ``run.field("head", timestep=5)``. Useful in notebook
        sessions where the same slice is reused across several variables.
        """
        return _AtAccessor(self._run, timestep=timestep, layer=layer)


class _AtAccessor:
    """Chainable helper bound to a ``(timestep, layer)`` slice."""

    __slots__ = ("_run", "_timestep", "_layer")

    def __init__(self, run: Run, *, timestep: int, layer: int | None):
        self._run = run
        self._timestep = timestep
        self._layer = layer

    def field(self, variable: str) -> np.ndarray:
        return self._run.field(variable, timestep=self._timestep, layer=self._layer)

    def __repr__(self) -> str:
        layer_str = f", layer={self._layer}" if self._layer is not None else ""
        return f"Run.at(timestep={self._timestep}{layer_str})"
