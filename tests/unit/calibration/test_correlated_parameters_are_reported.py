"""Two parameters that traded off against each other must be named.

A calibration returns one value per parameter and says nothing about whether the
data could tell them apart. When K rises and Sy falls across the whole trace to
keep the same cost, the pair is not identified: the search stopped somewhere on a
ridge and reported that point as if it were a minimum. That is the equifinality
the literature on this two-stage protocol leaves open, and the diagnostic for it
is the correlation between calibrated parameters over the trace.

``optim/diagnostics.parameter_correlation`` computed that matrix already, from
the trace ``persistence`` already writes, with a test of its own and no caller.
"""

from __future__ import annotations

from hydromodpy.calibration.optim.diagnostics import correlated_parameter_pairs


def _trace(pairs: list[tuple[float, float]]) -> list[dict[str, float]]:
    return [{"K": k, "Sy": s, "objective_total": 1.0} for k, s in pairs]


def test_a_ridge_is_named_with_its_coefficient() -> None:
    """A perfect trade-off between two parameters is reported."""
    trace = _trace([(1.0, 10.0), (2.0, 9.0), (3.0, 8.0), (4.0, 7.0), (5.0, 6.0)])

    pairs = correlated_parameter_pairs(trace, threshold=0.8)

    assert len(pairs) == 1
    first, second, coefficient = pairs[0]
    assert {first, second} == {"K", "Sy"}
    assert coefficient < -0.99


def test_independent_parameters_are_not_reported() -> None:
    """The diagnostic stays quiet when the search separated them."""
    trace = _trace([(1.0, 5.0), (2.0, 5.0), (3.0, 5.0), (1.0, 6.0), (2.0, 6.0), (3.0, 6.0)])

    assert correlated_parameter_pairs(trace, threshold=0.8) == []


def test_a_trace_too_short_to_judge_says_nothing() -> None:
    """One point carries no correlation, and inventing one would be worse."""
    assert correlated_parameter_pairs(_trace([(1.0, 2.0)]), threshold=0.8) == []


def test_the_worst_pair_comes_first() -> None:
    """A reader with three parameters reads the tightest trade-off first."""
    trace = [
        {"K": k, "Sy": s, "n": n, "objective_total": 1.0}
        for k, s, n in [
            (1.0, 10.0, 1.0),
            (2.0, 9.0, 3.0),
            (3.0, 8.0, 2.0),
            (4.0, 7.0, 5.0),
            (5.0, 6.0, 4.0),
        ]
    ]

    pairs = correlated_parameter_pairs(trace, threshold=0.5)

    assert abs(pairs[0][2]) >= abs(pairs[-1][2])
