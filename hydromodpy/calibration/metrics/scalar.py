"""Scalar metric helpers (KGE, NSE, RMSE, MAE).

This module exposes the scoring primitive used by RAM extractors. It owns the
alignment between observed and simulated series, the dispatch to the metric
function, and the higher-is-better flipping convention so the optimizer always
sees a cost.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from hydromodpy.calibration.criteria.series import (
    LOG_METRICS,
    METRICS,
    SAMPLED_BY_DATE,
    clip_negatives_for_log_metric,
)
from hydromodpy.core.logging import get_logger
from hydromodpy.core.time.period_aggregation import periods_in_window
from hydromodpy.core.time.time_method import DEFAULT_TIME_METHOD
from hydromodpy.results.catalog.constants import cost_of
from hydromodpy.results.derive.time_alignment import (
    align_observed_simulated,
    normalize_datetime_series,
)

if TYPE_CHECKING:
    from hydromodpy.calibration.metrics.trial_series_capture import TrialSeriesSink

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


def sampling_step_days(index: pd.Index) -> float | None:
    """Median spacing of a dated index, in days.

    ``None`` when the index is not dated or holds fewer than two distinct
    stamps.
    """
    if not isinstance(index, pd.DatetimeIndex) or index.size < 2:
        return None
    gaps = np.diff(index.sort_values().asi8) / 86_400e9
    gaps = gaps[gaps > 0.0]
    return float(np.median(gaps)) if gaps.size else None


def elapsed_days(index: pd.DatetimeIndex) -> np.ndarray:
    """Date of each stamp of *index*, in days since the epoch."""
    return np.asarray(index.asi8, dtype=float) / 86_400e9


def score(
    observed: pd.Series,
    simulated: pd.Series,
    objective: str,
    *,
    warmup_periods: int = 0,
    scoring_window: tuple[pd.Timestamp | None, pd.Timestamp | None] | None = None,
    metric_kwargs: dict[str, object] | None = None,
    time_method: str = DEFAULT_TIME_METHOD,
    period_start: pd.Timestamp | None = None,
    series_sink: TrialSeriesSink | None = None,
    output: str | None = None,
    station: str | None = None,
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
    output frequency. The two are mutually exclusive at the schema level. The
    window is read as the run reads its own
    (:func:`~hydromodpy.core.time.period_aggregation.periods_in_window`): a
    mean counts when its whole period lies in it, a state when its stamp does.
    ``warmup_periods`` is applied after the window.

    ``metric_kwargs`` reaches the metric function, which is how ``nse_log``
    receives an explicit ``eps`` instead of its adaptive default. A metric of
    :data:`~hydromodpy.calibration.criteria.series.SAMPLED_BY_DATE` also
    receives the sampling step and the dates of the aligned series, as on the
    block route, so a gap left by the pairing is read as a gap.

    ``time_method`` is how the simulated variable relates to its end stamps,
    ``"mean"`` for a flux and ``"point"`` for a state (see
    :func:`hydromodpy.results.derive.time_alignment.time_method_for`).
    ``period_start`` is the start of the first simulated period, which a
    single steady stamp cannot tell on its own.

    ``series_sink``, when given, records the aligned, windowed series this
    call is about to score (``output`` and ``station`` name it) before any
    log-metric clipping, so what is kept is the same pair the cost reduces.
    """
    metric = METRICS.get(objective.lower())
    if metric is None:
        raise ValueError(
            f"Unknown calibration objective {objective!r}. "
            f"Choices: {sorted(METRICS)} or a user callable via 'module.path:fn'."
        )
    paired = align_observed_simulated(observed, simulated, method=time_method, start=period_start)
    if paired.empty:
        raise ValueError("No overlapping finite observation/simulation samples for calibration")
    if scoring_window is not None:
        start, end = scoring_window
        paired = paired[
            periods_in_window(
                paired.index,
                method=time_method,
                start=start,
                end=end,
                grid=normalize_datetime_series(simulated).dropna().index,
                period_start=period_start,
            )
        ]
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
    if series_sink is not None:
        series_sink.record(
            output=output,
            station=station,
            times=paired.index,
            simulated=paired["sim"].to_numpy(),
            observed=paired["obs"].to_numpy(),
        )
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
    kwargs = dict(metric_kwargs or {})
    if objective.lower() in SAMPLED_BY_DATE:
        step = sampling_step_days(paired.index)
        if step is not None:
            kwargs.setdefault("sample_days", step)
            kwargs.setdefault("times_days", elapsed_days(paired.index))
    value = float(metric(sim_values, obs_values, **kwargs))
    if not np.isfinite(value):
        raise ValueError(
            f"Calibration metric {objective!r} returned a non-finite value. "
            + _non_finite_diagnosis(obs_values, sim_values)
        )
    return cost_of(objective, value)


__all__ = ["elapsed_days", "sampling_step_days", "score"]
