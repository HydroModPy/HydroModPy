"""Scalar metric helpers (KGE, NSE, RMSE, MAE).

This module exposes the scoring primitive used by RAM extractors. It owns the
alignment between observed and simulated series, the dispatch to the metric
function, and the higher-is-better flipping convention so the optimizer always
sees a cost.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from hydromodpy.calibration.optim.objective import (
    HIGHER_IS_BETTER,
    LOG_METRICS,
    METRICS,
    clip_negatives_for_log_metric,
)
from hydromodpy.core.logging import get_logger
from hydromodpy.results.derive.time_alignment import align_observed_simulated

logger = get_logger(__name__)


def _non_finite_diagnosis(observed: np.ndarray, simulated: np.ndarray) -> str:
    """Say which property of the two aligned series makes a metric undefined.

    Every metric here divides by the spread of the observations, so a constant
    record is undefined however good the simulation is. A single non-finite
    sample poisons the whole score the same way, and neither is visible from
    the value alone.
    """
    obs = np.asarray(observed, dtype="float64")
    sim = np.asarray(simulated, dtype="float64")
    reasons: list[str] = []
    if not np.all(np.isfinite(obs)):
        reasons.append(f"{int(np.count_nonzero(~np.isfinite(obs)))} of {obs.size} observed")
    if not np.all(np.isfinite(sim)):
        reasons.append(f"{int(np.count_nonzero(~np.isfinite(sim)))} of {sim.size} simulated")
    if reasons:
        return "Non-finite samples reached the metric: " + ", ".join(reasons) + "."
    finite_obs = obs[np.isfinite(obs)]
    if finite_obs.size and float(np.var(finite_obs)) == 0.0:
        return (
            f"The {obs.size} observed samples are all {finite_obs[0]:.6g}: every metric here "
            "divides by their spread, so none is defined on a constant record."
        )
    return (
        f"{obs.size} sample(s) scored, observed in [{np.min(obs):.6g}, {np.max(obs):.6g}], "
        f"simulated in [{np.min(sim):.6g}, {np.max(sim):.6g}]."
    )


def score(
    observed: pd.Series,
    simulated: pd.Series,
    objective: str,
    *,
    warmup_periods: int = 0,
    scoring_window: tuple[pd.Timestamp | None, pd.Timestamp | None] | None = None,
    metric_kwargs: dict[str, object] | None = None,
) -> float:
    """Align both series at the simulation frequency, compute the scalar metric.

    Returns the cost (lower is better). Higher-is-better metrics like NSE and
    KGE are flipped into ``1 - value`` so the optimizer always minimizes.

    ``warmup_periods`` drops that many aligned samples from the START before
    scoring. A transient model opens on an initial state the user supplied rather
    than one the model produced, so the first seasons say more about that guess
    than about the parameters; scoring them makes the optimiser chase the warm-up.
    The setting comes from ``[calibration].warmup_periods``, which until now was
    honoured only on the synthetic-truth paths and silently ignored here.

    ``scoring_window`` says the same thing in dates rather than in samples, which
    is what a transient calibration wants: it means the same span whatever the
    output frequency. The two are mutually exclusive at the schema level.

    ``metric_kwargs`` reaches the metric function, which is how ``nse_log``
    receives an explicit ``eps`` instead of its adaptive default.
    """
    metric = METRICS.get(objective.lower())
    if metric is None:
        raise ValueError(
            f"Unknown calibration objective {objective!r}. "
            f"Choices: {sorted(METRICS)} or a user callable via 'module.path:fn'."
        )
    paired = align_observed_simulated(observed, simulated)
    if paired.empty:
        raise ValueError("No overlapping finite observation/simulation samples for calibration")
    if scoring_window is not None:
        start, end = scoring_window
        if start is not None:
            paired = paired[paired.index >= start]
        if end is not None:
            paired = paired[paired.index <= end]
        if paired.empty:
            raise ValueError(f"scoring_window {start} to {end} leaves no aligned sample to score")
    skip = max(0, int(warmup_periods))
    if skip:
        if skip >= len(paired):
            raise ValueError(
                f"warmup_periods={skip} leaves no sample to score "
                f"({len(paired)} aligned periods available)"
            )
        paired = paired.iloc[skip:]
    sim_values = paired["sim"].values
    obs_values = paired["obs"].values
    if objective.lower() in LOG_METRICS:
        sim_values, obs_values, n_clipped = clip_negatives_for_log_metric(sim_values, obs_values)
        if n_clipped:
            logger.warning(
                "Metric %s: %d negative value(s) clipped to zero before the log transform. "
                "A reconstructed discharge below a dam can be negative; a sign error looks "
                "the same, so check the series.",
                objective,
                n_clipped,
            )
    value = float(metric(sim_values, obs_values, **(metric_kwargs or {})))
    if not np.isfinite(value):
        raise ValueError(
            f"Calibration metric {objective!r} returned a non-finite value. "
            + _non_finite_diagnosis(obs_values, sim_values)
        )
    return (1.0 - value) if objective.lower() in HIGHER_IS_BETTER else value


__all__ = ["score"]
