"""Observed-vs-simulated lake-level fit figure.

A small, reusable diagnostic for lake-stage calibration: it overlays the
observed lake level on the simulated stage, draws a 1:1 scatter on the
period-aligned pairs, and annotates the standard goodness-of-fit metrics.
Series in, PNG out; the function never touches the catalog or the solver,
so any caller can feed it two pandas Series.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from hydromodpy.core.metrics.goodness_of_fit import bias, correlation, mae, nse, rmse
from hydromodpy.results.time_alignment import (
    align_observed_simulated,
    normalize_datetime_series,
)

__all__ = ["lake_level_fit_metrics", "plot_lake_level_fit"]


def lake_level_fit_metrics(observed: pd.Series, simulated: pd.Series) -> dict[str, float]:
    """Return NSE/RMSE/MAE/bias/R2 of ``simulated`` vs ``observed``.

    Both series are aligned on the simulation timestamps before scoring.
    Returns an empty mapping when there is no overlapping finite sample.
    """
    paired = align_observed_simulated(observed, simulated)
    if paired.empty:
        return {}
    sim = paired["sim"].to_numpy()
    obs = paired["obs"].to_numpy()
    r = correlation(sim, obs)
    return {
        "nse": nse(sim, obs),
        "rmse": rmse(sim, obs),
        "mae": mae(sim, obs),
        "bias": bias(sim, obs),
        "r2": r * r,
        "n": float(len(paired)),
    }


def plot_lake_level_fit(
    observed: pd.Series,
    simulated: pd.Series,
    *,
    out_path: str | Path,
    lake_id: str = "lake",
    unit: str = "m",
    title: str | None = None,
) -> dict[str, float]:
    """Render the lake-level fit figure and return the fit metrics.

    Left panel: observed (daily) + simulated stage time series. Right panel:
    1:1 scatter of the period-aligned pairs. Metrics (NSE, RMSE, bias, R2) are
    annotated on the time-series panel. The returned mapping mirrors
    :func:`lake_level_fit_metrics`.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    out_path = Path(out_path)
    sim = normalize_datetime_series(simulated).dropna()
    obs = normalize_datetime_series(observed).dropna()
    if sim.empty:
        raise ValueError("plot_lake_level_fit: simulated series is empty")

    obs_window = obs.loc[sim.index.min() : sim.index.max()] if not obs.empty else obs
    metrics = lake_level_fit_metrics(obs, sim)
    paired = align_observed_simulated(obs, sim)

    fig, (ax_ts, ax_sc) = plt.subplots(
        1, 2, figsize=(11, 4), dpi=150, gridspec_kw={"width_ratios": [3, 1]}
    )

    if not obs_window.empty:
        ax_ts.plot(obs_window.index, obs_window.values, color="black", lw=1.2, label="Observed")
    ax_ts.plot(sim.index, sim.values, color="firebrick", lw=1.6, label="Simulated")
    ax_ts.set_ylabel(f"Lake level [{unit}]")
    ax_ts.set_title(title or f"Lake level fit - {lake_id}")
    ax_ts.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax_ts.legend(fontsize=9, loc="best")
    ax_ts.grid(alpha=0.3)
    if metrics:
        text = (
            f"NSE = {metrics['nse']:.3f}\n"
            f"RMSE = {metrics['rmse']:.3f} {unit}\n"
            f"bias = {metrics['bias']:+.3f} {unit}\n"
            f"R2 = {metrics['r2']:.3f}\n"
            f"n = {int(metrics['n'])}"
        )
        ax_ts.text(
            0.015,
            0.97,
            text,
            transform=ax_ts.transAxes,
            va="top",
            ha="left",
            fontsize=9,
            family="monospace",
            bbox={"boxstyle": "round", "facecolor": "white", "alpha": 0.8, "edgecolor": "#ccc"},
        )

    if not paired.empty:
        ax_sc.scatter(
            paired["obs"], paired["sim"], s=18, alpha=0.7, color="steelblue", edgecolor="none"
        )
        lo = float(min(paired["obs"].min(), paired["sim"].min()))
        hi = float(max(paired["obs"].max(), paired["sim"].max()))
        ax_sc.plot([lo, hi], [lo, hi], color="grey", lw=0.8, zorder=-1)
        ax_sc.set_xlabel(f"Obs [{unit}]")
        ax_sc.set_ylabel(f"Sim [{unit}]")
        ax_sc.set_title("1:1")
        ax_sc.grid(alpha=0.3)
    else:
        ax_sc.set_axis_off()

    fig.tight_layout()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    return metrics
