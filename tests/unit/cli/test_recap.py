"""The lines ``hmp calibrate`` prints about what a calibration found, built from a report in memory.

K is in m/s, Sy has no unit, costs are fractions of 1 that print as percent, widths are relative.
A value that sits on a search bound, two parameters that move together, the cost share of each
block, the Eq. 4 verdict, the bracket and the roots of a bisection each get a line.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.calibration.optim.fosm import ParameterUncertainty
from hydromodpy.calibration.report import CalibrationReport
from hydromodpy.calibration.runners.recap import result_lines, staged_result_lines

BOUND_FLAGS = [
    pytest.param(1e-3, "-- reached the search bound", id="on the bound"),
    pytest.param(9.5e-4, "-- its range reaches the search bound", id="range reaches the bound"),
]

UNIT_LINES = [
    pytest.param("m/s", "  K = 6.4e-05 m/s", id="with a unit"),
    pytest.param("-", "  K = 6.4e-05", id="without a unit"),
]


def report(**overrides: object) -> CalibrationReport:
    fields: dict[str, object] = {
        "session_id": "abc123",
        "method": "grid",
        "n_trials": 4,
        "best_cost": 0.1234,
        "duration_s": 1.0,
        "save_runs": "none",
        "promoted": 0,
    }
    fields.update(overrides)
    return CalibrationReport(**fields)


def k_report(**extra: object) -> CalibrationReport:
    """A report whose only parameter is K = 6.4e-5 m/s, with *extra* entries."""
    return report(best_parameters={"K": 6.4e-5}, extra=extra)


def text_of(result: CalibrationReport) -> str:
    return "\n".join(result_lines(result))


def interval(**fields: object) -> dict:
    """A tolerance interval of K around 6.4e-5 that touches no bound."""
    base = {
        "name": "K",
        "best": 6.4e-5,
        "lower": 5e-5,
        "upper": 7e-5,
        "margin": 0.05,
        "kind": "relative",
        "threshold": 0.13,
        "n_within": 2,
        "n_trials": 4,
        "reaches_lower_bound": False,
        "reaches_upper_bound": False,
    }
    return base | fields


def verdict(**fields: object) -> dict:
    """The Eq. 4 verdict of one network: r_optim, D_optim and the validity length in m."""
    base = {
        "value": 0.42,
        "D_optim": 31.5,
        "h_obs_m": 75.0,
        "validity_length_m": 150.0,
        "provenance": "auto",
        "valid": True,
        "causes": [],
    }
    return base | fields


def root(**fields: object) -> dict:
    """One root of K in a bisection, with its bracket."""
    base = {
        "k_star": 6.3e-5,
        "trial_id": 3,
        "residual": 1e-4,
        "weight": 0.5,
        "low": 6.28e-5,
        "high": 6.32e-5,
        "relative_width": 0.0064,
        "closed": True,
    }
    return base | fields


def test_k_over_r_note() -> None:
    result = report(
        best_parameters={"K": 6.4e-5},
        extra={
            "k_over_r": 3.2,
            "k_over_r_note": "k_over_r = 3.2, against R_mean_m_s = 2e-5 m/s: "
            "the ratio is not a conductivity.",
        },
    )

    lines = text_of(result)

    assert "k_over_r = 3.2" in lines
    assert "not a conductivity" in lines


@pytest.mark.parametrize(("best", "flag"), BOUND_FLAGS)
def test_value_on_search_bound(best: float, flag: str) -> None:
    stuck = interval(
        best=best,
        lower=9e-4,
        upper=1e-3,
        threshold=1e-4,
        n_within=1,
        reaches_upper_bound=True,
    )
    result = report(best_parameters={"K": best}, extra={"parameter_intervals": [stuck]})

    assert flag in text_of(result)


def test_correlated_parameters() -> None:
    result = report(
        best_parameters={"K": 6.4e-5, "Sy": 0.1},
        extra={"correlated_parameters": [("K", "Sy", 0.97)]},
    )

    lines = text_of(result)

    assert "K and Sy" in lines
    assert "not identified separately" in lines


def test_fosm_beats_interval() -> None:
    result = report(
        best_parameters={"K": 6.4e-5},
        parameter_uncertainty=(
            ParameterUncertainty(parameter="K", value=6.4e-5, sigma=2e-6, correlations={}),
        ),
        extra={"parameter_intervals": [interval()]},
    )

    lines = text_of(result)

    assert "sigma 2e-06" in lines
    assert "[5e-05, 7e-05]" not in lines


def test_fosm_tradeoff() -> None:
    result = report(
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

    lines = text_of(result)

    assert "trade off (r = +0.95)" in lines
    assert "moved together (r = +0.50)" not in lines


def test_cost_share_two_blocks() -> None:
    result = report(
        best_parameters={"K": 6.4e-5},
        cost_block_fractions={
            "mean": {"hydrograph": 0.5625, "network": 0.4375},
            "mean_n_trials": 14,
            "best": {"hydrograph": 0.75, "network": 0.25},
        },
    )

    lines = text_of(result)

    assert "cost share (mean over 14 finished trials): hydrograph 56%, network 44%" in lines
    assert "cost share (best trial): hydrograph 75%, network 25%" in lines


def test_cost_share_no_count() -> None:
    result = report(
        best_parameters={"K": 6.4e-5},
        cost_block_fractions={"mean": {"hydrograph": 0.6, "network": 0.4}},
    )

    lines = text_of(result)

    assert "cost share (mean over the finished trials): hydrograph 60%, network 40%" in lines


def test_reused_phase_share() -> None:
    result = report(
        best_parameters={"K": 6.4e-5},
        cost_block_fractions=None,
        extra={
            "reused_from_disk": True,
            "cost_block_fractions_absent_note": (
                "reused from a previous run: its persisted trials carry no cost share "
                "to read back, so it is not recomputed here"
            ),
        },
    )

    lines = text_of(result)

    assert "cost share: reused from a previous run" in lines
    assert "not recomputed" in lines


def test_staged_empty_phase() -> None:
    phase = SimpleNamespace(name="empty", report=report(best_parameters=None))

    assert staged_result_lines(SimpleNamespace(phases=[phase])) == []


def test_verdict_bracket_search() -> None:
    result = k_report(
        r_optim_verdict={"net": verdict()},
        bracket={
            "parameter": "K",
            "low": 6.3e-5,
            "high": 6.36e-5,
            "relative_width": 0.0095,
            "closed": True,
        },
        search={
            "stop_state": "rule_met",
            "converged": True,
            "stopping_rule": "rel_tol",
            "max_trials": 15,
            "extension": 0,
            "n_evaluations": 15,
        },
    )

    lines = result_lines(result)

    assert "  r_optim (net) = 0.42, D_optim = 31.5 m <= 150 m (auto), Eq. 4 holds" in lines
    assert "  bracket on K: [6.3e-05, 6.36e-05], width 0.95% (closed)" in lines
    assert (
        "  search: met its own rule (rel_tol), converged, 15 evaluation(s) of 15 declared" in lines
    )


def test_failed_verdict_open_bracket() -> None:
    empty = verdict(value=None, D_optim=None, h_obs_m=None, valid=False, causes=["empty"])
    result = k_report(
        r_optim_verdict={
            "net": verdict(value=3.1, D_optim=232.5, valid=False, causes=["doptim"]),
            "empty": empty,
        },
        bracket={
            "parameter": "K",
            "low": 5e-5,
            "high": 8e-5,
            "relative_width": 0.6,
            "closed": False,
        },
        search={
            "stop_state": "budget_spent",
            "converged": False,
            "stopping_rule": "rel_tol",
            "max_trials": 10,
            "extension": 5,
            "n_evaluations": 15,
        },
    )

    text = text_of(result)

    assert "r_optim (net) = 3.1, D_optim = 232.5 m > 150 m (auto), Eq. 4 fails" in text
    assert "r_optim (empty): not a number" in text
    assert "(open, the budget ran out first)" in text
    assert (
        "search: spent its budget before its rule (rel_tol) was met, not converged, "
        "15 evaluation(s) of 10 declared" in text
    )
    assert "+ 5 extension" in text


def test_two_closed_roots() -> None:
    result = k_report(
        roots={
            "parameter": "K",
            "minimal": root(),
            "maximal": root(
                k_star=6.42e-5,
                trial_id=7,
                residual=2e-4,
                low=6.4e-5,
                high=6.44e-5,
                relative_width=0.0063,
            ),
            "delta_log10": 0.0083,
            "value": 6.36e-5,
            "combined_trial_id": 9,
            "closed": True,
        }
    )

    lines = result_lines(result)

    assert "  K*_minimal = 6.3e-05, bracket [6.28e-05, 6.32e-05], width 0.64% (closed)" in lines
    assert "  K*_maximal = 6.42e-05, bracket [6.4e-05, 6.44e-05], width 0.63% (closed)" in lines
    assert "  Delta = log10(K*_maximal / K*_minimal) = 0.0083 decade(s)" in lines
    assert "  K = 6.36e-05, weighted geometric mean of the two roots (0.5 / 0.5)" in lines


def test_open_root() -> None:
    result = k_report(
        roots={
            "parameter": "K",
            "minimal": root(weight=0.7, low=5e-5, high=8e-5, relative_width=0.6, closed=False),
            "maximal": root(
                k_star=6.42e-5,
                trial_id=None,
                residual=None,
                weight=0.3,
                low=6.4e-5,
                high=6.44e-5,
                relative_width=0.0063,
            ),
            "delta_log10": None,
            "value": None,
            "combined_trial_id": None,
            "closed": False,
        }
    )

    text = text_of(result)

    assert "K*_minimal = 6.3e-05, bracket [5e-05, 8e-05], width 60.00% " in text
    assert "(open, the budget ran out first)" in text
    assert "Delta = log10(K*_maximal / K*_minimal) = unknown decade(s)" in text
    assert "K: not solved (weighted geometric mean, 0.7 / 0.3)" in text


@pytest.mark.parametrize(("unit", "line"), UNIT_LINES)
def test_value_unit(unit: str, line: str) -> None:
    result = k_report(parameter_units={"K": unit})

    assert result_lines(result)[0] == line
