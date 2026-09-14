"""A reported value has to carry how well the search determined it.

Two defects, one place. The trace handed to the diagnostics named its cost
column ``objective_total``, which is not one of the meta names, so the cost was
read as if it were another calibrated parameter: a search on one parameter could
report "K and objective_total moved together", which is not a statement about
identifiability at all.

And nothing measured the width of the optimum. The report gave a number, and a
number is the same whether the cost climbs steeply on both sides of it or is
flat over three decades.
"""

from __future__ import annotations

from hydromodpy.calibration.optim.diagnostics import correlated_parameter_pairs
from hydromodpy.calibration.optim.tolerance import tolerance_intervals


def _trace() -> list[dict[str, object]]:
    return [
        {"iter": 0, "parameters": {"K": 1.0}, "objective_value": 9.0},
        {"iter": 1, "parameters": {"K": 2.0}, "objective_value": 4.0},
        {"iter": 2, "parameters": {"K": 3.0}, "objective_value": 1.0},
        {"iter": 3, "parameters": {"K": 4.0}, "objective_value": 1.02},
    ]


def test_the_cost_is_never_read_as_a_parameter() -> None:
    """A single-parameter search cannot have a correlated pair."""
    assert correlated_parameter_pairs(_trace()) == []


def test_naming_the_parameters_keeps_the_answer_the_same() -> None:
    assert correlated_parameter_pairs(_trace(), ["K"]) == []


def test_two_parameters_moving_together_are_still_reported() -> None:
    trace = [
        {"iter": i, "parameters": {"K": float(i), "Sy": float(i) * 2.0}, "objective_value": 1.0}
        for i in range(5)
    ]

    (pair,) = correlated_parameter_pairs(trace)

    assert {pair[0], pair[1]} == {"K", "Sy"}


def test_the_interval_qualifies_the_reported_value() -> None:
    (interval,) = tolerance_intervals(_trace(), bounds={"K": (1.0, 4.0)})

    assert interval.best == 3.0
    assert interval.lower == 3.0
    assert interval.upper == 4.0
    assert interval.reaches_upper_bound is True


class _Item:
    def __init__(self, trial_id: int, objective_value: float) -> None:
        self.trial_id = trial_id
        self.objective_value = objective_value


def test_the_runner_builds_the_trace_under_the_name_the_diagnostics_read() -> None:
    from hydromodpy.calibration.runners.cli_runner import calibration_trace

    history = [_Item(0, 9.0), _Item(1, 1.0), _Item(2, 1.01)]
    values = {0: {"K": 1.0}, 1: {"K": 2.0}, 2: {"K": 3.0}}

    trace = calibration_trace(history, values)

    assert [row["objective_value"] for row in trace] == [9.0, 1.0, 1.01]
    assert correlated_parameter_pairs(trace, ["K"]) == []


def test_a_trial_with_no_recorded_values_is_left_out() -> None:
    from hydromodpy.calibration.runners.cli_runner import calibration_trace

    trace = calibration_trace([_Item(0, 1.0), _Item(7, 2.0)], {0: {"K": 1.0}})

    assert len(trace) == 1
