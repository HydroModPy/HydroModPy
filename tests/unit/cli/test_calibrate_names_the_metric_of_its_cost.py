"""``hmp calibrate`` names the metric its cost is.

The recap printed ``cost: 0.12`` alone. On an NSE that is ``1 - NSE``, a good
fit, and read as a score it looks like a poor one. The runner records what the
cost is (``extra["cost_metric"]``, ``1 - nse_log`` for an efficiency), and the
phase recap of ``hmp run`` already printed it.
"""

from __future__ import annotations

from hydromodpy.calibration.report import CalibrationReport
from hydromodpy.cli.commands.calibrate import _format_calibration_result


def _report(extra: dict) -> CalibrationReport:
    return CalibrationReport(
        session_id="abc123",
        method="grid",
        n_iterations=4,
        best_objective=0.1234,
        best_sim_id=None,
        duration_s=1.0,
        save_runs="none",
        promoted=0,
        best_parameters={"K": 6.4e-5},
        extra=extra,
    )


def test_the_cost_line_names_its_metric() -> None:
    lines = _format_calibration_result(_report({"cost_metric": "1 - nse_log"}))

    assert "  cost: 0.1234 (1 - nse_log)" in lines


def test_a_report_without_the_metric_prints_the_cost_alone() -> None:
    lines = _format_calibration_result(_report({}))

    assert "  cost: 0.1234" in lines
