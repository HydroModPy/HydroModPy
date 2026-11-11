"""Tabular and time-aligned accessors for :class:`hydromodpy.results.run.view.Run`.

Mixin grouping the tabular reads (parameters, metrics, budgets, mass
balance) and the time-resolved series accessors (``timeseries``,
``observed``, ``time_index``, ``recharge_forcing``). Every row is read from
the Parquet tables of the run directory
(:mod:`hydromodpy.results.run.tables`), never from the index. The inputs a
run loaded are read from its seal (``run.record.inputs``). Mixed into
:class:`Run`; reads ``self._sim_id`` and ``self._catalog``.
"""

from __future__ import annotations

from functools import cached_property

import pandas as pd

from hydromodpy.core.scope import CATCHMENT, OBSERVED, SIMULATED
from hydromodpy.core.time.period_aggregation import naive_timestamp, period_end_stamps
from hydromodpy.core.time.selection import in_series_window
from hydromodpy.results.derive.downsample import (
    DEFAULT_TARGET_POINTS,
    lttb_downsample,
    should_downsample,
)
from hydromodpy.results.derive.time_alignment import solver_time_index
from hydromodpy.results.record.manifest import RUNTIME_VARIABLE, is_sealed
from hydromodpy.results.run.sealed import metrics_frame
from hydromodpy.results.run.tables import has_rows, read_run_table


class RunTimeseriesMixin:
    """Tabular and time-series accessors mixed into :class:`Run`."""

    @property
    def parameters(self) -> pd.DataFrame:
        """Calibratable parameters persisted for this run.

        Returns a ``DataFrame`` indexed by ``param_name`` (or by the
        ``(param_name, zone_id)`` MultiIndex when a parameter is zonal)
        with columns ``value``, ``unit``, ``parameterization``. Homogeneous
        scalars are trivially looked up via
        ``run.parameters.loc["thickness", "value"]``.
        """
        df = read_run_table(
            self,
            "parameters",
            columns=("param_name", "zone_id", "value", "unit", "parameterization"),
        )
        # Homogeneous params are stored under "catchment"; hide that column
        # from the canonical view unless zonal rows are present.
        if df.empty:
            return df.set_index("param_name")
        df = df.sort_values(["param_name", "zone_id"], na_position="first", ignore_index=True)
        is_zonal = df["zone_id"].fillna(CATCHMENT) != CATCHMENT
        if is_zonal.any():
            df["zone_id"] = df["zone_id"].fillna(CATCHMENT)
            return df.set_index(["param_name", "zone_id"])
        return df.drop(columns=["zone_id"]).set_index("param_name")

    @property
    def metrics(self) -> pd.DataFrame:
        """Every score the seal of this run records, read from ``manifest.json``.

        The runtime numbers of the solve (variable ``runtime``) are not scores.

        Returns
        -------
        pandas.DataFrame
            Long-form table: ``station``, ``variable``, ``metric``, ``value``
            and the window each score was computed on (``window_start``,
            ``window_end``, ``n_samples``, ``metric_rule_version``), then
            ``n_clipped``, the negative values a log-scale score clipped to
            zero (0 on ``nse_log`` when none, empty on a metric that never
            clips), and ``n_sim_nan``, the periods of the window a NaN
            simulated value (a dry cell) took out of the pairs. A run scored
            without a window carries no row, and a run that never completed
            has no seal and no row.
        """
        frame = metrics_frame(self._record() if is_sealed(self.dir) else None)
        return frame[frame["variable"] != RUNTIME_VARIABLE].reset_index(drop=True)

    def has_table(self, table: str) -> bool:
        """Return True when the run holds at least one row of ``table``.

        Used by the display layer to decide whether a figure can render
        before calling it, so a run that never produced (for example)
        calibration iterations reports the figure as unavailable instead of
        raising mid-render.
        """
        return has_rows(self, table)

    def stations(self, variable: str, *, source: str = SIMULATED) -> list[str]:
        """Return the sorted station ids carrying one variable, simulated by default.

        Lets a caller enumerate multi-station families (one ``reach_id`` station
        per SFR reach, gauge ids, ...) before fetching each series with
        :meth:`timeseries`. ``source="observed"`` lists the gauges that measure it.
        """
        result = read_run_table(
            self,
            "timeseries",
            where={"variable": variable, "source": source},
            columns=("station_id",),
        )
        return sorted({str(value) for value in result["station_id"]})

    def timeseries(
        self,
        variable: str,
        *,
        station: str | None = None,
        period: tuple | str | None = None,
        downsample: str | None = None,
        n_out: int | None = None,
        source: str = SIMULATED,
    ) -> pd.Series:
        """Return one time series, simulated unless ``source`` says otherwise.

        Parameters
        ----------
        variable
            Catalog variable name, such as ``"discharge"`` or ``"head"``.
        station
            Station id stored in the timeseries table. Left ``None``, it is the
            only station of the variable, or the whole catchment when it has one.
            A run with several observed piezometers or lakes stores a series for each,
            and the catchment has none for a head or a stage, so those reads need
            ``station``; the error lists the ids.
        period
            Optional window, ``(start, end)`` or a year as text (``"2002"``). It
            keeps the stress periods it overlaps, as a field or a CSV export
            reads it: a simulated value by its stamp, ``(lo, hi]``, an observation
            by its date, ``[lo, hi)``. One date reads the period that date reads.
        downsample
            Optional decimation strategy. ``"lttb"`` runs Largest Triangle
            Three Buckets on the series; ``"auto"`` enables LTTB only when
            the series exceeds 50_000 points; ``None`` (default) returns the
            untouched full-resolution series.
        n_out
            Target sample count for ``downsample="lttb"`` or ``"auto"``.
            Defaults to ``5000``.
        source
            ``"simulated"``, the default, or ``"observed"`` for the measurement
            of the same variable.

        Returns
        -------
        pandas.Series
            Time-indexed values with timezone-normalized UTC timestamps.

        Raises
        ------
        KeyError
            Raised when no matching time series exists.
        """
        if station is None:
            stations = self.stations(variable, source=source)
            if not stations:
                raise KeyError(f"No timeseries for sim={self._sim_id}, var={variable}")
            if CATCHMENT in stations:
                # A gauge series sits beside it: no station asked means the whole catchment.
                stations = [CATCHMENT]
            if len(stations) > 1:
                raise KeyError(
                    f"Variable '{variable}' has multiple stations ({', '.join(stations)}); "
                    "pass station= explicitly."
                )
            station = stations[0]
        result = read_run_table(
            self,
            "timeseries",
            where={"station_id": station, "variable": variable, "source": source},
            columns=("time", "timestep", "value"),
        ).sort_values("timestep", kind="stable")
        # The table stores instants in UTC; the simulation time_index is
        # tz-naive, so strip the tz here to keep both aligned.
        idx = _naive_utc(result["time"])
        if period is not None:
            keep = in_series_window(
                idx, observed=source == OBSERVED, period=period, edges=self.periods.edges
            )
            result, idx = result[keep], idx[keep]
        if result.empty:
            raise KeyError(
                f"No timeseries for sim={self._sim_id}, station={station}, var={variable}"
            )
        series = pd.Series(
            result["value"].to_numpy(),
            index=idx,
            name=variable,
        )
        if downsample is not None:
            series = _apply_downsample(series, mode=downsample, n_out=n_out)
        return series

    def observed(
        self,
        variable: str,
        *,
        station: str | None = None,
        period: tuple | None = None,
    ) -> pd.DataFrame:
        """Return observed timeseries ingested for this simulation.

        Observation series are persisted in the ``timeseries`` table of the run
        with ``source = observed`` (see
        :func:`hydromodpy.data.ingest.observations.ingest_observations`).

        Parameters
        ----------
        variable : str
            Canonical variable name (``discharge``, ``head``, ...).
        station : str, optional
            Station id to filter on. When ``None``, every observed station
            for ``variable`` is returned.
        period : tuple, optional
            Window ``(start, end)``, read as :meth:`timeseries` reads it for an
            observation: what falls in the periods of the window, ``[lo, hi)``.

        Returns
        -------
        pd.DataFrame
            Long-form frame with columns ``station_id``, ``datetime``,
            ``value``. Datetimes are tz-naive UTC.

        Raises
        ------
        ValueError
            When no observation rows match the filter.
        """
        where = {"variable": variable, "source": OBSERVED}
        if station is not None:
            where["station_id"] = station
        df = read_run_table(
            self, "timeseries", where=where, columns=("station_id", "timestep", "time", "value")
        )
        df = df.sort_values(["station_id", "timestep"], kind="stable", ignore_index=True)
        idx = _naive_utc(df["time"])
        if period is not None:
            keep = in_series_window(idx, observed=True, period=period, edges=self.periods.edges)
            df, idx = df[keep].reset_index(drop=True), idx[keep]
        if df.empty:
            station_msg = f", station={station}" if station is not None else ""
            raise ValueError(
                f"No observations for sim={self._sim_id}, variable={variable}{station_msg}"
            )
        return pd.DataFrame(
            {"station_id": df["station_id"], "datetime": idx, "value": df["value"].to_numpy()}
        )

    def budget(
        self,
        component: str | None = None,
        *,
        zone_id: str | None = None,
        period: tuple | str | None = None,
        steps: tuple[int, int] | None = None,
    ) -> pd.DataFrame:
        """Return water budget rows for this simulation.

        Parameters
        ----------
        component
            Optional budget component filter.
        zone_id
            Optional zone filter.
        period
            Optional window of dates, ``(start, end)`` or a year as text. It keeps the
            stress periods it overlaps, as :meth:`timeseries` does.
        steps
            Optional inclusive range of period indexes, ``(first, last)``.

        Returns
        -------
        pandas.DataFrame
            Budget rows matching the filters.
        """
        where: dict[str, str] = {}
        if component is not None:
            where["component"] = component
        if zone_id is not None:
            where["zone_id"] = zone_id
        df = read_run_table(self, "budgets", where=where)
        if period is not None:
            window = (f"{period}-01-01", f"{period}-12-31") if isinstance(period, str) else period
            df = df[df["timestep"].isin(self.periods.steps_for(period=window))]
        if steps is not None:
            df = df[(df["timestep"] >= steps[0]) & (df["timestep"] <= steps[1])]
        return df.reset_index(drop=True)

    @property
    def mass_balance(self) -> pd.DataFrame:
        """Mass-balance diagnostics ordered by timestep."""
        df = read_run_table(self, "mass_balance")
        return df.sort_values("timestep", kind="stable", ignore_index=True)

    @cached_property
    def time_index(self) -> pd.DatetimeIndex:
        """Datetime index aligned with the simulation's stress periods.

        Length matches ``run.n_timesteps``. Each stamp is the END of its
        period, as the solvers write it. The solver's CF ``/time`` axis is read
        first; without it the stamps are rebuilt from the ``period_start``,
        ``period_end`` and ``time_unit`` the run states about itself. Raises
        if the bounds are missing or the simulation has no timesteps.
        """
        row = self._load_row()
        n = row.get("n_timesteps")
        if n is None:
            raise RuntimeError(
                f"Simulation '{self._sim_id}' has no n_timesteps recorded (is it completed?)"
            )
        # Prefer the solver's persisted CF /time axis so this index matches the
        # field arrays exactly (no drift). Fall back to the period bounds of the run.
        idx = solver_time_index(self._catalog, self._sim_id, n)
        if idx is not None:
            if idx.tz is not None:
                idx = idx.tz_localize(None)
            return idx
        start, end = row.get("period_start"), row.get("period_end")
        if start is None or end is None or pd.isna(start) or pd.isna(end):
            raise RuntimeError(
                f"Simulation '{self._sim_id}' states no period_start/period_end "
                "- cannot build a time index."
            )
        return period_end_stamps(
            naive_timestamp(start), naive_timestamp(end), int(n), step_unit=row.get("time_unit")
        )

    def recharge_forcing(self) -> pd.Series:
        """Lazy input recharge forcing per stress period."""
        from hydromodpy.results.derive import views

        return views.recharge_forcing(self)


def _naive_utc(values: pd.Series) -> pd.DatetimeIndex:
    """Return a column of instants as a naive UTC index."""
    idx = pd.DatetimeIndex(pd.to_datetime(values))
    return idx.tz_convert("UTC").tz_localize(None) if idx.tz is not None else idx


def _apply_downsample(
    series: pd.Series,
    *,
    mode: str,
    n_out: int | None,
) -> pd.Series:
    """Apply the requested downsampling mode to a pandas Series.

    ``mode``:
    - ``"lttb"``: always run LTTB.
    - ``"auto"``: run LTTB only when the series exceeds the default
      threshold (50_000 points by default).
    """
    target = int(n_out) if n_out is not None else DEFAULT_TARGET_POINTS
    if mode == "lttb":
        return lttb_downsample(series, n_out=target)
    if mode == "auto":
        if should_downsample(len(series)):
            return lttb_downsample(series, n_out=target)
        return series
    raise ValueError(f"Unknown downsample mode '{mode}'. Expected 'lttb', 'auto', or None.")
