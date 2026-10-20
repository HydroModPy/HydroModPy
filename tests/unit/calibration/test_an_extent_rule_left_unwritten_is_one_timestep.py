"""An extent rule a user writes no duration for counts one timestep, on any step.

The first default of the duration rules was "1 d". On a monthly run that made the
dry rule floor(1 d / 1 month) = 0 timestep instead of 1, and on an hourly run it
made both rules 24 timesteps instead of 1. A rule left out is now one timestep,
exactly the count a run made before the rules were durations.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.calibration.config import CalibNetworkExtent
from hydromodpy.core.stream_extent import dry_steps, flowing_steps, parse_extent_duration
from hydromodpy.core.time import nominal_step_days
from hydromodpy.results.derive.network_criterion_settings import (
    DEFAULT_EXTENT_RULES,
    network_criterion_settings,
)
from hydromodpy.results.derive.stream_extent import network_extents_from_run
from tests.unit.results._transient_network_run import transient_run

STEPS = {
    "hourly": nominal_step_days(1, "hour"),
    "daily": nominal_step_days(1, "day"),
    "weekly": nominal_step_days(7, "day"),
    "monthly": nominal_step_days(1, "month"),
}


def test_a_rule_left_out_has_no_duration() -> None:
    extent = CalibNetworkExtent()

    assert (extent.maximal_flowing_duration, extent.minimal_dry_duration) == (None, None)
    assert CalibNetworkExtent(maximal_flowing_duration=None).maximal_flowing_duration is None


@pytest.mark.parametrize("step", STEPS)
def test_no_duration_is_one_flowing_and_one_dry_timestep_on_any_step(step: str) -> None:
    unset = parse_extent_duration(None)

    assert (flowing_steps(unset, STEPS[step]), dry_steps(unset, STEPS[step])) == (1, 1)


def test_a_written_day_is_still_converted_by_the_step() -> None:
    day = parse_extent_duration("1 d")

    assert (flowing_steps(day, STEPS["hourly"]), dry_steps(day, STEPS["hourly"])) == (24, 24)
    assert (flowing_steps(day, STEPS["monthly"]), dry_steps(day, STEPS["monthly"])) == (1, 0)


def test_a_stored_monthly_run_with_no_rule_counts_one_and_one() -> None:
    extents = network_extents_from_run(transient_run())

    assert (extents.maximal_flowing_steps, extents.minimal_dry_steps) == (1, 1)
    assert (extents.maximal_flowing_duration, extents.minimal_dry_duration) == (None, None)


def test_a_stored_run_that_sealed_a_table_without_the_rules_reads_none() -> None:
    run = SimpleNamespace(
        sim_id="sim-x",
        config_snapshot={
            "simulation": {"time": {"step_value": 1, "step_unit": "month"}},
            "calibration": {
                "outputs": {
                    "net": {
                        "support": "network",
                        "observed_network": "data.hydrography",
                        "extent": {"year_quorum": 1.0},
                    }
                }
            },
        },
    )
    rules = network_criterion_settings(run).extent_rules

    assert (rules.maximal_flowing_duration, rules.minimal_dry_duration) == (None, None)
    assert DEFAULT_EXTENT_RULES.maximal_flowing_duration is None
