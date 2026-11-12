"""``soil_storage`` and ``transit_storage`` are states, read at their stamp.

A run stamps each stress period at its end. The soil and transit stores hold
the water in the reservoir at that instant, like a head or a lake stage, so they
are not averaged over the period the way a flux is.
"""

from __future__ import annotations

import pytest

from hydromodpy.core.time.time_method import DEFAULT_TIME_METHOD, OBSERVABLE_TIME_METHODS

METHODS = [
    pytest.param("soil_storage", "point", id="soil storage is a state"),
    pytest.param("transit_storage", "point", id="transit storage is a state"),
    pytest.param("recharge", "mean", id="recharge is a period mean"),
]


@pytest.mark.parametrize(("observable", "method"), METHODS)
def test_time_method(observable, method) -> None:
    assert OBSERVABLE_TIME_METHODS.get(observable, DEFAULT_TIME_METHOD) == method
