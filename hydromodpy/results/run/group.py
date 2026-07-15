"""Multi-simulation view on the results catalog.

What
----
Iterable, filterable view over a list of ``sim_id`` resolved against a single
``Catalog``. Builds pivoted ``parameters`` and ``metrics`` frames,
ranks runs (``best``, ``worst``, ``sort_by``), compares scalar metrics across
simulations (``compare``), exports tabular bundles (``to_dataframe``,
``to_csv``), stacks field arrays lazily into an ``xarray.DataArray``
(``to_xarray``, dask-backed), and narrows the set with ``filter(**criteria)``.

Why
---
Calibration ensembles, gallery sweeps, and ad hoc cohorts share the same
"list of runs" abstraction. Centralising it here keeps the per-run loop logic
(sort, pivot, compare) in one place rather than duplicated across notebooks.

Public API
----------
- ``RunSet``: returned by ``Catalog.find`` and similar
  multi-result entry points. Iteration yields ``Run`` instances; indexing,
  ``len()``, and HTML repr are supported.

Cross-refs
----------
- ``hydromodpy.results.catalog.Catalog`` is the upstream owner.
- ``hydromodpy.results.run.Run`` is the unit element of the group.
- ``to_xarray`` opens each per-sim Zarr lazily (dask-backed concat).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from hydromodpy.core import progress

if TYPE_CHECKING:
    from pathlib import Path

    import xarray as xr

    from hydromodpy.results.catalog import Catalog
    from hydromodpy.results.run import Run


def _open_simulation_lazy(catalog: Catalog, sim_id: str) -> xr.Dataset:
    """Open one simulation's Zarr root as a lazy ``xr.Dataset``.

    Delegates to :meth:`SimulationZarr.to_xarray` so the registry-driven
    assembly stays in one place (``results.zarr_store.zarr_reader``);
    CF time decoding is then applied on the resulting dataset.
    """
    import xarray as xr

    sz = catalog.open_zarr(sim_id)
    return xr.decode_cf(sz.to_xarray(), decode_times=True)


class RunSet:
    """Collection view over several simulations from one catalog.

    ``RunSet`` is returned by catalog queries that match more than one
    run. It behaves like a lightweight list of ``Run`` objects and adds cohort
    utilities: pivot parameter tables, pivot metric tables, rank runs, compare
    scalar metrics, export a wide DataFrame, and stack fields lazily.

    Parameters
    ----------
    sim_ids
        Ordered simulation ids in the group.
    catalog
        Catalog used to resolve ids into ``Run`` objects and tabular data.

    Examples
    --------
    >>> group = catalog.find(project="nancon")
    >>> group.count
    >>> group.best("nse").summary()

    See Also
    --------
    hydromodpy.results.run.Run
        Per-simulation view yielded during iteration.
    hydromodpy.results.catalog.Catalog
        Catalog that creates simulation groups.
    """

    def __init__(
        self,
        sim_ids: list[str],
        catalog: Catalog,
    ) -> None:
        self._sim_ids = sim_ids
        self._catalog = catalog

    @property
    def count(self) -> int:
        """Number of simulations in the group."""
        return len(self._sim_ids)

    @property
    def sim_ids(self) -> list[str]:
        """Simulation ids in group order."""
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
        """Wide parameter table with one row per simulation."""
        if not self._sim_ids:
            return pd.DataFrame()
        placeholders = ", ".join(["?"] * len(self._sim_ids))
        df = self._catalog.backend.query(
            f"SELECT sim_id, param_name, zone_id, value "
            f"FROM parameters WHERE sim_id IN ({placeholders})",
            self._sim_ids,
        )
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
        """Wide metric table with one row per simulation."""
        if not self._sim_ids:
            return pd.DataFrame()
        placeholders = ", ".join(["?"] * len(self._sim_ids))
        df = self._catalog.backend.query(
            f"SELECT sim_id, station_id, metric_name, value "
            f"FROM metrics WHERE sim_id IN ({placeholders})",
            self._sim_ids,
        )
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

    def _resolve_metric_station(self, metric: str, station: str | None) -> str | None:
        """Return the station to scope a metric ranking to.

        When ``station`` is given it is used verbatim. Otherwise the distinct
        stations carrying ``metric`` across the group are inspected: a single
        station (the common case) is used silently, and several stations raise a
        ``KeyError`` asking the caller to disambiguate, so best/worst/compare
        never mix stations across runs.
        """
        if station is not None:
            return station
        placeholders = ", ".join(["?"] * len(self._sim_ids))
        rows = self._catalog.backend.query(
            f"SELECT DISTINCT station_id FROM metrics "
            f"WHERE sim_id IN ({placeholders}) AND metric_name = ?",
            self._sim_ids + [metric],
        )
        stations = sorted(str(value) for value in rows["station_id"].tolist())
        if len(stations) <= 1:
            return stations[0] if stations else None
        raise KeyError(
            f"Metric '{metric}' exists at multiple stations ({', '.join(stations)}); "
            "pass station= to disambiguate."
        )

    def compare(self, metric: str, *, station: str | None = None) -> pd.DataFrame:
        """Compare one metric across every simulation in the group.

        Parameters
        ----------
        metric
            Metric name stored in the catalog.
        station
            Observation station to scope the comparison to. When omitted and the
            metric exists at a single station, that station is used; several
            stations raise a ``KeyError``.

        Returns
        -------
        pandas.DataFrame
            Rows ordered from highest to lowest metric value.
        """
        if not self._sim_ids:
            return pd.DataFrame()
        resolved = self._resolve_metric_station(metric, station)
        placeholders = ", ".join(["?"] * len(self._sim_ids))
        query = (
            f"SELECT s.sim_id, s.name, s.project, sv.code AS solver, "
            f"m.station_id, m.value "
            f"FROM simulations s "
            f"JOIN solvers sv ON s.solver_id = sv.id "
            f"JOIN metrics m ON s.sim_id = m.sim_id "
            f"WHERE s.sim_id IN ({placeholders}) AND m.metric_name = ?"
        )
        params = self._sim_ids + [metric]
        if resolved is not None:
            query += " AND m.station_id = ?"
            params.append(resolved)
        query += " ORDER BY m.value DESC"
        return self._catalog.backend.query(query, params)

    def best(self, metric: str, *, station: str | None = None) -> Run:
        """Return the run with the highest value for ``metric``.

        ``station`` scopes the ranking; when omitted a single-station metric is
        used silently and a multi-station metric raises ``KeyError``.

        Raises
        ------
        ValueError
            Raised when the group is empty.
        KeyError
            Raised when the metric is absent, or ambiguous across stations.
        """
        return self._extreme(metric, station=station, descending=True)

    def worst(self, metric: str, *, station: str | None = None) -> Run:
        """Return the run with the lowest value for ``metric``.

        ``station`` scopes the ranking; when omitted a single-station metric is
        used silently and a multi-station metric raises ``KeyError``.

        Raises
        ------
        ValueError
            Raised when the group is empty.
        KeyError
            Raised when the metric is absent, or ambiguous across stations.
        """
        return self._extreme(metric, station=station, descending=False)

    def _extreme(self, metric: str, *, station: str | None, descending: bool) -> Run:
        """Return the run holding the extreme value of a station-scoped metric."""
        from hydromodpy.results.run import Run

        if not self._sim_ids:
            raise ValueError("Empty group")
        resolved = self._resolve_metric_station(metric, station)
        placeholders = ", ".join(["?"] * len(self._sim_ids))
        query = (
            f"SELECT m.sim_id FROM metrics m "
            f"WHERE m.sim_id IN ({placeholders}) AND m.metric_name = ?"
        )
        params = self._sim_ids + [metric]
        if resolved is not None:
            query += " AND m.station_id = ?"
            params.append(resolved)
        query += f" ORDER BY m.value {'DESC' if descending else 'ASC'} LIMIT 1"
        row = self._catalog.backend.fetch_one(query, params)
        if row is None:
            raise KeyError(f"No metric '{metric}' found in group")
        return Run(str(row[0]), self._catalog)

    def sort_by(self, metric: str, ascending: bool = True) -> RunSet:
        """Return a new group ordered by one metric.

        Parameters
        ----------
        metric
            Metric name used for ordering.
        ascending
            Sort from low to high when true.

        Returns
        -------
        RunSet
            New group containing the sorted subset that has the metric.
        """
        if not self._sim_ids:
            return self
        placeholders = ", ".join(["?"] * len(self._sim_ids))
        order = "ASC" if ascending else "DESC"
        rows = self._catalog.backend.fetch_all(
            f"SELECT m.sim_id FROM metrics m "
            f"WHERE m.sim_id IN ({placeholders}) AND m.metric_name = ? "
            f"ORDER BY m.value {order}",
            self._sim_ids + [metric],
        )
        sorted_ids = [str(r[0]) for r in rows]
        return RunSet(sorted_ids, self._catalog)

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
        sims = self._catalog.backend.query(
            f"SELECT s.sim_id, s.project, sv.code AS solver, "
            f"sv.category AS solver_category, fr.code AS flow_regime, "
            f"s.n_cells, s.n_layers "
            f"FROM simulations s "
            f"JOIN solvers sv ON s.solver_id = sv.id "
            f"LEFT JOIN flow_regimes fr ON s.flow_regime_id = fr.id "
            f"WHERE s.sim_id IN ({placeholders})",
            self._sim_ids,
        )

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
        """Write ``to_dataframe()`` to a CSV file."""
        self.to_dataframe().to_csv(str(path), index=False)

    def to_xarray(self, variable: str, *, dim: str = "sim") -> xr.DataArray:
        """Return a lazy stacked ``xarray.DataArray`` of ``variable`` across sims.

        Each per-simulation Zarr store is opened via
        :meth:`Catalog.open_zarr` and assembled into an
        ``xarray.Dataset`` by :meth:`SimulationZarr.to_xarray` (dask-backed).
        Arrays are concatenated along ``dim`` whose coordinate values are
        the simulation ids. Nothing is read into memory until the caller
        materialises the array (``.compute()``, ``.values``, slicing,
        etc.). Simulations that lack the variable are skipped silently;
        if none match, an empty :class:`xarray.DataArray` is returned.

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
        for sid in progress.track(self._sim_ids, "Opening simulation stores"):
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

    # -- Filter --------------------------------------------------------------

    def filter(self, **criteria) -> RunSet:
        """Intersect with another ``catalog.find(**criteria)`` call.

        Equivalent to ``catalog.find(...)`` but restricted to this group's
        simulations. Useful for chainable exploration in notebooks.
        """
        if not self._sim_ids:
            return self
        subgroup = self._catalog.find(**criteria)
        common = [sid for sid in self._sim_ids if sid in subgroup.sim_ids]
        return RunSet(common, self._catalog)

    # -- Repr ----------------------------------------------------------------

    def __repr__(self) -> str:
        return f"RunSet(count={self.count})"

    def _repr_html_(self) -> str:
        if not self._sim_ids:
            return "<div><b>RunSet</b> <i>(empty)</i></div>"
        preview = self.to_dataframe()
        try:
            cols = [c for c in ("sim_id", "project", "solver") if c in preview.columns]
            head = preview[cols].head(10).to_html(index=False)
        except Exception:
            head = ""
        return f"<div><b>RunSet</b> ({self.count} simulations)</div>{head}"
