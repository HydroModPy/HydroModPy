"""Time alignment helpers for observed and simulated series."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pandas as pd

from hydromodpy.core.time.period_aggregation import observed_on_periods
from hydromodpy.core.time.time_method import (
    DEFAULT_TIME_METHOD,
    OBSERVABLE_TIME_METHODS,
    TimeMethod,
    bare_observable_name,
    time_method_from_cell_methods,
)
from hydromodpy.results.field_registry import FIELD_REGISTRY


def solver_time_index(catalog: Any, sim_id: Any, n_timesteps: int) -> pd.DatetimeIndex | None:
    """Return the solver's CF ``/time`` axis as a tz-naive ``DatetimeIndex``.

    This is the exact stress-period clock the solver persisted, shared by every
    field array. Reusing it keeps derived/aggregated series (e.g. the catchment
    discharge) on the same clock as the native solver series instead of
    re-deriving a drifting ``date_range(..., periods=n)``.

    Returns ``None`` when the axis is unavailable or its length does not match
    ``n_timesteps`` so the caller can fall back.
    """
    opener = getattr(catalog, "open_zarr", None)
    if not callable(opener):
        return None
    try:
        with opener(sim_id) as store_zarr:
            times = store_zarr.read_time()
    except Exception:
        return None
    if times is None or len(times) != int(n_timesteps):
        return None
    return pd.DatetimeIndex(times)


def normalize_datetime_series(series: pd.Series) -> pd.Series:
    """Return a float series sorted on a tz-naive UTC DatetimeIndex."""
    if series.empty:
        return series.astype(float)
    idx = pd.DatetimeIndex(series.index)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    out = pd.Series(series.astype(float).to_numpy(), index=idx, name=series.name)
    return out.sort_index()


def normalize_period_bounds(period: tuple | str) -> tuple[Any, Any, bool]:
    """Return ``(lo, hi, hi_inclusive)`` tz-aware UTC bounds for a query period.

    Timeseries ``time`` is stored as UTC-aware TIMESTAMPTZ, so the caller's
    bounds must be normalized to UTC to keep the comparison stable regardless of
    DuckDB's session timezone. A ``(start, end)`` pair keeps the historical
    inclusive upper bound (``hi_inclusive=True``). A single ``"YYYY"`` string
    expands to the half-open calendar year ``[YYYY-01-01, (YYYY+1)-01-01)`` with
    an exclusive upper bound so sub-daily 31 December samples are not dropped.
    """
    if isinstance(period, str):
        year = int(period)
        lo = pd.Timestamp(year=year, month=1, day=1, tz="UTC")
        hi = pd.Timestamp(year=year + 1, month=1, day=1, tz="UTC")
        return lo.to_pydatetime(), hi.to_pydatetime(), False
    lo = pd.Timestamp(period[0])
    hi = pd.Timestamp(period[1])
    lo = lo.tz_localize("UTC") if lo.tz is None else lo.tz_convert("UTC")
    hi = hi.tz_localize("UTC") if hi.tz is None else hi.tz_convert("UTC")
    return lo.to_pydatetime(), hi.to_pydatetime(), True


def time_method_for(variable: str | None) -> TimeMethod:
    """Return how a series named ``variable`` relates to its end stamps.

    The field registry is read first: its CF ``cell_methods`` says ``time:
    point`` for a state (head, water table, concentration) and ``time: mean``
    for a flux. A name the registry does not hold is looked up in
    :data:`hydromodpy.core.time.time_method.OBSERVABLE_TIME_METHODS`, which
    names the calibration variables and the observed families: ``discharge``
    is ``"mean"``, ``lake_level`` and ``stage`` are ``"point"``. Any other name
    is ``"mean"``, the rule a discharge is scored on. The ``_obs`` suffix of an
    ingested observation is ignored.
    """
    name = bare_observable_name(variable)
    descriptor = FIELD_REGISTRY.get(name)
    if descriptor is not None:
        return time_method_from_cell_methods(descriptor.cell_methods)
    return OBSERVABLE_TIME_METHODS.get(name, DEFAULT_TIME_METHOD)


def first_period_start(stamps: Any, boundaries: Sequence[Any] | None) -> pd.Timestamp | None:
    """Return the start of the period that ends at the first of ``stamps``.

    ``boundaries`` are the run's time-grid bounds, or the catalog
    ``period_start`` alone. The answer is the last bound strictly before the
    first stamp, so a series cut to its last period still gets that period's
    own start. ``None`` when no bound precedes the first stamp.
    """
    if boundaries is None or len(boundaries) == 0 or stamps is None or len(stamps) == 0:
        return None
    first = _naive_utc(pd.DatetimeIndex(stamps).min())
    bounds = sorted(_naive_utc(bound) for bound in boundaries if not pd.isna(bound))
    before = [bound for bound in bounds if bound < first]
    return before[-1] if before else None


def run_period_start(run: Any, stamps: Any) -> pd.Timestamp | None:
    """Return the start of a stored run's first period, from its catalog row.

    ``None`` when the run has no catalog row, no ``period_start``, or one that
    does not precede the first of ``stamps``.
    """
    loader = getattr(run, "_load_row", None)
    if not callable(loader):
        return None
    try:
        start = loader().get("period_start")
    except Exception:
        # A figure drawn from a run without a catalog row falls back on the
        # period inferred from the stamps; nothing is lost but the first edge.
        return None
    if start is None or pd.isna(start):
        return None
    return first_period_start(stamps, [start])


def _naive_utc(value: Any) -> pd.Timestamp:
    """Return one timestamp, tz-naive in UTC."""
    ts = pd.Timestamp(value)
    return ts.tz_convert("UTC").tz_localize(None) if ts.tz is not None else ts


def observed_on_simulation_index(
    observed: pd.Series,
    simulation_index: pd.DatetimeIndex,
    *,
    method: str = DEFAULT_TIME_METHOD,
    start: Any = None,
    tolerance: pd.Timedelta | pd.DateOffset | None = None,
) -> pd.Series:
    """Put an observation chronicle on the stress periods of a run.

    A simulation stamp is the END of its period and an observation is stamped
    at the START of what it averages. ``method`` says what the simulated value
    is, and :func:`time_method_for` gives it for a variable name:

    - ``"mean"``, a quantity averaged over the period (a discharge, a drain
      flux, a runoff forcing). Every period ``[s, e)`` takes the mean of the
      observations stamped in it; a period holding none takes the last
      observation before ``s`` when that observation's interval covers the
      period (a monthly mean on a daily run). ``tolerance`` is the interval of
      one observation, by default the step of the chronicle. ``start`` is the
      start of the first period; without it the first period is inferred from
      the spacing of the stamps, and a single stamp takes the mean of the whole
      chronicle.
    - ``"point"``, a state at the stamp instant (a head, a lake stage). A
      finer chronicle is averaged on a window centred on the stamp, a coarser
      or same-frequency one gives its nearest sample within ``tolerance``.

    The rules are written once, in
    :func:`hydromodpy.core.time.period_aggregation.observed_on_periods`. The
    default ``"mean"`` is the method of a name nothing declares; every
    internal caller passes the method of the variable it aligns.

    A caller aligning a FORCING rather than an observation chronicle should
    call ``period_mean_on_index`` itself, the way
    :func:`hydromodpy.calibration.metrics.series.add_runoff_to_discharge` does:
    a forcing that misses a period is a gap, not the previous value.
    """
    obs = normalize_datetime_series(observed).dropna()
    sim_index = pd.DatetimeIndex(simulation_index)
    if sim_index.tz is not None:
        sim_index = sim_index.tz_convert("UTC").tz_localize(None)
    sim_index = sim_index.sort_values()
    aligned = observed_on_periods(obs, sim_index, method=method, start=start, tolerance=tolerance)
    return aligned.rename(observed.name)


def align_observed_simulated(
    observed: pd.Series,
    simulated: pd.Series,
    *,
    method: str = DEFAULT_TIME_METHOD,
    dropna: bool = True,
    start: Any = None,
) -> pd.DataFrame:
    """Return observed and simulated values aligned on simulation timestamps.

    ``method`` and ``start`` are passed on to
    :func:`observed_on_simulation_index`.
    """
    sim = normalize_datetime_series(simulated).dropna()
    if sim.empty:
        return pd.DataFrame(columns=["obs", "sim"])
    sim.index = pd.DatetimeIndex(sim.index).as_unit("ns")
    obs_aligned = observed_on_simulation_index(
        observed, pd.DatetimeIndex(sim.index), method=method, start=start
    )
    paired = pd.DataFrame({"obs": obs_aligned, "sim": sim.reindex(obs_aligned.index)})
    return paired.dropna() if dropna else paired


__all__ = [
    "align_observed_simulated",
    "first_period_start",
    "normalize_datetime_series",
    "observed_on_simulation_index",
    "run_period_start",
    "time_method_for",
]
