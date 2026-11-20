"""Time alignment helpers for observed and simulated series."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pandas as pd

from hydromodpy.core.time.period_aggregation import (
    naive_timestamp,
    observed_on_periods,
    period_edges,
)
from hydromodpy.core.time.time_method import (
    DEFAULT_TIME_METHOD,
    OBSERVABLE_TIME_METHODS,
    TimeMethod,
    time_method_from_cell_methods,
)
from hydromodpy.results.field_registry import FIELD_REGISTRY, TIME_SERIES_REGISTRY
from hydromodpy.results.metric_rule import DateWindow


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


def time_method_for(variable: str | None) -> TimeMethod:
    """Return how a series named ``variable`` relates to its end stamps.

    The field registry is read first: its CF ``cell_methods`` says ``time:
    point`` for a state (head, water table, concentration) and ``time: mean``
    for a flux. A name the registry does not hold is looked up in
    :data:`hydromodpy.core.time.time_method.OBSERVABLE_TIME_METHODS`, which
    names the calibration variables and the observed families: ``discharge``
    is ``"mean"``, ``lake_level`` and ``stage`` are ``"point"``. Any other name
    is ``"mean"``, the rule a discharge is scored on.
    """
    name = str(variable or "").strip()
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
    first = naive_timestamp(pd.DatetimeIndex(stamps).min())
    bounds = sorted(naive_timestamp(bound) for bound in boundaries if not pd.isna(bound))
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


NO_TIME_AXIS = (AttributeError, KeyError, ValueError, FileNotFoundError, RuntimeError)
"""What a run without a time axis raises when its periods are asked for."""


def run_period_edges(run: Any) -> pd.DatetimeIndex | None:
    """Return the ``n + 1`` period edges of a run, or None when it carries no dates.

    The edges the catalog places on the calendar, else the ones the end stamps
    imply, as a trial reads a stack served without its time grid.
    """
    try:
        edges = run.periods.edges
    except NO_TIME_AXIS:
        edges = None
    if edges is not None and len(edges) >= 2:
        return pd.DatetimeIndex(edges)
    try:
        stamps = run.time_index
    except NO_TIME_AXIS:
        return None
    if stamps is None or len(stamps) < 2:
        return None
    return period_edges(stamps)


def run_period(run: Any) -> DateWindow | None:
    """Return the simulated period of a run as a date window, or None when it has no dates."""
    edges = run_period_edges(run)
    if edges is None:
        return None
    return DateWindow(start=edges[0].date(), end=edges[-1].date())


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
      finer chronicle is averaged on a window centered on the stamp, a coarser
      or same-frequency one gives its nearest sample within ``tolerance``.

    The rules are written once, in
    :func:`hydromodpy.core.time.period_aggregation.observed_on_periods`. The
    default ``"mean"`` is the method of a name nothing declares; every
    internal caller passes the method of the variable it aligns.

    A caller aligning a FORCING rather than an observation chronicle should
    call ``period_mean_on_index`` itself, the way
    :func:`hydromodpy.core.time.period_aggregation.runoff_m3_s_on_index` does:
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


def simulated_nan_stamps(
    observed: pd.Series,
    simulated: pd.Series,
    *,
    method: str = DEFAULT_TIME_METHOD,
    start: Any = None,
) -> pd.DatetimeIndex:
    """Return the end stamps whose simulated value is NaN while the record has one.

    These are the pairs :func:`align_observed_simulated` drops because of the
    simulated side, a dry cell for instance. The periods are cut on every
    simulated stamp, NaN ones included, so each stamp keeps its own period.
    A period the record leaves empty is not one of them. The stamps are
    tz-naive UTC.
    """
    sim = normalize_datetime_series(simulated)
    if sim.empty or not sim.isna().any():
        return pd.DatetimeIndex([])
    grid = pd.DatetimeIndex(sim.index).as_unit("ns")
    obs_aligned = observed_on_simulation_index(observed, grid, method=method, start=start)
    covered = obs_aligned.reindex(grid).notna().to_numpy()
    return grid[sim.isna().to_numpy() & covered]


def read_pair(run: Any, variable: str, *, station: str | None = None) -> pd.DataFrame:
    """Return the simulated series of ``variable`` and its observed record on one index.

    The index is the one of ``run.timeseries(variable, station=station)``, the end
    stamps of the periods. Columns are ``simulated`` and ``observed``, float64,
    in the stored unit, and ``observed`` is NaN for a period without observation.
    The observed family is the ``observed`` fact of the descriptor, else
    ``variable``. The time method is the one of ``variable`` and the first period
    start is the one of the run.

    Raises what ``run.timeseries`` and ``run.observed`` raise when a record is
    missing, and ``ValueError`` when ``station`` is None and the record holds
    several stations.
    """
    simulated = run.timeseries(variable, station=station).astype(float)
    found = TIME_SERIES_REGISTRY.get(variable) or FIELD_REGISTRY.get(variable)
    family = (found.observed if found is not None else None) or variable
    raw = run.observed(family, station=station)
    stations = sorted({str(name) for name in raw["station_id"]})
    if station is None and len(stations) > 1:
        raise ValueError(
            f"The {family!r} record of run {run.name!r} holds several stations "
            f"({', '.join(stations)}); name one."
        )
    record = pd.Series(
        raw["value"].to_numpy(float), index=pd.DatetimeIndex(raw["datetime"])
    ).sort_index()
    paired = align_observed_simulated(
        record,
        simulated,
        method=time_method_for(variable),
        start=run_period_start(run, simulated.index),
        dropna=False,
    )
    return pd.DataFrame(
        {"simulated": simulated, "observed": paired["obs"].reindex(simulated.index)}
    )


__all__ = [
    "align_observed_simulated",
    "first_period_start",
    "normalize_datetime_series",
    "observed_on_simulation_index",
    "read_pair",
    "run_period_edges",
    "run_period_start",
    "simulated_nan_stamps",
    "time_method_for",
]
