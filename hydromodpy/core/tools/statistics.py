"""Hydrological statistics and efficiency criteria."""

from __future__ import annotations

import datetime
import logging
import numbers

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def rmse_manual(sim, obs):
    """Root Mean Square Error (RMSE)."""
    return np.sqrt(np.mean((sim - obs) ** 2))


def nse_manual(sim, obs, transform=None):
    """Nash-Sutcliffe Efficiency (optionally on log-transformed Q)."""
    if transform == "log":
        eps = 1e-6
        sim, obs = np.log(sim + eps), np.log(obs + eps)
    num = np.sum((obs - sim) ** 2)
    den = np.sum((obs - np.mean(obs)) ** 2)
    return 1 - num / den


def mare_manual(sim, obs):
    """Mean Absolute Relative Error (MARE)."""
    return np.mean(np.abs(sim - obs) / obs)


def kge_manual(sim, obs):
    """Kling-Gupta Efficiency and its three components (r, alpha, beta)."""
    r = np.corrcoef(sim, obs)[0, 1]
    alpha = np.std(sim) / np.std(obs)
    beta = np.sum(sim) / np.sum(obs)
    kge = 1 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)
    return kge, r, alpha, beta


def efficiency_criteria(sim, obs):
    """Compute [RMSE, nRMSE, NSE, NSElog, BAL, MARE, KGE] on two 1-D arrays."""
    sim = np.asarray(sim).ravel()
    obs = np.asarray(obs).ravel()
    mask = ~np.isnan(obs)
    sim, obs = sim[mask], obs[mask]

    rmse = rmse_manual(sim, obs)
    nrmse = rmse / np.mean(obs)
    nse = nse_manual(sim, obs)
    nselog = nse_manual(sim, obs, transform="log")
    bal = np.sum(sim) / np.sum(obs)
    mare = mare_manual(sim, obs)
    kge = kge_manual(sim, obs)[0]

    return rmse, nrmse, nse, nselog, bal, mare, kge


def date_range(start, periods, freq):
    """Generate timestamp range from datetime parameters."""
    return pd.date_range(str(start), periods=periods, freq=freq)


def select_period(df, first, last):
    """Clip a timeseries DataFrame/Series between two boundary years."""
    return df[(df.index.year >= first) & (df.index.year <= last)]


def hydrological_mean(data, accuracy=15):
    """Compute the mean over the longest full-year period in *data*."""
    data = data[1:-1]

    if isinstance(data.index[0], numbers.Number):
        data.index = data["time"]
    if isinstance(data.index[0], str):
        data.index = pd.to_datetime(data.index)
    if not isinstance(data.index[0], datetime.datetime):
        logger.error(
            "No recognized datetime index in input series for hydrological_mean"
        )
        return None

    idx = data[data.index.month == data.index[0].month][
        abs(
            data[data.index.month == data.index[0].month].index.day
            - data.index[0].day
        )
        - 3
        <= 0
    ].index[-1]

    if (idx - data.index[0]).days < 350:
        logger.warning(
            "Time range shorter than one year; using simple mean instead of hydrological mean"
        )

    return data[data.index[0] : idx].mean(numeric_only=False)
