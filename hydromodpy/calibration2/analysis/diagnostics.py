"""Shared analysis helpers for calibration workflows."""

from __future__ import annotations

import numpy as np

from hydromodpy.calibration2.core.results import CalibrationResults
from hydromodpy.calibration2.analysis.plotting import unique_rows_with_counts
from hydromodpy.calibration2.core.objective_function import kge, nse, nse_log


def compute_performance_metrics(observed, simulated, *, nse_log_floor=None):
    """
    Compute NSE, NSElog and KGE with optional positivity floor for NSElog.
    """
    obs = np.asarray(observed, dtype=float).ravel()
    sim = np.asarray(simulated, dtype=float).ravel()
    if obs.shape != sim.shape:
        raise ValueError("observed and simulated must have the same shape")

    nse_value = float(nse(obs, sim))
    if nse_log_floor is None:
        nse_log_value = float(nse_log(obs, sim))
    else:
        floor = float(nse_log_floor)
        if floor <= 0.0:
            raise ValueError("nse_log_floor must be > 0")
        obs_pos = np.maximum(obs, floor)
        sim_pos = np.maximum(sim, floor)
        nse_log_value = float(nse_log(obs_pos, sim_pos))

    kge_value, components = kge(obs, sim, return_components=True)
    return {
        "NSE": nse_value,
        "NSElog": nse_log_value,
        "KGE": float(kge_value),
        "r": float(components["r"]),
        "alpha": float(components["alpha"]),
        "beta": float(components["beta"]),
    }


def extract_result_samples(
    result: CalibrationResults,
    *,
    n_params,
    posterior_unique_threshold=10,
    rounding_decimals=10,
):
    """
    Build sample views used by plotting/reporting from a `CalibrationResults`.
    """
    n_params = int(n_params)
    posterior_samples = (
        np.asarray(result.samples, dtype=float)
        if result.samples is not None
        else np.empty((0, n_params), dtype=float)
    )
    chain_samples = np.asarray(
        result.metadata.get("chain_samples", np.empty((0, n_params))),
        dtype=float,
    )
    has_posterior = posterior_samples.ndim == 2 and posterior_samples.shape[0] > 1
    posterior_unique, posterior_counts = unique_rows_with_counts(
        posterior_samples,
        decimals=rounding_decimals,
    )
    chain_unique, chain_counts = unique_rows_with_counts(
        chain_samples,
        decimals=rounding_decimals,
    )

    if posterior_unique.shape[0] >= int(posterior_unique_threshold):
        sample_source = posterior_samples
    elif chain_unique.shape[0] > 0:
        sample_source = chain_samples
    else:
        sample_source = posterior_samples

    return {
        "posterior_samples": posterior_samples,
        "chain_samples": chain_samples,
        "has_posterior": bool(has_posterior),
        "posterior_unique": posterior_unique,
        "posterior_counts": posterior_counts,
        "chain_unique": chain_unique,
        "chain_counts": chain_counts,
        "sample_source": sample_source,
    }


def build_calibration_result_view(
    result: CalibrationResults,
    *,
    parameter_names,
    posterior_unique_threshold=10,
    rounding_decimals=10,
):
    """
    Build a generic plotting/reporting view from `CalibrationResults`.
    """
    names = tuple(parameter_names)
    sample_views = extract_result_samples(
        result,
        n_params=len(names),
        posterior_unique_threshold=posterior_unique_threshold,
        rounding_decimals=rounding_decimals,
    )
    return {
        "method": str(result.method),
        "cost_best": float(result.cost_best),
        "score_best": (
            None if result.score_best is None else float(result.score_best)
        ),
        "n_evaluations": int(result.n_evaluations),
        "parameter_names": names,
        **sample_views,
    }
