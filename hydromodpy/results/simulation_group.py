"""Multi-simulation view on the results catalog.

What
----
Iterable, filterable view over a list of ``sim_id`` resolved against a single
``SimulationCatalog``. Builds pivoted ``parameters`` and ``metrics`` frames,
ranks runs (``best``, ``worst``, ``sort_by``), compares scalar metrics across
simulations (``compare``), exports tabular bundles (``to_dataframe``,
``to_csv``), stacks field arrays into an ``xarray.DataArray``
(``to_xarray``), and narrows the set with ``filter(**criteria)``.

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
- ``to_xarray`` defers to per-run ``Run.field`` reads.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from pathlib import Path

    from hydromodpy.results.catalog import SimulationCatalog
    from hydromodpy.results.run import Run


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

    def to_xarray(self, variable: str, *, dim: str = "sim"):
        """Return a stacked :class:`xarray.DataArray` of ``variable`` across sims.

        Every simulation in the group is opened, its
        :meth:`SimulationZarr.to_xarray` dataset is queried for ``variable``,
        and the results are concatenated along a new ``dim`` whose coordinate
        values are the simulation ids. Simulations that do not carry the
        variable are skipped with a warning; if none match, an empty
        ``xarray.DataArray`` is returned.

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
            sz = self._catalog.open_zarr(sid)
            try:
                ds = sz.to_xarray()
            finally:
                sz.close()
            if variable not in ds.data_vars:
                continue
            arrays.append(ds[variable])
            sim_ids.append(sid)

        if not arrays:
            return xr.DataArray(name=variable)
        stacked = xr.concat(arrays, dim=dim)
        stacked = stacked.assign_coords({dim: sim_ids})
        stacked.name = variable
        return stacked

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
