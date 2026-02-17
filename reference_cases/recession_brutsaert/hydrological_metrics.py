"""Classical hydrological performance metrics and objective-function switch.

References
----------
NSE:
  Nash, J. E., and J. V. Sutcliffe (1970).
  River flow forecasting through conceptual models part I.
  Journal of Hydrology, 10(3), 282-290.
  doi:10.1016/0022-1694(70)90255-6

NSElog (log-transformed NSE usage in model evaluation):
  Krause, P., D. P. Boyle, and F. Base (2005).
  Comparison of different efficiency criteria for hydrological model assessment.
  Advances in Geosciences, 5, 89-97.
  doi:10.5194/adgeo-5-89-2005

KGE (2009 original form):
  Gupta, H. V., H. Kling, K. K. Yilmaz, and G. F. Martinez (2009).
  Decomposition of the mean squared error and NSE performance criteria.
  Journal of Hydrology, 377(1-2), 80-91.
  doi:10.1016/j.jhydrol.2009.08.003
"""

import numpy as np


def _prepare_series(observed, simulated):
    """
    Prepare observed/simulated arrays with common finite-value masking.

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        (obs, sim) masked to finite pairs.

    Notes
    -----
    - Keeps only paired finite values to avoid NaN/Inf propagation.
    - Preserves 1-to-1 comparison after masking.
    """
    obs = np.asarray(observed, dtype=float)
    sim = np.asarray(simulated, dtype=float)

    if obs.shape != sim.shape:
        raise ValueError("observed and simulated must have the same shape")

    # Keep only entries where both observed and simulated are finite.
    mask = np.isfinite(obs) & np.isfinite(sim)
    obs = obs[mask]
    sim = sim[mask]

    if obs.size == 0:
        raise ValueError("no valid finite values after masking")

    return obs, sim


def nse(observed, simulated):
    """
    Nash-Sutcliffe Efficiency (NSE).

    NSE = 1 - sum((sim - obs)^2) / sum((obs - mean(obs))^2)

    Interpretation
    --------------
    - 1.0 : perfect fit
    - 0.0 : same skill as using mean(observed)
    - < 0 : worse than mean(observed)
    """
    obs, sim = _prepare_series(observed, simulated)
    # Denominator is total observed variance around its mean.
    denom = np.sum((obs - np.mean(obs)) ** 2)
    if denom == 0:
        raise ValueError("NSE undefined because observed series has zero variance")
    return 1.0 - np.sum((sim - obs) ** 2) / denom


def nse_log(observed, simulated):
    """
    Log-transformed Nash-Sutcliffe Efficiency (NSElog).

    Computed on log(obs) and log(sim), therefore all values must be > 0.
    This metric typically emphasizes low flows more than standard NSE.
    """
    obs, sim = _prepare_series(observed, simulated)
    if np.any(obs <= 0) or np.any(sim <= 0):
        raise ValueError("NSElog requires strictly positive observed and simulated values")
    # Re-use NSE implementation on transformed series.
    return nse(np.log(obs), np.log(sim))


def kge(observed, simulated, return_components=False):
    """
    Kling-Gupta Efficiency (KGE, 2009 form).

    KGE = 1 - sqrt((r-1)^2 + (alpha-1)^2 + (beta-1)^2)
      where:
        r     = correlation(sim, obs)
        alpha = std(sim) / std(obs)
        beta  = mean(sim) / mean(obs)

    Notes
    -----
    KGE decomposes performance into correlation, variability ratio and bias ratio.
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

    # Decompose fit into correlation, spread ratio and bias ratio.
    r = np.corrcoef(obs, sim)[0, 1]
    alpha = sim_std / obs_std
    beta = sim_mean / obs_mean
    kge_value = 1.0 - np.sqrt((r - 1.0) ** 2 + (alpha - 1.0) ** 2 + (beta - 1.0) ** 2)

    if return_components:
        return kge_value, {"r": r, "alpha": alpha, "beta": beta}
    return kge_value


class ObjectiveFunction:
    """
    Objective-function style interface for hydrological metrics.

    Supported canonical metric names:
    - "nse"
    - "nse_log"
    - "kge"

    Aliases are accepted (case-insensitive), e.g.:
    - "NSE", "nash"
    - "nselog", "lognse", "nse-log"
    - "KGE", "kling_gupta"
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
        """
        Build an objective-function evaluator with a default metric.

        Parameters
        ----------
        metric : str
            Default metric name or alias used when `evaluate(...)` is called
            without runtime override.
        """
        # Store canonical metric name at construction for predictable defaults.
        self.metric = self.resolve_metric_name(metric)

    @classmethod
    def resolve_metric_name(cls, metric):
        """
        Normalize metric name and validate supported aliases.

        Returns canonical metric key used internally by evaluator methods.
        """
        key = str(metric).strip().lower()
        if key not in cls._ALIASES:
            valid = ", ".join(sorted(set(cls._ALIASES.values())))
            raise ValueError(f"Unknown metric '{metric}'. Supported canonical metrics: {valid}")
        return cls._ALIASES[key]

    def evaluate(self, observed, simulated, metric=None, return_components=True):
        """
        Evaluate a single metric with optional runtime switch.

        Parameters
        ----------
        observed, simulated : array-like
            Series to compare.
        metric : str or None
            Optional override metric name.
        return_components : bool
            If True and metric is KGE, return its components too.

        Returns
        -------
        dict
            Always returns a dictionary with at least:
            {"metric": <name>, "value": <float>}
            and for KGE optionally:
            {"components": {"r": ..., "alpha": ..., "beta": ...}}
        """
        # Runtime override allows one ObjectiveFunction instance to evaluate
        # several criteria without reconstruction.
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

        # Should not be reachable due to resolve_metric_name.
        raise RuntimeError(f"Unhandled metric '{metric_name}'")

    def evaluate_all(self, observed, simulated):
        """
        Evaluate NSE, NSElog and KGE in one call.

        Returns
        -------
        dict
            {
              "NSE": ...,
              "NSElog": ...,
              "KGE": ...,
              "r": ...,
              "alpha": ...,
              "beta": ...
            }
        """
        # Single-call summary useful for reporting and post-calibration diagnostics.
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
