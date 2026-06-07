"""Time alignment helpers for observed and simulated series."""

from __future__ import annotations

import numpy as np
import pandas as pd


def normalize_datetime_series(series: pd.Series) -> pd.Series:
    """Return a float series sorted on a tz-naive UTC DatetimeIndex."""
    if series.empty:
        return series.astype(float)
    idx = pd.DatetimeIndex(series.index)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    out = pd.Series(series.astype(float).to_numpy(), index=idx, name=series.name)
    return out.sort_index()


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
