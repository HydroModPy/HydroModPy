"""Catalog-wide ML/DL dataset loader.

Joins scalar tables (``simulations``, ``parameters``, ``metrics``,
``runs_environment``) with optional per-simulation Zarr field arrays
into a single :class:`xarray.Dataset` indexed by ``sim_id``.

Field arrays stay lazy: each per-sim Zarr store is opened with
``xr.open_zarr`` (dask-backed) and concatenated along ``sim_id``. No
``np.stack`` / ``np.concatenate`` is involved, so the loader scales to
N=1000+ runs without OOM.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandas as pd

if TYPE_CHECKING:
    import xarray as xr

    from hydromodpy.results.catalog.facade import SimulationCatalog


_SIM_META_COLUMNS: tuple[str, ...] = (
    "sim_id",
    "name",
    "project",
    "solver",
    "solver_category",
    "flow_regime",
    "status",
    "n_cells",
    "n_layers",
    "n_timesteps",
    "config_hash",
    "scientific_objective",
    "study_area_name",
    "created_at",
    "duration_s",
)

_ENV_META_COLUMNS: tuple[str, ...] = (
    "python_version",
    "hydromodpy_version",
    "platform",
    "hostname",
    "git_commit",
    "project_git_commit",
    "mf6_binary_sha256",
    "mf6_version_text",
    "conda_env_hash",
    "rng_seed",
)


class DatasetLoader:
    """Build an ``xr.Dataset`` joining scalars + Zarr fields for a cohort.

    The loader is stateless apart from the catalog it wraps. ``load`` accepts
    the same ``filters`` keyword set as :meth:`SimulationCatalog.find` plus
    an optional ``fields`` list selecting which Zarr variables to attach.
    """

    def __init__(self, catalog: SimulationCatalog) -> None:
        self._catalog = catalog

    def load(
        self,
        filters: dict[str, Any] | None = None,
        *,
        fields: list[str] | None = None,
        include_params: bool = True,
        include_metrics: bool = True,
        include_env: bool = True,
    ) -> xr.Dataset:
        """Return one ``xr.Dataset`` aggregating a cohort of simulations.

        Parameters
        ----------
        filters
            Forwarded to :meth:`SimulationCatalog.find`. ``None`` means
            "every simulation in the catalog".
        fields
            Optional list of Zarr field names (e.g. ``["head"]``) to attach
            lazily. ``None`` skips field attachment and returns a scalar-only
            dataset (cheaper, no Zarr open).
        include_params
            When ``True`` (default) merge a wide-pivot of the ``parameters``
            table as scalar coords on ``sim_id``.
        include_metrics
            When ``True`` (default) merge a wide-pivot of the ``metrics``
            table.
        include_env
            When ``True`` (default) merge selected ``runs_environment``
            columns.
        """
        import xarray as xr

        group = self._resolve_group(filters)
        sim_ids = group.sim_ids
        if not sim_ids:
            return xr.Dataset(coords={"sim_id": []})

        scalars = self._build_scalar_frame(
            sim_ids,
            include_params=include_params,
            include_metrics=include_metrics,
            include_env=include_env,
        )
        ds = self._scalars_to_xarray(scalars)

        if fields:
            field_ds = self._open_fields_lazy(sim_ids, fields)
            if len(field_ds.data_vars) > 0:
                ds = xr.merge([ds, field_ds], compat="override", join="outer")

        return ds

    # -- Implementation ------------------------------------------------------

    def _resolve_group(self, filters: dict[str, Any] | None):
        if not filters:
            from hydromodpy.results.simulation_group import SimulationGroup

            rows = self._catalog._connection.execute(
                "SELECT CAST(sim_id AS VARCHAR) FROM simulations ORDER BY created_at DESC"
            ).fetchall()
            return SimulationGroup([str(r[0]) for r in rows], self._catalog)
        return self._catalog.find(**filters)

    def _build_scalar_frame(
        self,
        sim_ids: list[str],
        *,
        include_params: bool,
        include_metrics: bool,
        include_env: bool,
    ) -> pd.DataFrame:
        df = self._select_simulations(sim_ids)

        if include_params:
            params_df = self._select_parameters(sim_ids)
            if not params_df.empty:
                df = df.merge(params_df, on="sim_id", how="left")

        if include_metrics:
            metrics_df = self._select_metrics(sim_ids)
            if not metrics_df.empty:
                df = df.merge(metrics_df, on="sim_id", how="left")

        if include_env:
            env_df = self._select_environment(sim_ids)
            if not env_df.empty:
                df = df.merge(env_df, on="sim_id", how="left")

        return df

    def _select_simulations(self, sim_ids: list[str]) -> pd.DataFrame:
        placeholders = ", ".join(["?"] * len(sim_ids))
        cols = ", ".join(_SIM_META_COLUMNS)
        df = self._catalog._connection.execute(
            f"SELECT {cols} FROM simulations WHERE sim_id IN ({placeholders})",
            sim_ids,
        ).fetchdf()
        df["sim_id"] = df["sim_id"].astype(str)
        return df

    def _select_parameters(self, sim_ids: list[str]) -> pd.DataFrame:
        placeholders = ", ".join(["?"] * len(sim_ids))
        df = self._catalog._connection.execute(
            f"SELECT sim_id, param_name, zone_id, value "
            f"FROM parameters WHERE sim_id IN ({placeholders})",
            sim_ids,
        ).fetchdf()
        if df.empty:
            return df
        df["sim_id"] = df["sim_id"].astype(str)
        df["key"] = df["param_name"].where(
            df["zone_id"] == "__global__",
            df["param_name"] + "_" + df["zone_id"],
        )
        wide = df.pivot_table(
            index="sim_id",
            columns="key",
            values="value",
            aggfunc="first",
        ).reset_index()
        wide.columns = ["sim_id"] + [f"param_{c}" for c in wide.columns[1:]]
        return wide

    def _select_metrics(self, sim_ids: list[str]) -> pd.DataFrame:
        placeholders = ", ".join(["?"] * len(sim_ids))
        df = self._catalog._connection.execute(
            f"SELECT sim_id, station_id, metric_name, value "
            f"FROM metrics WHERE sim_id IN ({placeholders})",
            sim_ids,
        ).fetchdf()
        if df.empty:
            return df
        df["sim_id"] = df["sim_id"].astype(str)
        df["key"] = df["metric_name"].where(
            df["station_id"].isna() | (df["station_id"] == "__outlet__"),
            df["metric_name"] + "_" + df["station_id"].astype(str),
        )
        wide = df.pivot_table(
            index="sim_id",
            columns="key",
            values="value",
            aggfunc="first",
        ).reset_index()
        wide.columns = ["sim_id"] + [f"metric_{c}" for c in wide.columns[1:]]
        return wide

    def _select_environment(self, sim_ids: list[str]) -> pd.DataFrame:
        placeholders = ", ".join(["?"] * len(sim_ids))
        cols = ", ".join(_ENV_META_COLUMNS)
        df = self._catalog._connection.execute(
            f"SELECT sim_id, {cols} FROM runs_environment WHERE sim_id IN ({placeholders})",
            sim_ids,
        ).fetchdf()
        if df.empty:
            return df
        df["sim_id"] = df["sim_id"].astype(str)
        df = df.rename(columns={c: f"env_{c}" for c in _ENV_META_COLUMNS})
        return df

    def _scalars_to_xarray(self, df: pd.DataFrame) -> xr.Dataset:
        df = df.set_index("sim_id")
        ds = df.to_xarray()
        ds = ds.rename({"sim_id": "sim_id"})
        return ds

    def _open_fields_lazy(
        self,
        sim_ids: list[str],
        fields: list[str],
    ) -> xr.Dataset:
        """Open each per-sim Zarr store and concat lazily on ``sim_id``.

        Each store is opened with ``xr.open_zarr`` (dask-backed). Variables
        absent from a store are skipped per-simulation. Stores that error out
        are skipped with a logged warning.
        """
        import xarray as xr

        from hydromodpy.core.logging import get_logger

        logger = get_logger(__name__)

        per_var_arrays: dict[str, list[xr.DataArray]] = {v: [] for v in fields}
        per_var_ids: dict[str, list[str]] = {v: [] for v in fields}

        for sid in sim_ids:
            try:
                ds_sim = self._open_simulation_lazy(sid)
            except (KeyError, FileNotFoundError, OSError) as exc:
                logger.warning("Cannot open Zarr store for sim %s: %s", sid, exc)
                continue

            for variable in fields:
                if variable in ds_sim.data_vars:
                    per_var_arrays[variable].append(ds_sim[variable])
                    per_var_ids[variable].append(sid)

        data_vars: dict[str, xr.DataArray] = {}
        for variable in fields:
            arrays = per_var_arrays[variable]
            if not arrays:
                continue
            stacked = xr.concat(
                arrays,
                dim="sim_id",
                combine_attrs="drop_conflicts",
                coords="minimal",
                compat="override",
            )
            stacked = stacked.assign_coords({"sim_id": per_var_ids[variable]})
            data_vars[variable] = stacked

        return xr.Dataset(data_vars)

    def _open_simulation_lazy(self, sim_id: str) -> xr.Dataset:
        """Open one simulation's Zarr root as a lazy ``xr.Dataset``."""
        from hydromodpy.results.simulation_group import _open_simulation_lazy

        return _open_simulation_lazy(self._catalog, sim_id)
