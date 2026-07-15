"""Scalar metric helpers (KGE, NSE, RMSE, MAE).

This module exposes the scoring primitive used by RAM extractors. It owns the
alignment between observed and simulated series, the dispatch to the metric
function, and the higher-is-better flipping convention so the optimizer always
sees a cost.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from hydromodpy.calibration.optim.objective import HIGHER_IS_BETTER, METRICS
from hydromodpy.results.derive.time_alignment import align_observed_simulated


def score(observed: pd.Series, simulated: pd.Series, objective: str) -> float:
    """Align both series at the simulation frequency, compute the scalar metric.

    Returns the cost (lower is better). Higher-is-better metrics like NSE and
    KGE are flipped into ``1 - value`` so the optimizer always minimizes.
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
    value = float(metric(paired["sim"].values, paired["obs"].values))
    if not np.isfinite(value):
        raise ValueError(f"Calibration metric {objective!r} returned a non-finite value")
    return (1.0 - value) if objective.lower() in HIGHER_IS_BETTER else value


__all__ = ["score"]
