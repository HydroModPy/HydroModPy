"""A phase that did not converge says what a re-run really replays.

The message told the user to "raise max_trials or loosen the tolerance" and
promised that a re-run replays the trials already solved. The cache key holds
only what changes the cost of a trial, so a new max_trials, precision, seed,
method or option replays the trials it proposes at values already solved, as the
engine warning already says.
"""

from __future__ import annotations

from hydromodpy.calibration.report import CalibrationReport
from hydromodpy.calibration.runners.staged_runner import _why_unsettled


def _report() -> CalibrationReport:
    return CalibrationReport(
        session_id="s1",
        method="scipy_nelder_mead",
        n_trials=120,
        best_cost=2.9,
        duration_s=1.0,
        save_runs="none",
        promoted=0,
        best_parameters={"K": 2.1e-4},
        extra={
            "search": {
                "stop_state": "budget_spent",
                "converged": False,
                "stopping_rule": "xatol",
                "max_trials": 120,
                "extension": 0,
                "n_evaluations": 120,
            }
        },
    )


def test_a_new_search_setting_is_promised_the_cache_only_at_the_values_solved() -> None:
    message = _why_unsettled(_report())

    assert "loosen the tolerance" not in message
    assert (
        "Raise max_trials: a re-run of the same file replays the trials already solved from "
        "the cache. So does a new precision, seed, method or method_options, for every "
        "trial it proposes at values already solved"
    ) in message
