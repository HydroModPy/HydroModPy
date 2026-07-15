"""Time alignment helpers for observed and simulated series."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


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


def median_step(index: pd.DatetimeIndex) -> pd.Timedelta | None:
    """Return the median spacing of a datetime index."""
    if len(index) < 2:
        return None
    deltas = index.to_series().diff().dropna()
    if deltas.empty:
        return None
    return pd.Timedelta(deltas.median())


def observed_on_simulation_index(
    observed: pd.Series,
    simulation_index: pd.DatetimeIndex,
    *,
    tolerance: pd.Timedelta | None = None,
) -> pd.Series:
    """Average or nearest-match observations on the simulation index."""
    obs = normalize_datetime_series(observed).dropna()
    sim_index = pd.DatetimeIndex(simulation_index)
    if sim_index.tz is not None:
        sim_index = sim_index.tz_convert("UTC").tz_localize(None)
    sim_index = sim_index.sort_values()
    if obs.empty or len(sim_index) == 0:
        return pd.Series(np.nan, index=sim_index, name=observed.name, dtype=float)

    sim_step = median_step(sim_index)
    obs_step = median_step(obs.index)
    if sim_step is not None and obs_step is not None and sim_step > obs_step:
        half = sim_step / 2
        bin_edges = pd.DatetimeIndex([sim_index[0] - half] + [t + half for t in sim_index])
        bins = pd.cut(obs.index, bins=bin_edges, labels=sim_index, right=False)
        binned = obs.groupby(bins, observed=True).mean()
        binned.index = pd.DatetimeIndex(binned.index)
        return binned.reindex(sim_index).rename(observed.name)

    tol = tolerance
    if tol is None:
        tol = sim_step if sim_step is not None else obs_step
    if tol is None:
        tol = pd.Timedelta(0)
    obs_frame = obs.rename("obs").reset_index()
    obs_frame.columns = ["datetime", "obs"]
    sim_frame = pd.DataFrame({"datetime": sim_index})
    aligned = pd.merge_asof(
        sim_frame.sort_values("datetime"),
        obs_frame.sort_values("datetime"),
        on="datetime",
        direction="nearest",
        tolerance=tol,
    )
    return pd.Series(aligned["obs"].to_numpy(dtype=float), index=sim_index, name=observed.name)


def align_observed_simulated(
    observed: pd.Series,
    simulated: pd.Series,
    *,
    dropna: bool = True,
) -> pd.DataFrame:
    """Return observed and simulated values aligned on simulation timestamps."""
    sim = normalize_datetime_series(simulated).dropna()
    if sim.empty:
        return pd.DataFrame(columns=["obs", "sim"])
    obs_aligned = observed_on_simulation_index(observed, pd.DatetimeIndex(sim.index))
    paired = pd.DataFrame({"obs": obs_aligned, "sim": sim.reindex(obs_aligned.index)})
    return paired.dropna() if dropna else paired


__all__ = [
    "align_observed_simulated",
    "median_step",
    "normalize_datetime_series",
    "observed_on_simulation_index",
]
