"""A phase that did not converge says what a re-run really replays.

The message told the user to "raise max_iter or loosen the tolerance" and
promised that a re-run replays the trials already solved. The tolerance is in
the cache key, as are the seed, the method and its options: changing any of
them solves every trial again. Only max_iter keeps the cache, as the engine
warning already says.
"""

from __future__ import annotations

from hydromodpy.calibration.report import CalibrationReport
from hydromodpy.calibration.runners.staged_runner import _why_not_converged


def _report() -> CalibrationReport:
    return CalibrationReport(
        session_id="s1",
        method="scipy_nelder_mead",
        n_iterations=120,
        best_objective=2.9,
        best_sim_id=None,
        duration_s=1.0,
        save_runs="none",
        promoted=0,
        best_parameters={"K": 2.1e-4},
        extra={
            "search": {
                "converged": False,
                "stopping_rule": "xatol",
                "max_iter": 120,
                "extension": 0,
                "n_evaluations": 120,
            }
        },
    )


def test_only_a_higher_max_iter_is_promised_the_cache() -> None:
    message = _why_not_converged(_report())

    assert "loosen the tolerance" not in message
    assert (
        "Raise max_iter: a re-run of the same file replays the trials already solved from "
        "the cache. A new tolerance, seed, method or method_options changes the cache key "
        "and solves every trial again"
    ) in message
