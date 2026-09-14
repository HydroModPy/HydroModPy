"""A spin-up may only call itself converged on quantities it actually compared.

``cycle_delta`` returned the largest lake-stage change over the lakes present in
both cycles, and ``0.0`` when that set was empty. Two different situations
collapsed onto the same number: a model with no lake at all, where zero is the
truth, and a model whose lake stages could not be read, where zero is a claim
about a comparison that never happened. The loop then declared convergence on a
lake it had never looked at.

The two are told apart: no lake gives ``0.0``, an unreadable one gives nothing,
and the loop refuses to conclude on nothing.
"""

from __future__ import annotations

import pytest

from hydromodpy.project.spinup import lake_stage_delta


def test_no_lake_at_all_is_a_change_of_zero() -> None:
    assert lake_stage_delta({}, {}) == 0.0


def test_a_shared_lake_gives_its_largest_change() -> None:
    assert lake_stage_delta({"cheze": 1.0}, {"cheze": 1.25}) == pytest.approx(0.25)


def test_several_lakes_give_the_largest_of_them() -> None:
    delta = lake_stage_delta({"a": 1.0, "b": 5.0}, {"a": 1.1, "b": 5.9})

    assert delta == pytest.approx(0.9)


def test_a_lake_present_in_one_cycle_only_is_not_a_comparison() -> None:
    assert lake_stage_delta({"cheze": 1.0}, {}) is None
    assert lake_stage_delta({}, {"cheze": 1.0}) is None


def test_two_cycles_naming_different_lakes_is_not_a_comparison() -> None:
    assert lake_stage_delta({"a": 1.0}, {"b": 1.0}) is None


def test_the_result_says_what_a_non_converged_antecedent_is(tmp_path) -> None:
    """`--then-run` seeds production from the last cycle whether it settled or not."""
    from hydromodpy.project.spinup import SpinupCycle, SpinupResult

    result = SpinupResult(
        converged=False,
        cycles=[SpinupCycle(0, "a", "a.zarr", None, None)],
        restart_from="a.zarr",
    )

    assert result.antecedent_warning() is not None
    assert "did not converge" in result.antecedent_warning()


def test_a_converged_result_has_nothing_to_warn_about() -> None:
    from hydromodpy.project.spinup import SpinupCycle, SpinupResult

    result = SpinupResult(
        converged=True,
        cycles=[SpinupCycle(0, "a", "a.zarr", None, None)],
        restart_from="a.zarr",
    )

    assert result.antecedent_warning() is None
