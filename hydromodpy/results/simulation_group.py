"""Multi-simulation view on the results catalog.

What
----
Iterable, filterable view over a list of ``sim_id`` resolved against a single
``SimulationCatalog``. Builds pivoted ``parameters`` and ``metrics`` frames,
ranks runs (``best``, ``worst``, ``sort_by``), compares scalar metrics across
simulations (``compare``), exports tabular bundles (``to_dataframe``,
``to_csv``), stacks field arrays lazily into an ``xarray.DataArray``
(``to_xarray``, dask-backed), streams runs as tensors
(``to_torch_dataset``), and narrows the set with ``filter(**criteria)``.

Why
---
Calibration ensembles, gallery sweeps, and ad hoc cohorts share the same
"list of runs" abstraction. Centralising it here keeps the per-run loop logic
(sort, pivot, compare) in one place rather than duplicated across notebooks.

Public API
----------
- ``SimulationGroup``: returned by ``SimulationCatalog.find`` and similar
  multi-result entry points. Iteration yields ``Run`` instances; indexing,
  ``len()``, and HTML repr are supported.

Cross-refs
----------
- ``hydromodpy.results.catalog.SimulationCatalog`` is the upstream owner.
- ``hydromodpy.results.run.Run`` is the unit element of the group.
- ``to_xarray`` opens each per-sim Zarr lazily (dask-backed concat).
- ``to_torch_dataset`` streams runs as :class:`torch.Tensor` items.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    import xarray as xr

    from hydromodpy.results.catalog import SimulationCatalog
    from hydromodpy.results.run import Run


def _open_simulation_lazy(catalog: SimulationCatalog, sim_id: str) -> xr.Dataset:
    """Open one simulation's Zarr root as a lazy ``xr.Dataset``.

    Wraps each registered field's Zarr array in ``dask.array.from_array``
    so that the returned dataset is fully lazy: nothing is read until the
    caller materialises slices. Dimensions are read from the field
    registry, not Zarr metadata, so we don't depend on
    ``dimension_names`` (which HydroModPy stores don't carry).
    """
    import dask.array as da
    import xarray as xr
    import zarr

    from hydromodpy.results import field_registry

    zarr_path = catalog.zarr_path_for(sim_id)
    if str(zarr_path).endswith(".zarr.zip"):
        store = zarr.storage.ZipStore(str(zarr_path), mode="r")
        root = zarr.open_group(store, mode="r")
    else:
        store = zarr.storage.LocalStore(str(zarr_path))
        root = zarr.open_group(store, mode="r")

    shape_to_dims = {
        field_registry.SHAPE_TIME_LAYER_FACE: ("time", "layer", "face"),
        field_registry.SHAPE_TIME_FACE: ("time", "face"),
        field_registry.SHAPE_LAYER_FACE: ("layer", "face"),
        field_registry.SHAPE_FACE: ("face",),
        field_registry.SHAPE_PARTICLES: ("time", "particle"),
    }

    data_vars: dict[str, xr.DataArray] = {}
    for name, desc in field_registry.FIELD_REGISTRY.items():
        path = desc.zarr_path
        if "/" in path:
            group_name, var_name = path.split("/", 1)
            group = root.get(group_name)
            if group is None or var_name not in group:
                continue
            arr = group[var_name]
        else:
            if path not in root:
                continue
            arr = root[path]
        dims = shape_to_dims.get(desc.shape, ())
        if len(dims) != arr.ndim:
            dims = tuple(f"dim_{i}" for i in range(arr.ndim))
        chunks = arr.chunks if arr.chunks else "auto"
        dask_arr = da.from_array(arr, chunks=chunks)
        data_vars[name] = xr.DataArray(dask_arr, dims=dims, attrs=dict(arr.attrs))

    return xr.Dataset(data_vars)


class SimulationGroup:
    def __init__(
        self,
        sim_ids: list[str],
        catalog: SimulationCatalog,
    ) -> None:
        self._sim_ids = sim_ids
        self._catalog = catalog

    @property
    def count(self) -> int:
        return len(self._sim_ids)

    @property
    def sim_ids(self) -> list[str]:
        return list(self._sim_ids)

    def __len__(self) -> int:
        return len(self._sim_ids)

    def __iter__(self):
        from hydromodpy.results.run import Run

        for sid in self._sim_ids:
            yield Run(sid, self._catalog)

    def __getitem__(self, index: int) -> Run:
        from hydromodpy.results.run import Run

        return Run(self._sim_ids[index], self._catalog)

    # -- Pivot DataFrames ----------------------------------------------------

    @property
    def parameters(self) -> pd.DataFrame:
        if not self._sim_ids:
            return pd.DataFrame()
        placeholders = ", ".join(["?"] * len(self._sim_ids))
        df = self._catalog._connection.execute(
            f"SELECT sim_id, param_name, zone_id, value "
            f"FROM parameters WHERE sim_id IN ({placeholders})",
            self._sim_ids,
        ).fetchdf()
        if df.empty:
            return df
        df["key"] = df["param_name"].where(
            df["zone_id"] == "__global__",
            df["param_name"] + "_" + df["zone_id"],
        )
        return df.pivot_table(
            index="sim_id",
            columns="key",
            values="value",
            aggfunc="first",
        ).reset_index()

    @property
    def metrics(self) -> pd.DataFrame:
        if not self._sim_ids:
            return pd.DataFrame()
        placeholders = ", ".join(["?"] * len(self._sim_ids))
        df = self._catalog._connection.execute(
            f"SELECT sim_id, station_id, metric_name, value "
            f"FROM metrics WHERE sim_id IN ({placeholders})",
            self._sim_ids,
        ).fetchdf()
        if df.empty:
            return df
        df["key"] = df["metric_name"].where(
            df["station_id"].isna(),
            df["metric_name"] + "_" + df["station_id"],
        )
        return df.pivot_table(
            index="sim_id",
            columns="key",
            values="value",
            aggfunc="first",
        ).reset_index()

    # -- Comparison ----------------------------------------------------------

    def compare(self, metric: str) -> pd.DataFrame:
        if not self._sim_ids:
            return pd.DataFrame()
        placeholders = ", ".join(["?"] * len(self._sim_ids))
        return self._catalog._connection.execute(
            f"SELECT s.sim_id, s.name, s.project, s.solver, m.station_id, m.value "
            f"FROM simulations s "
            f"JOIN metrics m ON s.sim_id = m.sim_id "
            f"WHERE s.sim_id IN ({placeholders}) AND m.metric_name = ? "
            f"ORDER BY m.value DESC",
            self._sim_ids + [metric],
        ).fetchdf()

    def best(self, metric: str) -> Run:
        from hydromodpy.results.run import Run

        if not self._sim_ids:
            raise ValueError("Empty group")
        placeholders = ", ".join(["?"] * len(self._sim_ids))
        row = self._catalog._connection.execute(
            f"SELECT m.sim_id FROM metrics m "
            f"WHERE m.sim_id IN ({placeholders}) AND m.metric_name = ? "
            f"ORDER BY m.value DESC LIMIT 1",
            self._sim_ids + [metric],
        ).fetchone()
        if row is None:
            raise KeyError(f"No metric '{metric}' found in group")
        return Run(str(row[0]), self._catalog)

    def worst(self, metric: str) -> Run:
        from hydromodpy.results.run import Run

        if not self._sim_ids:
            raise ValueError("Empty group")
        placeholders = ", ".join(["?"] * len(self._sim_ids))
        row = self._catalog._connection.execute(
            f"SELECT m.sim_id FROM metrics m "
            f"WHERE m.sim_id IN ({placeholders}) AND m.metric_name = ? "
            f"ORDER BY m.value ASC LIMIT 1",
            self._sim_ids + [metric],
        ).fetchone()
        if row is None:
            raise KeyError(f"No metric '{metric}' found in group")
        return Run(str(row[0]), self._catalog)

    def sort_by(self, metric: str, ascending: bool = True) -> SimulationGroup:
        if not self._sim_ids:
            return self
        placeholders = ", ".join(["?"] * len(self._sim_ids))
        order = "ASC" if ascending else "DESC"
        rows = self._catalog._connection.execute(
            f"SELECT m.sim_id FROM metrics m "
            f"WHERE m.sim_id IN ({placeholders}) AND m.metric_name = ? "
            f"ORDER BY m.value {order}",
            self._sim_ids + [metric],
        ).fetchall()
        sorted_ids = [str(r[0]) for r in rows]
        return SimulationGroup(sorted_ids, self._catalog)

    # -- ML-ready export -----------------------------------------------------

    def to_dataframe(
        self,
        *,
        params: list[str] | None = None,
        metrics: list[str] | None = None,
    ) -> pd.DataFrame:
        """Return a wide table joining metadata, parameters, and metrics.

        Parameters
        ----------
        params
            Optional whitelist of parameter column names to keep after the pivot.
        metrics
            Optional whitelist of metric column names to keep.
        """
        if not self._sim_ids:
            return pd.DataFrame()
        placeholders = ", ".join(["?"] * len(self._sim_ids))
        sims = self._catalog._connection.execute(
            f"SELECT sim_id, project, solver, solver_category, flow_regime, "
            f"n_cells, n_layers "
            f"FROM simulations WHERE sim_id IN ({placeholders})",
            self._sim_ids,
        ).fetchdf()

        params_df = self.parameters
        metrics_df = self.metrics

        if params is not None and not params_df.empty:
            keep = ["sim_id", *[c for c in params_df.columns if c in params]]
            params_df = params_df[[c for c in keep if c in params_df.columns]]
        if metrics is not None and not metrics_df.empty:
            keep = ["sim_id", *[c for c in metrics_df.columns if c in metrics]]
            metrics_df = metrics_df[[c for c in keep if c in metrics_df.columns]]

        df = sims
        if not params_df.empty:
            df = df.merge(params_df, on="sim_id", how="left")
        if not metrics_df.empty:
            df = df.merge(metrics_df, on="sim_id", how="left")
        return df

    def to_csv(self, path: Path | str) -> None:
        self.to_dataframe().to_csv(str(path), index=False)

    def to_xarray(self, variable: str, *, dim: str = "sim") -> xr.DataArray:
        """Return a lazy stacked ``xarray.DataArray`` of ``variable`` across sims.

        Each per-simulation Zarr store is opened with ``xr.open_zarr`` (dask
        backend) and arrays are concatenated along ``dim`` whose coordinate
        values are the simulation ids. Nothing is read into memory until the
        caller materialises the array (``.compute()``, ``.values``, slicing,
        etc.). Simulations that lack the variable are skipped silently; if
        none match, an empty :class:`xarray.DataArray` is returned.

        Parameters
        ----------
        variable
            Public field name (as declared in the
            :mod:`hydromodpy.results.field_registry`).
        dim
            Name of the new stacking dimension (default ``"sim"``).
        """
        import xarray as xr

        arrays: list[xr.DataArray] = []
        sim_ids: list[str] = []
        for sid in self._sim_ids:
            try:
                ds = _open_simulation_lazy(self._catalog, sid)
            except (KeyError, FileNotFoundError, OSError):
                continue
            if variable not in ds.data_vars:
                continue
            arrays.append(ds[variable])
            sim_ids.append(sid)

        if not arrays:
            return xr.DataArray(name=variable)
        stacked = xr.concat(
            arrays,
            dim=dim,
            combine_attrs="drop_conflicts",
            coords="minimal",
            compat="override",
        )
        stacked = stacked.assign_coords({dim: sim_ids})
        stacked.name = variable
        return stacked

    def to_torch_dataset(
        self,
        variables: list[str],
        *,
        timestep: int | None = None,
        layer: int | None = None,
    ):
        """Return a :class:`torch.utils.data.IterableDataset` streaming runs.

        Each item yielded is a ``dict[str, torch.Tensor]`` keyed by entries
        in ``variables`` (Zarr field names). Reads are streamed: only the
        active simulation's slab is loaded at iteration time, so memory
        footprint is O(one run) regardless of cohort size.

        Parameters
        ----------
        variables
            Field names to materialise per item.
        timestep
            Optional timestep index (negative = from end). ``None`` returns
            the full time axis when present.
        layer
            Optional layer index. ``None`` returns the full layer axis when
            present.

        Raises
        ------
        ImportError
            When :mod:`torch` is not installed. The error is a
            :class:`hydromodpy.results.catalog.discovery.MissingMLDependencyError`.
        """
        try:
            cls = _build_torch_iterable_dataset_class()
        except ImportError as exc:
            from hydromodpy.results.catalog.discovery import MissingMLDependencyError

            raise MissingMLDependencyError(
                "torch",
                hint="install PyTorch (`pip install torch`) to stream runs as tensors",
            ) from exc

        return cls(
            sim_ids=list(self._sim_ids),
            catalog=self._catalog,
            variables=list(variables),
            timestep=timestep,
            layer=layer,
        )

    # -- Filter --------------------------------------------------------------

    def filter(self, **criteria) -> SimulationGroup:
        """Intersect with another ``catalog.find(**criteria)`` call.

        Equivalent to ``catalog.find(...)`` but restricted to this group's
        simulations. Useful for chainable exploration in notebooks.
        """
        if not self._sim_ids:
            return self
        subgroup = self._catalog.find(**criteria)
        common = [sid for sid in self._sim_ids if sid in subgroup.sim_ids]
        return SimulationGroup(common, self._catalog)

    # -- Repr ----------------------------------------------------------------

    def __repr__(self) -> str:
        return f"SimulationGroup(count={self.count})"

    def _repr_html_(self) -> str:
        if not self._sim_ids:
            return "<div><b>SimulationGroup</b> <i>(empty)</i></div>"
        preview = self.to_dataframe()
        try:
            cols = [c for c in ("sim_id", "project", "solver") if c in preview.columns]
            head = preview[cols].head(10).to_html(index=False)
        except Exception:
            head = ""
        return f"<div><b>SimulationGroup</b> ({self.count} simulations)</div>{head}"


_TORCH_DATASET_CLASS_CACHE: type | None = None


def _build_torch_iterable_dataset_class() -> type:
    """Build (once) and return the torch-aware IterableDataset subclass.

    The class is constructed at first call so importing this module never
    requires :mod:`torch`. The cached class is reused by every
    :meth:`SimulationGroup.to_torch_dataset` invocation.
    """
    global _TORCH_DATASET_CLASS_CACHE
    if _TORCH_DATASET_CLASS_CACHE is not None:
        return _TORCH_DATASET_CLASS_CACHE

    import numpy as np
    import torch
    from torch.utils.data import IterableDataset

    class _TorchSimulationIterableDataset(IterableDataset):
        """Streaming dataset yielding ``{var: tensor, "sim_id": str}`` per run."""

        def __init__(
            self,
            *,
            sim_ids: list[str],
            catalog: SimulationCatalog,
            variables: list[str],
            timestep: int | None,
            layer: int | None,
        ) -> None:
            super().__init__()
            self._sim_ids = sim_ids
            self._catalog = catalog
            self._variables = variables
            self._timestep = timestep
            self._layer = layer

        def __iter__(self) -> Iterator[dict]:
            for sid in self._sim_ids:
                try:
                    ds = _open_simulation_lazy(self._catalog, sid)
                except (KeyError, FileNotFoundError, OSError):
                    continue
                sample: dict[str, object] = {"sim_id": sid}
                keep = True
                for variable in self._variables:
                    if variable not in ds.data_vars:
                        keep = False
                        break
                    arr = ds[variable]
                    if self._timestep is not None and "time" in arr.dims:
                        arr = arr.isel(time=self._timestep)
                    if self._layer is not None and "layer" in arr.dims:
                        arr = arr.isel(layer=self._layer)
                    values = np.ascontiguousarray(arr.values)
                    sample[variable] = torch.from_numpy(values)
                if keep:
                    yield sample

        def __len__(self) -> int:
            return len(self._sim_ids)

    _TORCH_DATASET_CLASS_CACHE = _TorchSimulationIterableDataset
    return _TorchSimulationIterableDataset
