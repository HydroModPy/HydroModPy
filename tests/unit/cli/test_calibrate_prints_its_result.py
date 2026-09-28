"""``hmp calibrate`` prints what the run actually found.

``CalibrationReport`` defines no ``summary`` attribute, so
``getattr(result, "summary", None)`` was always ``None`` and the command
printed nothing of the result it just spent hours computing. These tests
exercise the rendering directly, on a report built in memory, rather than
running a real calibration.
"""

from __future__ import annotations

from types import SimpleNamespace

from hydromodpy.calibration.optim.fosm import ParameterUncertainty
from hydromodpy.calibration.report import CalibrationReport
from hydromodpy.cli.commands.calibrate import (
    _format_calibration_result,
    _format_staged_calibration_result,
)


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


def test_the_mean_and_best_cost_share_are_printed_for_two_or_more_blocks() -> None:
    report = _report(
        best_parameters={"K": 6.4e-5},
        objective_block_shares={
            "mean": {"hydrograph": 0.5625, "network": 0.4375},
            "mean_n_trials": 14,
            "best": {"hydrograph": 0.75, "network": 0.25},
        },
    )

    lines = "\n".join(_format_calibration_result(report))

    assert "cost share (mean over 14 finished trials): hydrograph 56%, network 44%" in lines
    assert "cost share (best trial): hydrograph 75%, network 25%" in lines


def test_the_mean_share_falls_back_to_a_plain_label_without_a_trial_count() -> None:
    report = _report(
        best_parameters={"K": 6.4e-5},
        objective_block_shares={"mean": {"hydrograph": 0.6, "network": 0.4}},
    )

    lines = "\n".join(_format_calibration_result(report))

    assert "cost share (mean over the finished trials): hydrograph 60%, network 40%" in lines


def test_a_reused_phase_that_could_not_recompute_its_share_says_so() -> None:
    report = _report(
        best_parameters={"K": 6.4e-5},
        objective_block_shares=None,
        extra={
            "reused_from_disk": True,
            "objective_block_shares_absent_note": (
                "reused from a previous run: its persisted trials carry no cost share "
                "to read back, so it is not recomputed here"
            ),
        },
    )

    lines = "\n".join(_format_calibration_result(report))

    assert "cost share: reused from a previous run" in lines
    assert "not recomputed" in lines


def test_a_single_block_share_is_not_printed() -> None:
    report = _report(
        best_parameters={"K": 6.4e-5},
        objective_block_shares={"mean": {"hydrograph": 1.0}, "best": {"hydrograph": 1.0}},
    )

    lines = "\n".join(_format_calibration_result(report))

    assert "cost share" not in lines


def test_a_report_with_no_computable_share_prints_nothing_about_it() -> None:
    report = _report(best_parameters={"K": 6.4e-5}, objective_block_shares=None)

    lines = "\n".join(_format_calibration_result(report))

    assert "cost share" not in lines


def test_a_staged_result_prints_each_phase_with_its_own_share() -> None:
    phase_a = SimpleNamespace(
        name="k_steady",
        report=_report(best_parameters={"K": 6.4e-5}),
    )
    phase_b = SimpleNamespace(
        name="sy_transient",
        report=_report(
            best_parameters={"Sy": 0.06},
            best_objective=0.27,
            objective_block_shares={
                "mean": {"hydrograph": 0.36, "network_extension": 0.64},
                "mean_n_trials": 14,
                "best": {"hydrograph": 0.37, "network_extension": 0.63},
            },
        ),
    )
    staged = SimpleNamespace(phases=[phase_a, phase_b])

    lines = "\n".join(_format_staged_calibration_result(staged))

    assert "phase k_steady:" in lines
    assert "phase sy_transient:" in lines
    assert "  Sy = 0.06" in lines
    assert "cost share (best trial): hydrograph 37%, network_extension 63%" in lines


def test_a_staged_result_with_no_evaluated_phase_prints_nothing() -> None:
    phase = SimpleNamespace(name="empty", report=_report(best_parameters=None))
    staged = SimpleNamespace(phases=[phase])

    assert _format_staged_calibration_result(staged) == []


def test_the_eq4_verdict_the_bracket_and_the_search_are_printed() -> None:
    report = _report(
        best_parameters={"K": 6.4e-5},
        extra={
            "roptim_verdict": {
                "net": {
                    "value": 0.42,
                    "Doptim": 31.5,
                    "h_obs_m": 75.0,
                    "validity_length_m": 150.0,
                    "provenance": "auto",
                    "valid": True,
                    "causes": [],
                }
            },
            "bracket": {
                "parameter": "K",
                "low": 6.3e-5,
                "high": 6.36e-5,
                "relative_width": 0.0095,
                "closed": True,
            },
            "search": {
                "converged": True,
                "stopping_rule": "rel_tol",
                "max_iter": 15,
                "extension": 0,
                "n_evaluations": 15,
            },
        },
    )

    lines = _format_calibration_result(report)

    assert "  roptim (net) = 0.42, Doptim = 31.5 m <= 150 m (auto), Eq. 4 holds" in lines
    assert "  bracket on K: [6.3e-05, 6.36e-05], width 0.95% (closed)" in lines
    assert "  search: converged on its rule (rel_tol), 15 evaluation(s) of 15 declared" in lines


def test_a_failed_verdict_an_open_bracket_and_an_unconverged_search_say_so() -> None:
    report = _report(
        best_parameters={"K": 6.4e-5},
        extra={
            "roptim_verdict": {
                "net": {
                    "value": 3.1,
                    "Doptim": 232.5,
                    "h_obs_m": 75.0,
                    "validity_length_m": 150.0,
                    "provenance": "auto",
                    "valid": False,
                    "causes": ["doptim"],
                },
                "empty": {
                    "value": None,
                    "Doptim": None,
                    "h_obs_m": None,
                    "validity_length_m": 150.0,
                    "provenance": "auto",
                    "valid": False,
                    "causes": ["empty"],
                },
            },
            "bracket": {
                "parameter": "K",
                "low": 5e-5,
                "high": 8e-5,
                "relative_width": 0.6,
                "closed": False,
            },
            "search": {
                "converged": False,
                "stopping_rule": "rel_tol",
                "max_iter": 10,
                "extension": 5,
                "n_evaluations": 15,
            },
        },
    )

    text = "\n".join(_format_calibration_result(report))

    assert "roptim (net) = 3.1, Doptim = 232.5 m > 150 m (auto), Eq. 4 fails" in text
    assert "roptim (empty): not a number" in text
    assert "(open, the budget ran out first)" in text
    assert "search: did NOT converge on its rule (rel_tol), 15 evaluation(s) of 10 declared" in text
    assert "+ 5 extension" in text


def test_a_snap_that_moved_the_map_too_far_is_named_as_the_cause() -> None:
    snap = {
        "displacement_p90_m": 80.0,
        "displacement_bound_m": 75.0,
        "rejected_share": 0.02,
        "rejected_share_max": 0.1,
        "floor_m": 30.0,
        "valid": False,
    }
    verdict = {
        "value": 1.2,
        "Doptim": 90.0,
        "h_obs_m": 75.0,
        "validity_length_m": 150.0,
        "provenance": "auto",
        "valid": False,
        "causes": ["snap"],
        "snap": snap,
    }
    report = _report(best_parameters={"K": 6.4e-5}, extra={"roptim_verdict": {"net": verdict}})

    text = "\n".join(_format_calibration_result(report))

    # Doptim passes: the line says so and names the snap, never "coarse agreement".
    assert "Doptim = 90 m <= 150 m (auto), Eq. 4 fails: the snap moved the map" in text
    assert "p90 displacement 80 m against 75 m" in text
    assert "coarse agreement" not in text


def test_a_report_without_these_records_prints_none_of_them() -> None:
    text = "\n".join(_format_calibration_result(_report(best_parameters={"K": 6.4e-5})))

    assert "roptim" not in text
    assert "bracket" not in text
    assert "search:" not in text


def test_two_closed_roots_print_a_line_each_then_the_spread_and_the_value() -> None:
    report = _report(
        best_parameters={"K": 6.4e-5},
        extra={
            "roots": {
                "parameter": "K",
                "minimal": {
                    "k_star": 6.3e-5,
                    "trial_id": 3,
                    "residual": 1e-4,
                    "weight": 0.5,
                    "low": 6.28e-5,
                    "high": 6.32e-5,
                    "relative_width": 0.0064,
                    "closed": True,
                },
                "maximal": {
                    "k_star": 6.42e-5,
                    "trial_id": 7,
                    "residual": 2e-4,
                    "weight": 0.5,
                    "low": 6.4e-5,
                    "high": 6.44e-5,
                    "relative_width": 0.0063,
                    "closed": True,
                },
                "delta_log10": 0.0083,
                "value": 6.36e-5,
                "combined_trial_id": 9,
                "closed": True,
            }
        },
    )

    lines = _format_calibration_result(report)

    assert "  K*_minimal = 6.3e-05, bracket [6.28e-05, 6.32e-05], width 0.64% (closed)" in lines
    assert "  K*_maximal = 6.42e-05, bracket [6.4e-05, 6.44e-05], width 0.63% (closed)" in lines
    assert "  Delta = log10(K*_maximal / K*_minimal) = 0.0083 decade(s)" in lines
    assert "  K = 6.36e-05, weighted geometric mean of the two roots (0.5 / 0.5)" in lines


def test_an_open_root_and_an_unsolved_combined_value_say_so() -> None:
    report = _report(
        best_parameters={"K": 6.4e-5},
        extra={
            "roots": {
                "parameter": "K",
                "minimal": {
                    "k_star": 6.3e-5,
                    "trial_id": 3,
                    "residual": 1e-4,
                    "weight": 0.7,
                    "low": 5e-5,
                    "high": 8e-5,
                    "relative_width": 0.6,
                    "closed": False,
                },
                "maximal": {
                    "k_star": 6.42e-5,
                    "trial_id": None,
                    "residual": None,
                    "weight": 0.3,
                    "low": 6.4e-5,
                    "high": 6.44e-5,
                    "relative_width": 0.0063,
                    "closed": True,
                },
                "delta_log10": None,
                "value": None,
                "combined_trial_id": None,
                "closed": False,
            }
        },
    )

    text = "\n".join(_format_calibration_result(report))

    assert "K*_minimal = 6.3e-05, bracket [5e-05, 8e-05], width 60.00% " in text
    assert "(open, the budget ran out first)" in text
    assert "Delta = log10(K*_maximal / K*_minimal) = unknown decade(s)" in text
    assert "K: not solved (weighted geometric mean, 0.7 / 0.3)" in text


def test_a_bracket_prints_no_roots_line() -> None:
    report = _report(
        best_parameters={"K": 6.4e-5},
        extra={
            "bracket": {
                "parameter": "K",
                "low": 6.3e-5,
                "high": 6.36e-5,
                "relative_width": 0.0095,
                "closed": True,
            }
        },
    )

    text = "\n".join(_format_calibration_result(report))

    assert "K*_minimal" not in text
    assert "Delta = " not in text
