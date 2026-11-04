"""Tests of `runners.failure_watch`."""

from __future__ import annotations

import pytest

from hydromodpy.calibration.runners.failure_watch import (
    ConsecutiveFailureWatch,
    EveryTrialFailedError,
)

# From test_a_wholly_failed_search_stops.py
# A search whose every trial fails must stop, not finish and report a winner.
#
# A mis-configured calibration used to log one warning per trial and carry on: on
# a twenty-iteration search that is twenty lines buried in the solver's own output,
# followed by a session that completes and names a best candidate computed from
# nothing. For someone who will not read the code to find out why, a single early
# refusal is worth more than a plausible result.
#
# The counter lives on the wrapper so it sees the trials the engine actually ran;
# a cache hit never reaches the evaluator and must not count as a failure.


def test_a_run_of_failures_stops_the_search() -> None:
    """The watch gives up once the declared streak is reached."""
    watch = ConsecutiveFailureWatch(limit=3)

    watch.record(failed=True, error="no observed discharge")
    watch.record(failed=True, error="no observed discharge")
    with pytest.raises(EveryTrialFailedError) as failure:
        watch.record(failed=True, error="no observed discharge")

    message = str(failure.value)
    assert "3" in message
    assert "no observed discharge" in message


def test_one_success_clears_the_streak() -> None:
    """A search that recovers is a search, not a failure."""
    watch = ConsecutiveFailureWatch(limit=3)

    watch.record(failed=True, error="transient")
    watch.record(failed=True, error="transient")
    watch.record(failed=False, error=None)
    watch.record(failed=True, error="transient")
    watch.record(failed=True, error="transient")


def test_the_message_carries_the_last_reason() -> None:
    """The reason is what the reader needs; the count only says it is systematic."""
    watch = ConsecutiveFailureWatch(limit=2)

    watch.record(failed=True, error="first reason")
    with pytest.raises(EveryTrialFailedError, match="second reason"):
        watch.record(failed=True, error="second reason")


def test_a_limit_of_zero_never_fires() -> None:
    """Opting out stays possible for a search expected to fail its way through."""
    watch = ConsecutiveFailureWatch(limit=0)

    for _ in range(50):
        watch.record(failed=True, error="ignored")


_FAILED = (True, "no observed discharge")
_INFEASIBLE = (True, "infeasible: fork: ValueError: candidate 0.8")
_SCORED = (False, None)


@pytest.mark.parametrize(
    ("trials", "refusal"),
    [
        # A point out of physical bounds says nothing about the configuration.
        ([_SCORED, _FAILED, *[_INFEASIBLE] * 5, _FAILED], "2 calibration trials in a row"),
        # A search that never scores a point is refused, by the infeasible count.
        ([_FAILED, *[_INFEASIBLE] * 3], "3 calibration trials were infeasible"),
        # Once a point is scored, an infeasible region is a region to walk out of.
        ([_SCORED, *[_INFEASIBLE] * 10], None),
    ],
)
def test_an_infeasible_trial_is_counted_apart(trials, refusal) -> None:
    watch = ConsecutiveFailureWatch(limit=2, infeasible_limit=3)

    *head, (failed, error) = trials
    for head_failed, head_error in head:
        watch.record(failed=head_failed, error=head_error)
    if refusal is None:
        watch.record(failed=failed, error=error)
        return
    with pytest.raises(EveryTrialFailedError, match=refusal):
        watch.record(failed=failed, error=error)
