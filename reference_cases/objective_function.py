"""
Classical performance metrics and objective-function switch.

Bibliographic references
------------------------
RMSE / MAE (forecast and model-error measures):
- Hyndman, R. J., Koehler, A. B. (2006). Another look at measures of
  forecast accuracy. International Journal of Forecasting, 22(4), 679-688.
  DOI: 10.1016/j.ijforecast.2006.03.001

NSE:
- Nash, J. E., Sutcliffe, J. V. (1970). River flow forecasting through
  conceptual models part I - A discussion of principles.
  Journal of Hydrology, 10(3), 282-290.
  DOI: 10.1016/0022-1694(70)90255-6

NSElog usage in hydrological model assessment:
- Krause, P., Boyle, D. P., Base, F. (2005). Comparison of different
  efficiency criteria for hydrological model assessment.
  Advances in Geosciences, 5, 89-97.
  DOI: 10.5194/adgeo-5-89-2005

KGE (2009 formulation used in this module):
- Gupta, H. V., Kling, H., Yilmaz, K. K., Martinez, G. F. (2009).
  Decomposition of the mean squared error and NSE performance criteria:
  Implications for improving hydrological modelling.
  Journal of Hydrology, 377(1-2), 80-91.
  DOI: 10.1016/j.jhydrol.2009.08.003
"""

from __future__ import annotations

import numpy as np


def _prepare_series(observed, simulated):
    """
    Prepare observed/simulated arrays with common finite-value masking.

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        (obs, sim) masked to finite pairs.
    """
    obs = np.asarray(observed, dtype=float)
    sim = np.asarray(simulated, dtype=float)

    if obs.shape != sim.shape:
        raise ValueError("observed and simulated must have the same shape")

    mask = np.isfinite(obs) & np.isfinite(sim)
    obs = obs[mask]
    sim = sim[mask]

    if obs.size == 0:
        raise ValueError("no valid finite values after masking")

    return obs, sim


def rmse(observed, simulated):
    """
    Root Mean Square Error (lower is better).

    Reference: Hyndman and Koehler (2006), DOI: 10.1016/j.ijforecast.2006.03.001
    """
    obs, sim = _prepare_series(observed, simulated)
    return float(np.sqrt(np.mean((sim - obs) ** 2)))


def mae(observed, simulated):
    """
    Mean Absolute Error (lower is better).

    Reference: Hyndman and Koehler (2006), DOI: 10.1016/j.ijforecast.2006.03.001
    """
    obs, sim = _prepare_series(observed, simulated)
    return float(np.mean(np.abs(sim - obs)))


def nse(observed, simulated):
    """
    Nash-Sutcliffe Efficiency (higher is better, max=1).

    Reference: Nash and Sutcliffe (1970), DOI: 10.1016/0022-1694(70)90255-6
    """
    obs, sim = _prepare_series(observed, simulated)
    denom = np.sum((obs - np.mean(obs)) ** 2)
    if denom == 0:
        raise ValueError("NSE undefined because observed series has zero variance")
    return 1.0 - np.sum((sim - obs) ** 2) / denom


def nse_log(observed, simulated):
    """
    Log-transformed Nash-Sutcliffe Efficiency.

    Requires strictly positive observed and simulated values.

    Reference for log-space efficiency usage:
    Krause et al. (2005), DOI: 10.5194/adgeo-5-89-2005
    """
    obs, sim = _prepare_series(observed, simulated)
    if np.any(obs <= 0) or np.any(sim <= 0):
        raise ValueError("NSElog requires strictly positive observed and simulated values")
    return nse(np.log(obs), np.log(sim))


def kge(observed, simulated, return_components=False):
    """
    Kling-Gupta Efficiency (2009 form).

    Reference: Gupta et al. (2009), DOI: 10.1016/j.jhydrol.2009.08.003
    """
    obs, sim = _prepare_series(observed, simulated)

    obs_mean = np.mean(obs)
    sim_mean = np.mean(sim)
    obs_std = np.std(obs, ddof=1)
    sim_std = np.std(sim, ddof=1)

    if obs_std == 0:
        raise ValueError("KGE undefined because observed series has zero standard deviation")
    if obs_mean == 0:
        raise ValueError("KGE undefined because observed mean is zero")

    r = np.corrcoef(obs, sim)[0, 1]
    alpha = sim_std / obs_std
    beta = sim_mean / obs_mean
    kge_value = 1.0 - np.sqrt((r - 1.0) ** 2 + (alpha - 1.0) ** 2 + (beta - 1.0) ** 2)

    if return_components:
        return kge_value, {"r": r, "alpha": alpha, "beta": beta}
    return kge_value


def objective_function(observed, simulated, metric="rmse"):
    """
    Direct helper for one-shot metric evaluation.

    Supported names (case-insensitive):
    - RMSE
    - MAE
    - NSE
    - NSElog / NSE_log
    - KGE
    """
    key = str(metric).strip().lower()

    if key == "rmse":
        return rmse(observed, simulated)
    if key == "mae":
        return mae(observed, simulated)
    if key in ("nse", "nash", "nash_sutcliffe"):
        return float(nse(observed, simulated))
    if key in ("nselog", "nse_log", "nse-log", "lognse"):
        return float(nse_log(observed, simulated))
    if key in ("kge", "kling_gupta", "kling-gupta"):
        return float(kge(observed, simulated, return_components=False))

    raise ValueError(
        f"Unsupported metric: {metric}. "
        "Choose from 'RMSE', 'MAE', 'NSE', 'NSElog', 'KGE'."
    )


class ObjectiveFunction:
    """
    Objective-function interface for calibration workflows.

    Canonical metric names:
    - "nse"
    - "nse_log"
    - "kge"
    """

    _ALIASES = {
        "nse": "nse",
        "nash": "nse",
        "nash_sutcliffe": "nse",
        "nse_log": "nse_log",
        "nselog": "nse_log",
        "lognse": "nse_log",
        "nse-log": "nse_log",
        "kge": "kge",
        "kling_gupta": "kge",
        "kling-gupta": "kge",
    }

    def __init__(self, metric="nse"):
        self.metric = self.resolve_metric_name(metric)

    @classmethod
    def resolve_metric_name(cls, metric):
        """Normalize metric name and validate supported aliases."""
        key = str(metric).strip().lower()
        if key not in cls._ALIASES:
            valid = ", ".join(sorted(set(cls._ALIASES.values())))
            raise ValueError(f"Unknown metric '{metric}'. Supported canonical metrics: {valid}")
        return cls._ALIASES[key]

    def evaluate(self, observed, simulated, metric=None, return_components=True):
        """
        Evaluate one metric.

        Returns
        -------
        dict
            At least {"metric": <name>, "value": <float>}.
            For KGE and `return_components=True`, adds `components`.
        """
        metric_name = self.metric if metric is None else self.resolve_metric_name(metric)

        if metric_name == "nse":
            value = float(nse(observed, simulated))
            return {"metric": metric_name, "value": value}

        if metric_name == "nse_log":
            value = float(nse_log(observed, simulated))
            return {"metric": metric_name, "value": value}

        if metric_name == "kge":
            if return_components:
                value, components = kge(observed, simulated, return_components=True)
                return {"metric": metric_name, "value": float(value), "components": components}
            value = float(kge(observed, simulated, return_components=False))
            return {"metric": metric_name, "value": value}

        raise RuntimeError(f"Unhandled metric '{metric_name}'")

    def evaluate_all(self, observed, simulated):
        """
        Evaluate NSE, NSElog and KGE in one call.
        """
        nse_value = float(nse(observed, simulated))
        nse_log_value = float(nse_log(observed, simulated))
        kge_value, components = kge(observed, simulated, return_components=True)
        return {
            "NSE": nse_value,
            "NSElog": nse_log_value,
            "KGE": float(kge_value),
            "r": float(components["r"]),
            "alpha": float(components["alpha"]),
            "beta": float(components["beta"]),
        }
