"""Tabular and time-aligned accessors for :class:`hydromodpy.results.run.Run`.

Mixin grouping the catalog-backed tabular reads (parameters, metrics,
budgets, mass balance, provenance) and the time-resolved series accessors
(``timeseries``, ``observed``, ``time_index``, ``recharge_forcing``).
Mixed into :class:`Run`; reads ``self._sim_id`` and ``self._catalog``.
"""

from __future__ import annotations

from functools import cached_property

import pandas as pd

from hydromodpy.results.time_alignment import solver_time_index
from hydromodpy.results.timeseries_downsample import (
    DEFAULT_TARGET_POINTS,
    lttb_downsample,
    should_downsample,
)


class RunTimeseriesMixin:
    """Tabular and time-series accessors mixed into :class:`Run`."""

    @property
    def parameters(self) -> pd.DataFrame:
        """Calibratable parameters persisted for this run.

        Returns a ``DataFrame`` indexed by ``param_name`` (or by the
        ``(param_name, zone_id)`` MultiIndex when a parameter is zonal)
        with columns ``value``, ``unit``, ``parameterization``. Homogeneous
        scalars are trivially looked up via
        ``sim.parameters.loc["thickness", "value"]``.
        """
        df = self._catalog.backend.query(
            "SELECT param_name, zone_id, value, unit, parameterization "
            "FROM parameters WHERE sim_id = ? ORDER BY param_name, zone_id",
            [self._sim_id],
        )
        # Homogeneous params have zone_id=NULL in the DB (stored as
        # "__global__" by the writer); hide that column from the canonical
        # view unless zonal rows are present.
        if df.empty:
            return df.set_index("param_name")
        is_zonal = df["zone_id"].fillna("__global__") != "__global__"
        if is_zonal.any():
            df["zone_id"] = df["zone_id"].fillna("__global__")
            return df.set_index(["param_name", "zone_id"])
        return df.drop(columns=["zone_id"]).set_index("param_name")

    @property
    def metrics(self) -> pd.DataFrame:
        """Performance and diagnostic metrics recorded for this run.

        Returns
        -------
        pandas.DataFrame
            Long-form table with ``station_id``, ``metric_name``, and ``value``.
        """
        return self._catalog.backend.query(
            "SELECT station_id, metric_name, value "
            "FROM metrics WHERE sim_id = ? ORDER BY station_id, metric_name",
            [self._sim_id],
        )

    @property
    def provenance(self) -> pd.DataFrame:
        """Input-data provenance rows consumed by this run.

        Returns
        -------
        pandas.DataFrame
            Long-form table with source references, checksums, periods, and
            record counts.
        """
        return self._catalog.backend.query(
            "SELECT variable, source_type, source_ref, "
            "payload_sha256 AS checksum, "
            "period_start, period_end, n_records "
            "FROM provenance WHERE sim_id = ?",
            [self._sim_id],
        )

    def stations(self, variable: str) -> list[str]:
        """Return the sorted station ids carrying one simulated variable.

        Lets a caller enumerate multi-station families (one ``sfr:<net>:<reach>``
        station per SFR reach, gauge ids, ...) before fetching each series with
        :meth:`timeseries`.
        """
        result = self._catalog.backend.query(
            "SELECT DISTINCT station_id FROM timeseries WHERE sim_id = ? AND variable = ?",
            [self._sim_id, variable],
        )
        return sorted(str(value) for value in result["station_id"])

    def timeseries(
        self,
        variable: str,
        *,
        station: str | None = None,
        period: tuple | str | None = None,
        downsample: str | None = None,
        n_out: int | None = None,
    ) -> pd.Series:
        """Return one simulated time series.

        Parameters
        ----------
        variable
            Catalog variable name, such as ``"discharge"`` or ``"head"``.
        station
            Station id stored in the timeseries table. When the variable has
            a single station, this can be left ``None``.
        period
            Optional ``(start, end)`` datetime bounds, or a single ``"YYYY"``
            year string applied as ``("YYYY-01-01", "YYYY-12-31")``.
        downsample
            Optional decimation strategy. ``"lttb"`` runs Largest Triangle
            Three Buckets on the series; ``"auto"`` enables LTTB only when
            the series exceeds 50_000 points; ``None`` (default) returns the
            untouched full-resolution series.
        n_out
            Target sample count for ``downsample="lttb"`` or ``"auto"``.
            Defaults to ``5000``.

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
            stations = self._catalog.backend.query(
                "SELECT DISTINCT station_id FROM timeseries WHERE sim_id = ? AND variable = ?",
                [self._sim_id, variable],
            )
            if stations.empty:
                raise KeyError(f"No timeseries for sim={self._sim_id}, var={variable}")
            if len(stations) > 1:
                names = ", ".join(sorted(stations["station_id"].astype(str)))
                raise KeyError(
                    f"Variable '{variable}' has multiple stations ({names}); "
                    "pass station= explicitly."
                )
            station = str(stations["station_id"].iloc[0])
        if isinstance(period, str):
            period = (f"{period}-01-01", f"{period}-12-31")
        query = (
            "SELECT time, timestep, value FROM timeseries "
            "WHERE sim_id = ? AND station_id = ? AND variable = ?"
        )
        params: list = [self._sim_id, station, variable]
        if period is not None:
            query += " AND time >= ? AND time <= ?"
            params.extend([period[0], period[1]])
        query += " ORDER BY timestep"
        result = self._catalog.backend.query(query, params)
        if result.empty:
            raise KeyError(
                f"No timeseries for sim={self._sim_id}, station={station}, var={variable}"
            )
        # The catalog stores datetimes as TIMESTAMPTZ (UTC); simulation
        # time_index is tz-naive, so strip the tz here to keep both aligned.
        idx = pd.DatetimeIndex(result["time"])
        if idx.tz is not None:
            idx = idx.tz_convert("UTC").tz_localize(None)
        series = pd.Series(
            result["value"].values,
            index=idx,
            name=variable,
        )
        if downsample is not None:
            series = _apply_downsample(series, mode=downsample, n_out=n_out)
        return series

    def observed(
        self,
        variable: str,
        station: str | None = None,
        period: tuple | None = None,
    ) -> pd.DataFrame:
        """Return observed timeseries ingested for this simulation.

        Observation series are persisted in the catalog ``timeseries`` table
        with an ``_obs`` suffix on the variable name (see
        :func:`hydromodpy.simulation.extraction.derivation.observation_ingest.ingest_observations`).
        This accessor strips that suffix on read so callers query with the
        canonical variable name (``discharge``, ``head``, ...).

        Parameters
        ----------
        variable : str
            Canonical variable name (no ``_obs`` suffix).
        station : str, optional
            Station id to filter on. When ``None``, every observed station
            for ``variable`` is returned.
        period : tuple, optional
            ``(start, end)`` datetime bounds, inclusive on both ends.

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
        obs_variable = f"{variable}_obs"
        query = (
            "SELECT station_id, time AS datetime, value FROM timeseries "
            "WHERE sim_id = ? AND variable = ?"
        )
        params: list = [self._sim_id, obs_variable]
        if station is not None:
            query += " AND station_id = ?"
            params.append(station)
        if period is not None:
            query += " AND time >= ? AND time <= ?"
            params.extend([period[0], period[1]])
        query += " ORDER BY station_id, timestep"
        df = self._catalog.backend.query(query, params)
        if df.empty:
            station_msg = f", station={station}" if station is not None else ""
            raise ValueError(
                f"No observations for sim={self._sim_id}, variable={variable}{station_msg}"
            )
        idx = pd.DatetimeIndex(df["datetime"])
        if idx.tz is not None:
            idx = idx.tz_convert("UTC").tz_localize(None)
        df["datetime"] = idx
        return df

    def budget(
        self,
        component: str | None = None,
        zone_id: str | None = None,
        period: tuple[int, int] | None = None,
    ) -> pd.DataFrame:
        """Return water budget rows for this simulation.

        Parameters
        ----------
        component
            Optional budget component filter.
        zone_id
            Optional zone filter.
        period
            Optional inclusive timestep range ``(start, end)``.

        Returns
        -------
        pandas.DataFrame
            Budget rows matching the filters.
        """
        query = "SELECT * FROM budgets WHERE sim_id = ?"
        params: list = [self._sim_id]
        if component is not None:
            query += " AND component = ?"
            params.append(component)
        if zone_id is not None:
            query += " AND zone_id = ?"
            params.append(zone_id)
        if period is not None:
            query += " AND timestep >= ? AND timestep <= ?"
            params.extend(period)
        return self._catalog.backend.query(query, params)

    @property
    def mass_balance(self) -> pd.DataFrame:
        """Mass-balance diagnostics ordered by timestep."""
        return self._catalog.backend.query(
            "SELECT * FROM mass_balance WHERE sim_id = ? ORDER BY timestep",
            [self._sim_id],
        )

    @cached_property
    def time_index(self) -> pd.DatetimeIndex:
        """Datetime index aligned with the simulation's stress periods.

        Length matches ``run.n_timesteps``. Uses ``period_start`` and
        ``period_end`` stored in the catalog; raises if either is
        missing or the simulation has no timesteps.
        """
        row = self._load_row()
        n = row.get("n_timesteps")
        if n is None:
            raise RuntimeError(
                f"Simulation '{self._sim_id}' has no n_timesteps recorded (is it completed?)"
            )
        # Prefer the solver's persisted CF /time axis so this index matches the
        # field arrays exactly (no drift). Fall back to the catalog period bounds.
        idx = solver_time_index(self._catalog, self._sim_id, n)
        if idx is not None:
            if idx.tz is not None:
                idx = idx.tz_localize(None)
            return idx
        start, end = row.get("period_start"), row.get("period_end")
        if start is None or end is None or pd.isna(start) or pd.isna(end):
            raise RuntimeError(
                f"Simulation '{self._sim_id}' missing period_start/period_end "
                "in catalog - cannot build a time index."
            )
        idx = pd.date_range(start=start, end=end, periods=n)
        if idx.tz is not None:
            idx = idx.tz_localize(None)
        return idx

    @cached_property
    def params(self) -> dict[str, float]:
        """Mapping of global (non-zonal) parameter values to scalar floats.

        Shortcut for the common case; for zonal parameters use the full
        ``run.parameters`` DataFrame (MultiIndex on ``param_name`` and
        ``zone_id``).
        """
        rows = self._catalog.backend.fetch_all(
            "SELECT param_name, value FROM parameters "
            "WHERE sim_id = ? AND (zone_id IS NULL OR zone_id = ?)",
            [self._sim_id, "__global__"],
        )
        return {name: float(val) for name, val in rows}

    def recharge_forcing(self) -> pd.Series:
        """Lazy input recharge forcing per stress period."""
        from hydromodpy.results import views

        return views.recharge_forcing(self)

    def input_entries(self) -> pd.DataFrame:
        """Return cache entries consumed by this run via the SHA-256 bridge.

        Joins ``tracked_files`` (in the project catalog) with
        ``entries`` (in the workspace cache DB) on ``sha256`` through a
        DuckDB ATTACH read-only context. Returns an empty DataFrame when
        the cache DB cannot be located next to the workspace or when no
        tracked file matches a cache entry.
        """
        from hydromodpy.results.catalog.cross_db import run_input_entries

        return run_input_entries(self._catalog, self._sim_id)


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
