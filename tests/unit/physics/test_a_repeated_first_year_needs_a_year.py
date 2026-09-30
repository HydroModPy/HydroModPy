"""Repeating the first year to spin up the soil needs a run of a year at least.

``spinup = "first_year"`` repeats the first 365 days of the run; a shorter run
never sees a full first year to repeat.
"""

from __future__ import annotations

from hydromodpy.physics.hydrology.soil_reservoir.config import (
    SoilReservoirConfig,
    spinup_refusal,
)


def test_a_run_shorter_than_a_year_is_refused() -> None:
    config = SoilReservoirConfig(ru=100.0)

    refusal = spinup_refusal(config, 364)

    assert refusal == (
        'spinup = "first_year" repeats the first 365 days of the run, and '
        '[simulation.time] covers 364 days: write spinup = "none" under '
        "[flow.sinks_sources.recharge.soil] to start from a full soil, or extend "
        "the run to one year at least."
    )


def test_a_year_long_run_needs_no_refusal() -> None:
    config = SoilReservoirConfig(ru=100.0)

    assert spinup_refusal(config, 365) is None


def test_no_spinup_needs_no_refusal() -> None:
    config = SoilReservoirConfig(ru=100.0, spinup="none")

    assert spinup_refusal(config, 10) is None
