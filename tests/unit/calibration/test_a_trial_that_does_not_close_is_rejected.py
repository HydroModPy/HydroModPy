"""A trial whose water balance does not close is not a cheaper trial.

The solver reports a percent discrepancy on every run, and until now that number
was recorded and nothing read it. A run at twelve per cent was an ordinary trial:
scored, ranked, and eligible for promotion. Its cost is not comparable to a run
that closed, because part of the water it routed came from nowhere.

The threshold is a declaration, not a constant. A steady solve on a coarse mesh
closes to a fraction of a per cent; a transient one with a lake and a stream
network legitimately sits higher. Whoever runs the model states what they accept,
and a trial past it is rejected rather than scored, with the number said.
"""

from __future__ import annotations

import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.runners.verdict import (
    WATER_BUDGET_METRIC,
    water_budget_verdict,
)


class TestTheDeclaration:
    def test_nothing_is_rejected_by_default(self) -> None:
        """A threshold nobody chose must not start refusing runs."""
        assert CalibrationConfig().reject_water_budget_above is None

    def test_a_file_may_state_what_it_accepts(self) -> None:
        cfg = CalibrationConfig.model_validate(
            {"parameters": {"K": {"bounds": [1e-8, 1e-2]}}, "reject_water_budget_above": 5.0}
        )

        assert cfg.reject_water_budget_above == 5.0

    def test_a_negative_threshold_is_refused(self) -> None:
        with pytest.raises(ValueError):
            CalibrationConfig.model_validate(
                {
                    "parameters": {"K": {"bounds": [1e-8, 1e-2]}},
                    "reject_water_budget_above": -1.0,
                }
            )


class TestTheVerdict:
    def test_no_threshold_passes_whatever_the_discrepancy(self) -> None:
        verdict = water_budget_verdict({WATER_BUDGET_METRIC: 12.0}, threshold=None)

        assert verdict is None

    def test_a_run_inside_the_threshold_passes(self) -> None:
        verdict = water_budget_verdict({WATER_BUDGET_METRIC: 0.4}, threshold=5.0)

        assert verdict is not None
        assert verdict.passed is True
        assert verdict.value == pytest.approx(0.4)

    def test_a_run_past_the_threshold_fails_and_is_fatal(self) -> None:
        verdict = water_budget_verdict({WATER_BUDGET_METRIC: 12.0}, threshold=5.0)

        assert verdict is not None
        assert verdict.passed is False
        assert verdict.fatal is True

    def test_the_sign_of_the_discrepancy_does_not_excuse_it(self) -> None:
        verdict = water_budget_verdict({WATER_BUDGET_METRIC: -12.0}, threshold=5.0)

        assert verdict is not None
        assert verdict.passed is False

    def test_a_run_that_reported_nothing_yields_no_verdict(self) -> None:
        """Absent is not zero: a backend that reports none says nothing either way."""
        assert water_budget_verdict({}, threshold=5.0) is None


class TestTheLabelReadsInPlainWords:
    def test_it_says_what_the_failure_does_to_the_number(self) -> None:
        verdict = water_budget_verdict({WATER_BUDGET_METRIC: 12.0}, threshold=5.0)

        assert verdict is not None
        message = verdict.message
        assert "12" in message
        assert "5" in message
        assert "not comparable" in message

    def test_it_names_itself_so_a_report_can_group_it(self) -> None:
        verdict = water_budget_verdict({WATER_BUDGET_METRIC: 12.0}, threshold=5.0)

        assert verdict is not None
        assert verdict.name == "water_budget"


class TestTheTrialActsOnIt:
    def test_a_rejected_trial_is_not_scored(self) -> None:
        import inspect

        from hydromodpy.calibration.runners import trial

        source = inspect.getsource(trial)

        assert "water_budget_verdict" in source

    def test_the_runner_forwards_what_the_file_declared(self) -> None:
        import inspect

        from hydromodpy.calibration.runners import cli_runner

        source = inspect.getsource(cli_runner.run_calibration_core)

        assert "reject_water_budget_above=cfg.reject_water_budget_above" in source

    def test_a_rejected_trial_keeps_its_metrics_so_the_reason_is_readable(self) -> None:
        import inspect

        from hydromodpy.calibration.runners import trial

        rejected = inspect.getsource(trial.run_trial_light).split("water_budget_verdict")[1]

        assert "metrics=dict(metrics)" in rejected
        assert 'status="failed"' in rejected
        assert "error=verdict.message" in rejected
