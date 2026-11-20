"""Multi-simulation view on the results catalog.

What
----
Iterable, filterable view over a list of ``sim_id`` resolved against a single
``Catalog``. Builds a pivoted ``parameters`` frame and a ``metrics`` frame
read from the seal of each run (metrics at the gauge, in the window of the
run's rule, columns named by metric), ranks runs (``best``, ``worst``,
``sort_by``), compares one metric across runs (``compare``), exports tabular
bundles (``to_dataframe``,
``to_csv``), stacks field arrays lazily into an ``xarray.DataArray``
(``to_xarray``, dask-backed), reads one location on every run
(``probe.series``) and narrows the set with ``filter(**criteria)``.

Why
---
Calibration ensembles, recipe sweeps and ad hoc cohorts are all a
"list of runs". Centralizing it here keeps the per-run loop logic
(sort, pivot, compare) in one place rather than duplicated across notebooks.

Public API
----------
- ``RunSet``: returned by ``Catalog.find`` and similar
  multi-result entry points. Iteration yields ``Run`` instances; indexing,
  ``len()``, and HTML repr are supported.

Cross-refs
----------
- ``hydromodpy.results.catalog.facade.Catalog`` is the upstream owner.
- ``hydromodpy.results.run.view.Run`` is the unit element of the group.
- ``to_xarray`` opens each per-sim Zarr lazily (dask-backed concat).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, Final

import pandas as pd

from hydromodpy.core.console import progress
from hydromodpy.core.exceptions import NothingThereError
from hydromodpy.core.scope import CATCHMENT
from hydromodpy.core.scoring.metric_table import RUN_METRIC_NAMES
from hydromodpy.results.catalog.constants import metric_sense
from hydromodpy.results.record.manifest import is_sealed
from hydromodpy.results.run.point import RunPointProvider
from hydromodpy.results.run.sealed import RULE_COLUMNS, check_one_rule, headline_metrics

if TYPE_CHECKING:
    from pathlib import Path

    import xarray as xr
    from matplotlib.figure import Figure

    from hydromodpy.results.catalog.facade import Catalog
    from hydromodpy.results.run.view import Renderer, Run


RUNSET_SHOWS: Final[tuple[str, ...]] = ("table", "figure")
"""The values of ``what`` that :meth:`RunSet.show` reads."""

_RUN_COLUMNS: Final[tuple[str, ...]] = ("name", "project", "solver")
"""Columns that name a run in :meth:`RunSet.compare`."""


def _finite(value: Any) -> bool:
    """Return whether *value* is a finite number."""
    return isinstance(value, (int, float)) and math.isfinite(value)


def rank_key(metric: str) -> Callable[[float], float]:
    """Return the key that puts the best value of ``metric`` lowest.

    The direction is :func:`~hydromodpy.results.catalog.constants.metric_sense`:
    ``max`` and ``min`` rank the value, ``zero`` and ``one`` its distance to
    that target. A metric without a direction, or under a retired name, is
    refused: best would be undefined.
    """
    sense = metric_sense(metric)
    if sense == "max":
        return lambda value: -value
    if sense == "min":
        return lambda value: value
    target = 0.0 if sense == "zero" else 1.0
    return lambda value: abs(value - target)


def stack_fields(
    catalog: Catalog, sim_ids: list[str], fields: list[str], *, dim: str
) -> dict[str, xr.DataArray]:
    """Stack each of ``fields`` lazily across the runs ``sim_ids`` along ``dim``.

    Each Zarr store is opened once by :meth:`SimulationZarr.to_xarray`
    (dask-backed) and CF-decoded. A run whose store cannot be opened is
    skipped with a warning, a run without a field is skipped for that field,
    and a field no run holds is left out of the result.
    """
    import xarray as xr

    from hydromodpy.core.logging import get_logger

    arrays: dict[str, list[xr.DataArray]] = {name: [] for name in fields}
    holders: dict[str, list[str]] = {name: [] for name in fields}
    for sid in progress.track(sim_ids, "Opening simulation stores"):
        try:
            ds = xr.decode_cf(catalog.open_zarr(sid).to_xarray(), decode_times=True)
        except (KeyError, FileNotFoundError, OSError) as exc:
            get_logger(__name__).warning("Cannot open Zarr store for sim %s: %s", sid, exc)
            continue
        for name in fields:
            if name in ds.data_vars:
                arrays[name].append(ds[name])
                holders[name].append(sid)
    return {
        name: xr.concat(
            arrays[name],
            dim=dim,
            combine_attrs="drop_conflicts",
            coords="minimal",
            compat="override",
        ).assign_coords({dim: holders[name]})
        for name in fields
        if arrays[name]
    }


class RunSet:
    """Collection view over several simulations from one catalog.

    ``RunSet`` is returned by catalog queries that match more than one
    run. It behaves like a lightweight list of ``Run`` objects and adds cohort
    utilities: pivot parameter tables, read the metrics of each run under its
    rule, rank runs, compare one metric, export a wide DataFrame, and stack
    fields lazily. Runs scored under different rules (station, variable,
    window, rule version) are not ranked together unless asked
    (``mixed_windows=True``).

    Parameters
    ----------
    sim_ids
        Ordered simulation ids in the group.
    catalog
        Catalog used to resolve ids into ``Run`` objects and tabular data.
    render
        The function that draws a figure of the set. Without one the set takes
        the one of its catalog, and ``figure`` is refused when there is none.

    Examples
    --------
    >>> group = catalog.find(project="my_project")  # doctest: +SKIP
    >>> group.count  # doctest: +SKIP
    >>> group.best("nse").summary()  # doctest: +SKIP

    See Also
    --------
    hydromodpy.results.run.view.Run
        Per-simulation view yielded during iteration.
    hydromodpy.results.catalog.facade.Catalog
        Catalog that creates simulation groups.
    """

    def __init__(
        self,
        sim_ids: list[str],
        catalog: Catalog,
        *,
        render: Renderer | None = None,
    ) -> None:
        self._sim_ids = sim_ids
        self._catalog_handle = catalog
        self._render = render if render is not None else getattr(catalog, "render", None)
        self._score_rows: dict[str, dict[str, Any]] = {}
        self.probe = RunPointProvider(self)

    @property
    def _catalog(self) -> Catalog:
        """The catalog the group reads through, reopened if its owner closed it."""
        from hydromodpy.results.run.view import live_catalog

        self._catalog_handle = live_catalog(self._catalog_handle)
        return self._catalog_handle

    def _iter_runs(self):
        """Runs of the group, so ``probe`` serves a set exactly like one run."""
        return iter(self)

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
        from hydromodpy.results.run.view import Run

        for sid in self._sim_ids:
            yield Run(sid, self._catalog)

    def __getitem__(self, index: int) -> Run:
        from hydromodpy.results.run.view import Run

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
            df["zone_id"] == CATCHMENT,
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
        """One row per run: its metrics at the gauge, in the window of its rule.

        Columns: ``sim_id``, ``station`` and ``variable`` of the headline NSE,
        the window it was computed on (``window_start``, ``window_end``,
        ``n_samples``, ``metric_rule_version``), then one column per metric, named
        by the metric alone (``nse``, ``kge``, ``rmse`` ...). The scores come
        from each run's ``manifest.json``. A run without a seal, without a
        window or without a station has empty cells.
        """
        if not self._sim_ids:
            return pd.DataFrame()
        rows = [{"sim_id": sid, **self._scores(sid)} for sid in self._sim_ids]
        frame = pd.DataFrame(rows)
        leading = ["sim_id", *RULE_COLUMNS]
        known = [name for name in RUN_METRIC_NAMES if name in frame.columns]
        others = sorted(set(frame.columns) - set(leading) - set(known) - set(_RUN_COLUMNS))
        return frame[[*leading, *known, *others]]

    def _scores(self, sim_id: str) -> dict[str, Any]:
        """The headline metrics of one run, plus its name, project and solver, read once."""
        cached = self._score_rows.get(sim_id)
        if cached is not None:
            return cached
        from hydromodpy.results.run.view import Run

        run = Run(sim_id, self._catalog)
        row: dict[str, Any] = dict.fromkeys(RULE_COLUMNS)
        if is_sealed(run.dir):
            record = run._record()  # noqa: SLF001 - same package
            row = {
                "name": record.run.name,
                "project": record.run.project,
                "solver": record.run.solver,
                **headline_metrics(record),
            }
        self._score_rows[sim_id] = row
        return row

    # -- Comparison ----------------------------------------------------------

    def _scored(self, metric: str, *, mixed_windows: bool) -> pd.DataFrame:
        """Rows of the group that carry a finite ``metric``, under one rule.

        Runs scored at different stations, on different variables, on
        different windows or under different rule versions are not comparable:
        they are refused unless ``mixed_windows`` is true.
        """
        described = (*_RUN_COLUMNS, *RULE_COLUMNS)
        rows: list[dict[str, Any]] = []
        for sid in self._sim_ids:
            scores = self._scores(sid)
            if _finite(scores.get(metric)):
                rows.append(
                    {
                        "sim_id": sid,
                        **{column: scores.get(column) for column in described},
                        "value": scores[metric],
                    }
                )
        frame = pd.DataFrame(rows, columns=["sim_id", *described, "value"])
        if not mixed_windows:
            check_one_rule(
                rows,
                metric,
                names=[str(row["sim_id"])[:8] for row in rows],
            )
        return frame

    def compare(self, metric: str, *, mixed_windows: bool = False) -> pd.DataFrame:
        """Compare one metric across the runs of the group, best first.

        The metric is read at the gauge of each run, in the window of its rule
        (:attr:`metrics`). Best follows the direction of the metric.

        Parameters
        ----------
        metric
            Metric name, as in the columns of :attr:`metrics`.
        mixed_windows
            Rank runs scored under different rules: another station, variable,
            window or rule version. Refused by default: such values are not
            comparable.

        Returns
        -------
        pandas.DataFrame
            ``sim_id``, ``name``, ``project``, ``solver``, ``station``,
            ``variable``, the window columns and ``value``, best first. Runs
            without the metric are left out.
        """
        if not self._sim_ids:
            return pd.DataFrame()
        return self._ranked(metric, best=True, mixed_windows=mixed_windows)

    def best(self, metric: str, *, mixed_windows: bool = False) -> Run:
        """Return the run with the best value for ``metric``.

        Best follows the direction of the metric: the highest ``nse``, the
        lowest ``rmse``, the ``pbias`` closest to zero. The metric is read at
        the gauge of each run, in the window of its rule.

        Raises
        ------
        ValueError
            Raised when the group is empty, or when the metric has no declared
            direction (:class:`~hydromodpy.results.catalog.constants.UnrankedMetricError`).
        MixedWindowsError
            Raised when the runs were scored under different rules (station,
            variable, window or rule version) and ``mixed_windows`` is false.
        KeyError
            Raised when no run of the group carries the metric, for instance
            when no run declares a ``[metrics] window``.
        """
        return self._extreme(metric, best=True, mixed_windows=mixed_windows)

    def worst(self, metric: str, *, mixed_windows: bool = False) -> Run:
        """Return the run with the worst value for ``metric``.

        The mirror of :meth:`best`, with the same direction rule and errors.
        """
        return self._extreme(metric, best=False, mixed_windows=mixed_windows)

    def _ranked(self, metric: str, *, best: bool, mixed_windows: bool) -> pd.DataFrame:
        """Rows carrying ``metric``, best (or worst) first."""
        key = rank_key(metric)
        frame = self._scored(metric, mixed_windows=mixed_windows)
        order = frame["value"].map(key).sort_values(ascending=best, kind="stable").index
        return frame.loc[order].reset_index(drop=True)

    def _extreme(self, metric: str, *, best: bool, mixed_windows: bool) -> Run:
        """Return the run holding the best or worst value of ``metric``."""
        from hydromodpy.results.run.view import Run

        if not self._sim_ids:
            raise ValueError("Empty group")
        ranked = self._ranked(metric, best=best, mixed_windows=mixed_windows)
        if ranked.empty:
            raise KeyError(
                f"No run of the group carries '{metric}'. A run is scored only on its "
                "[metrics] window: a run without one has no score."
            )
        return Run(str(ranked["sim_id"].iloc[0]), self._catalog)

    def sort_by(
        self, metric: str, *, ascending: bool = True, mixed_windows: bool = False
    ) -> RunSet:
        """Return a new group ordered by the raw value of one metric.

        Parameters
        ----------
        metric
            Metric name, as in the columns of :attr:`metrics`.
        ascending
            Sort from low to high when true.
        mixed_windows
            Order runs scored under different rules. Refused by default.

        Returns
        -------
        RunSet
            New group containing the sorted subset that has the metric.
        """
        if not self._sim_ids:
            return self
        frame = self._scored(metric, mixed_windows=mixed_windows)
        ordered = frame.sort_values("value", ascending=ascending, kind="stable")
        return RunSet([str(sid) for sid in ordered["sim_id"]], self._catalog)

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

    def table(self, name: str) -> pd.DataFrame:
        """Return the table *name* of the set: ``parameters``, ``metrics`` or ``runs``.

        ``parameters`` is :attr:`parameters`, ``metrics`` is :attr:`metrics` and
        ``runs`` is :meth:`to_dataframe` with every column. Any other name is
        refused with these three.
        """
        if name == "parameters":
            return self.parameters
        if name == "metrics":
            return self.metrics
        if name == "runs":
            return self.to_dataframe()
        raise NothingThereError(
            f"A set of runs holds the tables parameters, metrics and runs, not {name!r}."
        )

    def figure(
        self,
        name: str | None = None,
        *,
        request: Mapping[str, Any] | None = None,
        draw: Callable[..., Any] | None = None,
        save: str | Path | None = None,
        dpi: int | None = None,
        theme: str | None = None,
        engine: str | None = None,
        time: str | None = None,
        data: bool = False,
        **options: Any,
    ) -> Figure | Path | dict[str, Any]:
        """Draw the registered ``runset`` figure *name* of this set, ``ensemble_band`` for one.

        The arguments are those of :meth:`hydromodpy.results.run.view.Run.figure`.
        A figure of another subject refuses the set.

        Raises
        ------
        hydromodpy.core.exceptions.CommandUsageError
            If the set was not opened by ``hydromodpy.open`` or a project.
        """
        from hydromodpy.results.run.view import figure_of

        return figure_of(
            self,
            name,
            request,
            {
                **options,
                "draw": draw,
                "save": save,
                "dpi": dpi,
                "theme": theme,
                "engine": engine,
                "time": time,
            },
            data=data,
        )

    def show(self, what: str, **options: Any) -> Any:
        """Read one thing of this set: ``table`` or ``figure``."""
        from hydromodpy.results.run.view import show_of

        return show_of(self, what, options, RUNSET_SHOWS)

    def to_csv(self, path: Path | str) -> None:
        """Write ``to_dataframe()`` to a CSV file."""
        self.to_dataframe().to_csv(str(path), index=False)

    def to_xarray(self, variable: str, *, dim: str = "run") -> xr.DataArray:
        """Return a lazy stacked ``xarray.DataArray`` of ``variable`` across sims.

        Each per-simulation Zarr store is opened via
        :meth:`Catalog.open_zarr` and assembled into an
        ``xarray.Dataset`` by :meth:`SimulationZarr.to_xarray` (dask-backed).
        Arrays are concatenated along ``dim`` whose coordinate values are
        the simulation ids. Nothing is read into memory until the caller
        materializes the array (``.compute()``, ``.values``, slicing,
        etc.). Simulations that lack the variable are skipped, a store
        that cannot be opened with a warning; if none match, an empty
        :class:`xarray.DataArray` is returned.

        Parameters
        ----------
        variable
            Public field name (as declared in the
            :mod:`hydromodpy.results.field_registry`).
        dim
            Name of the new stacking dimension (default ``"sim"``).
        """
        import xarray as xr

        stacked = stack_fields(self._catalog, self._sim_ids, [variable], dim=dim).get(variable)
        if stacked is None:
            return xr.DataArray(name=variable)
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
