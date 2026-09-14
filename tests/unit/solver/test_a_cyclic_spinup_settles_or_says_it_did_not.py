"""Repeating the run's own period until the state stops moving.

A steady solve carries the forcing's mean and none of its history, which is the
wrong antecedent for an aquifer whose response time is long against the record. The
cycles are auxiliary solves inside one run, exactly as the steady initialization
already is, which is what lets a calibration trial use them: nothing touches the
run's store.

What is gated here is the loop's bookkeeping and its two honesty rules, with no
solver: how many cycles run, that the largest change decides and not the mean, and
that a loop out of cycles hands back its last state while saying it did not settle.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.physics.flow.initial_conditions import FlowInitialConditions
from hydromodpy.solver.steady_initial_conditions import (
    cycles_have_settled,
    cyclic_flow_copy_for_initialization,
    cyclic_spinup_strategy,
    flow_uses_cyclic_spinup,
)


def _flow(**ic):
    payload = {"type": "spinup_cyclic", **ic}
    return SimpleNamespace(initial_conditions=FlowInitialConditions.model_validate({"h": payload}))


class TestTheDeclaration:
    def test_the_type_is_recognised(self) -> None:
        assert flow_uses_cyclic_spinup(_flow()) is True

    def test_another_initial_condition_is_not(self) -> None:
        other = SimpleNamespace(
            initial_conditions=FlowInitialConditions.model_validate({"h": {"type": "top"}})
        )
        assert flow_uses_cyclic_spinup(other) is False

    def test_the_tolerance_carries_its_unit(self) -> None:
        assert cyclic_spinup_strategy(_flow(tol_head="2 cm")).tol_head_m == pytest.approx(0.02)

    def test_the_defaults_are_a_real_strategy(self) -> None:
        strategy = cyclic_spinup_strategy(_flow())
        assert strategy.max_cycles >= 1
        assert strategy.tol_head_m > 0.0
        assert strategy.first_cycle_from == "top"

    def test_a_first_cycle_source_it_does_not_know_is_refused(self) -> None:
        with pytest.raises(ValueError):
            FlowInitialConditions.model_validate(
                {"h": {"type": "spinup_cyclic", "first_cycle_from": "yesterday"}}
            )


class TestWhatCountsAsSettled:
    def test_the_largest_change_decides_not_the_mean(self) -> None:
        # A basin settled on average while one compartment still drifts has not
        # settled, and averaging is how that gets missed.
        before = np.zeros(100)
        after = np.zeros(100)
        after[42] = 5.0
        assert cycles_have_settled(before, after, tol_head_m=0.01) is False

    def test_a_change_under_the_tolerance_everywhere_is_settled(self) -> None:
        before = np.linspace(10.0, 20.0, 50)
        assert cycles_have_settled(before, before + 0.005, tol_head_m=0.01) is True

    def test_the_first_cycle_has_nothing_to_compare_to(self) -> None:
        assert cycles_have_settled(None, np.zeros(5), tol_head_m=1.0) is False

    def test_a_cell_that_wetted_between_cycles_is_a_change(self) -> None:
        # Dry in one and wet in the other is the state moving, not a missing value.
        before = np.array([1.0, np.nan, 3.0])
        after = np.array([1.0, 2.0, 3.0])
        assert cycles_have_settled(before, after, tol_head_m=10.0) is False

    def test_two_meshes_of_different_size_are_refused(self) -> None:
        with pytest.raises(ValueError, match="same mesh"):
            cycles_have_settled(np.zeros(3), np.zeros(4), tol_head_m=1.0)

    def test_a_field_that_is_entirely_inactive_never_counts_as_settled(self) -> None:
        nans = np.full(4, np.nan)
        assert cycles_have_settled(nans, nans, tol_head_m=1.0) is False


class TestTheCycleDoesNotSpawnItsOwn:
    """The defect that a real run found, and the only gate that catches it early."""

    def test_a_cycle_s_flow_no_longer_asks_for_cycling(self) -> None:
        # Measured before this was fixed: each auxiliary model re-entered the same
        # hook, so a three-cycle spin-up ran 143 solves and was stopped by the
        # machine rather than by the loop.
        cycle_flow = cyclic_flow_copy_for_initialization(_flow(max_cycles=3))
        assert flow_uses_cyclic_spinup(cycle_flow) is False

    def test_the_cycle_starts_from_the_top_surface(self) -> None:
        # The caller overwrites it with the previous cycle's heads; what matters is
        # that the copy carries a type the hook does not fire on.
        cycle_flow = cyclic_flow_copy_for_initialization(_flow())
        assert cycle_flow.initial_conditions.h.type == "top"

    def test_the_original_flow_is_left_alone(self) -> None:
        flow = _flow(max_cycles=2)
        cyclic_flow_copy_for_initialization(flow)
        assert flow_uses_cyclic_spinup(flow) is True
