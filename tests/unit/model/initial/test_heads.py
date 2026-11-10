"""The start head on a backend's grid, the restart fill, and the two checks on heads."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.model.initial.heads import (
    build_head_initial_condition_array,
    cycles_have_settled,
    head_rule_of,
    restart_start_heads,
    summarize_head_initial_condition_bounds,
)
from hydromodpy.model.initial.state import (
    CyclicSpinupStrategy,
    CyclicStart,
    HeadRule,
    PriorState,
    SolvedState,
    SteadyStart,
    SteadyStateStrategy,
)

TOP = np.array([10.0, 12.0, 14.0])
BOTTOM = np.array([0.0, 1.0, 2.0])
SHAPE = (2, 3)

ARRAY_CASES = (
    ("top", HeadRule("top"), np.tile(TOP, (2, 1))),
    ("top_offset", HeadRule("top_offset", 0.5), np.tile(TOP - 0.5, (2, 1))),
    ("bottom", HeadRule("bottom"), np.tile(BOTTOM, (2, 1))),
    ("custom", HeadRule("custom", 7.25), np.full(SHAPE, 7.25)),
    ("steady start", SteadyStart(), np.tile(TOP, (2, 1))),
    (
        "prescribed steady start",
        SteadyStart(SteadyStateStrategy("prescribed", None, "first_period", 1e-8)),
        np.tile(TOP, (2, 1)),
    ),
    ("cyclic start", CyclicStart(), np.tile(TOP, (2, 1))),
    (
        "cyclic start from steady",
        CyclicStart(CyclicSpinupStrategy(3, 0.01, "steady_state")),
        np.tile(TOP, (2, 1)),
    ),
)


@pytest.mark.parametrize(
    ("case", "initial", "expected"), ARRAY_CASES, ids=[case for case, _, _ in ARRAY_CASES]
)
def test_a_start_rule_gives_its_array_on_the_grid(case, initial, expected) -> None:
    del case
    head = build_head_initial_condition_array(initial, top=TOP, bottom=BOTTOM, target_shape=SHAPE)

    assert head.dtype == float
    assert head.shape == SHAPE
    np.testing.assert_array_equal(head, expected)


def test_the_array_is_a_fresh_copy_of_the_surface() -> None:
    top = TOP.copy()
    head = build_head_initial_condition_array(
        HeadRule("top"), top=top, bottom=BOTTOM, target_shape=SHAPE
    )
    head[0, 0] = -1.0

    assert top[0] == 10.0


def test_a_surface_that_does_not_broadcast_is_refused_with_its_prefix() -> None:
    with pytest.raises(ValueError, match=r"flow\.ic resolved shape \(2,\) cannot broadcast"):
        build_head_initial_condition_array(
            HeadRule("top"), top=np.ones(2), bottom=BOTTOM, target_shape=SHAPE
        )


RULE_CASES = (
    ("head rule", HeadRule("bottom"), HeadRule("bottom")),
    ("steady start", SteadyStart(), HeadRule("top")),
    ("cyclic start", CyclicStart(), HeadRule("top")),
)


@pytest.mark.parametrize(
    ("case", "initial", "expected"), RULE_CASES, ids=[case for case, _, _ in RULE_CASES]
)
def test_a_steady_or_cyclic_start_begins_at_the_top(case, initial, expected) -> None:
    del case
    assert head_rule_of(initial) == expected


REFUSED = (
    ("prior state", PriorState(np.zeros((1, 3)), {}, "store.zarr"), "PriorState holds"),
    ("solved state", SolvedState(np.zeros((1, 3)), "modflow6"), "SolvedState holds"),
    ("anything else", "top", "Not a start state"),
)


@pytest.mark.parametrize(
    ("case", "initial", "message"), REFUSED, ids=[case for case, _, _ in REFUSED]
)
def test_a_state_that_holds_its_head_is_not_a_rule(case, initial, message) -> None:
    del case
    with pytest.raises(TypeError, match=message):
        head_rule_of(initial)


def test_a_restart_copies_the_prior_head_and_fills_inactive_cells_with_the_top() -> None:
    prior = PriorState(np.array([[5.0, np.nan, 6.0], [4.0, 3.0, np.nan]]), {}, "store.zarr")

    start = restart_start_heads(prior.head, nlay=2, ncpl=3, top=TOP)

    np.testing.assert_array_equal(start, [[5.0, 12.0, 6.0], [4.0, 3.0, 14.0]])
    assert np.isnan(prior.head[0, 1])
    assert start.flags.writeable


def test_a_restart_reads_a_top_of_any_shape_as_its_cells() -> None:
    start = restart_start_heads(
        np.array([[np.nan, 1.0]]), nlay=1, ncpl=2, top=np.array([[8.0], [9.0]])
    )

    np.testing.assert_array_equal(start, [[8.0, 1.0]])


@pytest.mark.parametrize(("nlay", "ncpl"), [(1, 3), (2, 4)])
def test_a_restart_on_another_mesh_is_refused(nlay: int, ncpl: int) -> None:
    with pytest.raises(ValueError, match=r"restart_from: prior head shape \(2, 3\) does not match"):
        restart_start_heads(np.zeros((2, 3)), nlay=nlay, ncpl=ncpl, top=np.zeros(ncpl))


BOUND_CASES = (
    ("inside", np.array([5.0, 6.0, 7.0]), True, 0, 0, 0),
    ("above", np.array([11.0, 6.0, 7.0]), False, 0, 1, 0),
    ("below", np.array([5.0, 0.5, 7.0]), False, 1, 0, 0),
    ("not finite", np.array([5.0, np.nan, 7.0]), False, 0, 0, 1),
)


@pytest.mark.parametrize(
    ("case", "head", "within", "below", "above", "nonfinite"),
    BOUND_CASES,
    ids=[case[0] for case in BOUND_CASES],
)
def test_the_bounds_summary_counts_each_way_out(
    case, head, within, below, above, nonfinite
) -> None:
    del case
    summary = summarize_head_initial_condition_bounds(head=head, top=TOP, bottom=BOTTOM)

    assert summary["within_bounds"] is within
    assert summary["below_bottom_count"] == below
    assert summary["above_top_count"] == above
    assert summary["nonfinite_cell_count"] == nonfinite
    assert summary["cell_count"] == 3


def test_the_bounds_summary_gives_the_largest_gaps() -> None:
    summary = summarize_head_initial_condition_bounds(
        head=np.array([11.5, 0.25, 7.0]), top=TOP, bottom=BOTTOM
    )

    assert summary["max_above_top_m"] == pytest.approx(1.5)
    assert summary["max_below_bottom_m"] == pytest.approx(0.75)
    assert (summary["head_min_m"], summary["head_max_m"]) == (0.25, 11.5)


def test_bounds_that_do_not_broadcast_are_refused() -> None:
    with pytest.raises(ValueError, match="bounds cannot broadcast"):
        summarize_head_initial_condition_bounds(head=np.zeros(3), top=np.zeros(2), bottom=BOTTOM)


SETTLE_CASES = (
    ("first cycle", None, np.zeros(3), 0.01, False),
    ("still", np.zeros(3), np.full(3, 0.005), 0.01, True),
    ("at the tolerance", np.zeros(3), np.full(3, 0.01), 0.01, True),
    ("one cell drifts", np.zeros(3), np.array([0.0, 0.0, 0.5]), 0.01, False),
    ("a cell dries", np.zeros(3), np.array([0.0, np.nan, 0.0]), 0.01, False),
    ("both inactive", np.array([0.0, np.nan]), np.array([0.0, np.nan]), 0.01, True),
    ("nothing active", np.array([np.nan]), np.array([np.nan]), 0.01, False),
)


@pytest.mark.parametrize(
    ("case", "previous", "current", "tol", "expected"),
    SETTLE_CASES,
    ids=[case[0] for case in SETTLE_CASES],
)
def test_two_cycles_settle_on_their_largest_change(case, previous, current, tol, expected):
    del case
    assert cycles_have_settled(previous, current, tol_head_m=tol) is expected


def test_two_cycles_on_different_meshes_are_refused() -> None:
    with pytest.raises(ValueError, match="same mesh"):
        cycles_have_settled(np.zeros(3), np.zeros(4), tol_head_m=0.01)


STAGE_CASES = (
    ("no lake", None, None, True),
    ("still", {"lake": 10.0}, {"lake": 10.005}, True),
    ("at the tolerance", {"lake": 10.0}, {"lake": 10.01}, True),
    ("a lake drifts", {"lake": 10.0, "pond": 3.0}, {"lake": 10.0, "pond": 3.2}, False),
)


@pytest.mark.parametrize(
    ("case", "previous", "current", "expected"),
    STAGE_CASES,
    ids=[case[0] for case in STAGE_CASES],
)
def test_two_cycles_settle_only_when_their_lakes_settle_too(case, previous, current, expected):
    del case
    settled = cycles_have_settled(
        np.zeros(3),
        np.full(3, 0.005),
        tol_head_m=0.01,
        previous_stages=previous,
        current_stages=current,
    )

    assert settled is expected


def test_a_still_lake_does_not_settle_a_drifting_aquifer() -> None:
    settled = cycles_have_settled(
        np.zeros(3),
        np.array([0.0, 0.0, 0.5]),
        tol_head_m=0.01,
        previous_stages={"lake": 10.0},
        current_stages={"lake": 10.0},
    )

    assert settled is False


def test_two_cycles_with_different_lakes_are_refused() -> None:
    with pytest.raises(ValueError, match="same lakes"):
        cycles_have_settled(
            np.zeros(3),
            np.zeros(3),
            tol_head_m=0.01,
            previous_stages={"lake": 1.0},
            current_stages={"pond": 1.0},
        )
