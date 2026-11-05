"""``soil_storage`` and ``transit_storage`` are states, read at their stamp.

A run stamps each stress period at its end. The soil and transit stores hold
the water in the reservoir at that instant, like a head or a lake stage: they
must not be averaged over the period the way a flux is.
"""

from __future__ import annotations

from hydromodpy.core.time.time_method import observable_time_method


def test_the_soil_storage_is_a_state_at_the_stamp() -> None:
    assert observable_time_method("soil_storage") == "point"


def test_the_transit_storage_is_a_state_at_the_stamp() -> None:
    assert observable_time_method("transit_storage") == "point"


def test_the_recharge_stays_a_period_mean() -> None:
    assert observable_time_method("recharge") == "mean"
