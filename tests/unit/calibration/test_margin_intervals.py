"""A calibrated value on its own says nothing about how well it is determined.

The report gives one number per parameter. Two searches can return the same
number with entirely different standing: one where the cost climbs steeply on
both sides, one where it is flat over three decades. Nothing in the output told
them apart, so a conductivity read off a report carried no way to know whether
the record constrained it.

The interval is read off the trials the search already ran: the range of values
whose cost stays within a stated margin of the best. It assumes no error
model and costs nothing extra, and it says explicitly when it runs into the
search bound, because there the record does not constrain the parameter at all.
"""

from __future__ import annotations

import pytest

from hydromodpy.calibration.optim.cost_margin import (
    DEFAULT_MARGIN,
    margin_intervals,
)


def _trace(pairs: list[tuple[float, float]]) -> list[dict[str, object]]:
    return [
        {"iter": i, "parameters": {"K": value}, "cost": cost}
        for i, (value, cost) in enumerate(pairs)
    ]


_SHARP = _trace([(1.0, 10.0), (2.0, 1.0), (3.0, 1.02), (4.0, 9.0), (5.0, 30.0)])
_FLAT = _trace([(1.0, 1.01), (2.0, 1.0), (3.0, 1.02), (4.0, 1.01), (5.0, 1.03)])


def test_the_interval_is_the_range_that_stays_within_the_margin() -> None:
    (interval,) = margin_intervals(_SHARP, bounds={"K": (0.5, 6.0)})

    assert interval.name == "K"
    assert interval.best == 2.0
    assert interval.lower == 2.0
    assert interval.upper == 3.0
    assert interval.n_within == 2


def test_a_flat_cost_gives_an_interval_that_spans_the_search() -> None:
    (interval,) = margin_intervals(_FLAT, bounds={"K": (0.5, 6.0)})

    assert interval.lower == 1.0
    assert interval.upper == 5.0
    assert interval.n_within == 5


def test_an_interval_reaching_the_search_bound_says_so() -> None:
    """There the record does not constrain the parameter; it ran out of room."""
    (interval,) = margin_intervals(_FLAT, bounds={"K": (1.0, 5.0)})

    assert interval.reaches_lower_bound is True
    assert interval.reaches_upper_bound is True


def test_an_interval_inside_the_search_does_not_claim_a_bound() -> None:
    (interval,) = margin_intervals(_SHARP, bounds={"K": (0.5, 6.0)})

    assert interval.reaches_lower_bound is False
    assert interval.reaches_upper_bound is False


def test_the_margin_is_relative_to_the_best_cost_by_default() -> None:
    assert DEFAULT_MARGIN == 0.05

    (tight,) = margin_intervals(_SHARP, margin=0.001)

    assert tight.lower == tight.upper == 2.0
    assert tight.n_within == 1


def test_an_absolute_margin_is_read_in_cost_units() -> None:
    (interval,) = margin_intervals(_SHARP, margin=8.5, kind="absolute")

    assert interval.lower == 2.0
    assert interval.upper == 4.0


def test_a_cost_that_reaches_zero_refuses_a_relative_margin() -> None:
    """A gap criterion is solved at zero, where 5 % of the best means nothing."""
    trace = _trace([(1.0, 4.0), (2.0, 0.0), (3.0, 3.0)])

    with pytest.raises(ValueError, match="length"):
        margin_intervals(trace)


def test_failed_trials_are_left_out() -> None:
    trace = _SHARP + _trace([(9.0, float("nan")), (10.0, float("inf"))])

    (interval,) = margin_intervals(trace, bounds={"K": (0.5, 6.0)})

    assert interval.upper == 3.0


def test_a_trace_with_nothing_finite_yields_nothing() -> None:
    assert margin_intervals(_trace([(1.0, float("nan"))])) == []


def test_the_interval_carries_how_many_trials_it_rests_on() -> None:
    (interval,) = margin_intervals(_SHARP)

    assert interval.n_trials == 5
    assert interval.margin == DEFAULT_MARGIN
    assert interval.kind == "relative"


def test_each_calibrated_parameter_gets_its_own_interval() -> None:
    trace = [
        {"iter": 0, "parameters": {"K": 1.0, "Sy": 0.1}, "cost": 5.0},
        {"iter": 1, "parameters": {"K": 2.0, "Sy": 0.2}, "cost": 1.0},
        {"iter": 2, "parameters": {"K": 3.0, "Sy": 0.3}, "cost": 1.01},
    ]

    intervals = {item.name: item for item in margin_intervals(trace)}

    assert set(intervals) == {"K", "Sy"}
    assert intervals["Sy"].lower == 0.2
    assert intervals["Sy"].upper == 0.3
