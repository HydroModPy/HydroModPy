"""``hmp calibrate`` prints what the run actually found.

``CalibrationReport`` defines no ``summary`` attribute, so
``getattr(result, "summary", None)`` was always ``None`` and the command
printed nothing of the result it just spent hours computing. These tests
exercise the rendering directly, on a report built in memory, rather than
running a real calibration.
"""

from __future__ import annotations

from hydromodpy.calibration.optim.fosm import ParameterUncertainty
from hydromodpy.calibration.report import CalibrationReport
from hydromodpy.cli.commands.calibrate import _format_calibration_result


def _report(**overrides: object) -> CalibrationReport:
    fields: dict[str, object] = {
        "session_id": "abc123",
        "method": "grid",
        "n_iterations": 4,
        "best_objective": 0.1234,
        "best_sim_id": None,
        "duration_s": 1.0,
        "save_runs": "none",
        "promoted": 0,
    }
    fields.update(overrides)
    return CalibrationReport(**fields)


def test_the_calibrated_value_and_cost_are_printed() -> None:
    report = _report(best_parameters={"K": 6.4e-5})

    lines = "\n".join(_format_calibration_result(report))

    assert "K = 6.4e-05" in lines
    assert "cost: 0.1234" in lines


def test_k_over_r_from_extra_is_printed_with_its_note() -> None:
    report = _report(
        best_parameters={"K": 6.4e-5},
        extra={
            "k_over_r": 3.2,
            "k_over_r_note": "k_over_r = 3.2, against R_mean_m_s = 2e-5 m/s: "
            "the ratio is not a conductivity.",
        },
    )

    lines = "\n".join(_format_calibration_result(report))

    assert "k_over_r = 3.2" in lines
    assert "not a conductivity" in lines


def test_the_tolerance_interval_is_shown_beside_its_value() -> None:
    report = _report(
        best_parameters={"K": 6.4e-5},
        extra={
            "parameter_intervals": [
                {
                    "name": "K",
                    "best": 6.4e-5,
                    "lower": 5e-5,
                    "upper": 7e-5,
                    "tolerance": 0.05,
                    "mode": "relative",
                    "threshold": 0.13,
                    "n_within": 2,
                    "n_trials": 4,
                    "reaches_lower_bound": False,
                    "reaches_upper_bound": False,
                }
            ]
        },
    )

    lines = "\n".join(_format_calibration_result(report))

    assert "[5e-05, 7e-05]" in lines


def test_a_value_stuck_on_a_search_bound_is_flagged() -> None:
    report = _report(
        best_parameters={"K": 1e-3},
        extra={
            "parameter_intervals": [
                {
                    "name": "K",
                    "best": 1e-3,
                    "lower": 9e-4,
                    "upper": 1e-3,
                    "tolerance": 0.05,
                    "mode": "relative",
                    "threshold": 1e-4,
                    "n_within": 1,
                    "n_trials": 4,
                    "reaches_lower_bound": False,
                    "reaches_upper_bound": True,
                }
            ]
        },
    )

    lines = "\n".join(_format_calibration_result(report))

    assert "reached the search bound" in lines


def test_two_parameters_moving_together_are_flagged_as_a_caution() -> None:
    report = _report(
        best_parameters={"K": 6.4e-5, "Sy": 0.1},
        extra={"correlated_parameters": [("K", "Sy", 0.97)]},
    )

    lines = "\n".join(_format_calibration_result(report))

    assert "K and Sy" in lines
    assert "not identified separately" in lines


def test_a_fosm_width_is_shown_and_wins_over_a_tolerance_interval() -> None:
    report = _report(
        best_parameters={"K": 6.4e-5},
        parameter_uncertainty=(
            ParameterUncertainty(parameter="K", value=6.4e-5, sigma=2e-6, correlations={}),
        ),
        extra={
            "parameter_intervals": [
                {
                    "name": "K",
                    "best": 6.4e-5,
                    "lower": 5e-5,
                    "upper": 7e-5,
                    "tolerance": 0.05,
                    "mode": "relative",
                    "threshold": 0.13,
                    "n_within": 2,
                    "n_trials": 4,
                    "reaches_lower_bound": False,
                    "reaches_upper_bound": False,
                }
            ]
        },
    )

    lines = "\n".join(_format_calibration_result(report))

    assert "sigma 2e-06" in lines
    assert "[5e-05, 7e-05]" not in lines


def test_a_fosm_tradeoff_is_flagged_instead_of_the_trace_correlation() -> None:
    report = _report(
        best_parameters={"K": 6.4e-5, "Sy": 0.1},
        parameter_uncertainty=(
            ParameterUncertainty(
                parameter="K", value=6.4e-5, sigma=2e-6, correlations={"K": 1.0, "Sy": 0.95}
            ),
            ParameterUncertainty(
                parameter="Sy", value=0.1, sigma=3e-3, correlations={"K": 0.95, "Sy": 1.0}
            ),
        ),
        extra={"correlated_parameters": [("K", "Sy", 0.5)]},
    )

    lines = "\n".join(_format_calibration_result(report))

    assert "trade off (r = +0.95)" in lines
    assert "moved together (r = +0.50)" not in lines


def test_a_report_with_no_optional_part_prints_the_bare_minimum() -> None:
    report = _report(best_parameters={"K": 6.4e-5})

    lines = _format_calibration_result(report)

    assert lines == ["  K = 6.4e-05", "  cost: 0.1234"]


def test_a_report_with_no_candidate_evaluated_prints_nothing_and_does_not_crash() -> None:
    report = _report(best_objective=None, best_parameters=None)

    assert _format_calibration_result(report) == []


def test_a_bare_object_with_no_calibration_fields_does_not_crash() -> None:
    assert _format_calibration_result(object()) == []
