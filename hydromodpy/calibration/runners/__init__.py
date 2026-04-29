"""Calibration runners (trial drivers) layer.

Owns the "prepare once, evaluate many" trial primitive used by the
calibration loop to evaluate parameter samples without re-running the
expensive setup phases.
"""

from hydromodpy.calibration.runners.trial import (
    TrialContext,
    TrialMetricFn,
    TrialResult,
    prepare_trials,
    promote_trial,
    run_trial_light,
)

__all__ = [
    "TrialContext",
    "TrialMetricFn",
    "TrialResult",
    "prepare_trials",
    "promote_trial",
    "run_trial_light",
]
