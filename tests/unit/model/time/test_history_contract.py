"""Time axes of a transient run (s) and the per-step histories laid on them."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.model.time.history_contract import (
    build_transient_time_axes,
    saturated_thickness_from_head_history,
    snapshot_elapsed_seconds_from_payload,
    step_history_from_history,
)


def test_snapshot_times_of_three_steps():
    axes = build_transient_time_axes([10.0, 20.0, 30.0])

    assert axes.n_steps == 3
    assert axes.snapshot_elapsed_seconds.tolist() == [0.0, 10.0, 30.0, 60.0]


def test_run_without_periods_has_only_its_start():
    axes = build_transient_time_axes([])

    assert axes.n_steps == 0
    assert axes.snapshot_elapsed_seconds.tolist() == [0.0]


def test_history_drops_its_initial_row():
    # A history with n_steps + 1 rows starts from the initial state, which is dropped.
    history = np.asarray([1.0, 2.0, 3.0, 4.0])

    assert step_history_from_history(history, n_steps=3, name="h").tolist() == [2.0, 3.0, 4.0]


def test_history_with_one_row_per_step_is_kept():
    history = np.asarray([[1.0, 2.0], [3.0, 4.0]])

    np.testing.assert_allclose(step_history_from_history(history, n_steps=2, name="h"), history)


SNAPSHOT_AXES = [
    pytest.param(
        {"snapshot_elapsed_seconds": [0.0, 5.0, 9.0]}, None, [0.0, 5.0, 9.0], id="explicit"
    ),
    pytest.param(
        {"snapshot_elapsed_seconds": [0.0, 5.0, 9.0]}, 3, [0.0, 5.0, 9.0], id="explicit, count"
    ),
    # Periods of 10 s and 20 s end at 10 s and 30 s, after the start at 0 s.
    pytest.param({"period_lengths_seconds": [10.0, 20.0]}, 3, [0.0, 10.0, 30.0], id="from periods"),
    pytest.param({"period_lengths_seconds": [10.0, 20.0]}, 4, None, id="periods, wrong count"),
    pytest.param({"snapshot_elapsed_seconds": []}, None, None, id="empty axis"),
    pytest.param({"other": [1.0]}, None, None, id="no axis"),
    pytest.param(
        {"snapshot_elapsed_seconds": [], "period_lengths_seconds": [10.0]},
        None,
        [0.0, 10.0],
        id="empty axis, periods",
    ),
]


@pytest.mark.parametrize(("payload", "n_snapshots", "expected"), SNAPSHOT_AXES)
def test_snapshot_axis_of_a_payload(payload, n_snapshots, expected):
    axis = snapshot_elapsed_seconds_from_payload(payload, n_snapshots=n_snapshots)

    if expected is None:
        assert axis is None
    else:
        assert axis.tolist() == expected


def test_saturated_thickness_is_clipped_to_the_aquifer():
    # Two cells: top 10 / bottom 0 m, and top 5 / bottom 8 m (bottom above top, zero thickness).
    heads = np.array([[4.0, 9.0], [12.0, 6.0], [-3.0, 7.0]])

    thickness = saturated_thickness_from_head_history(
        heads, top_m=np.array([10.0, 5.0]), bottom_m=np.array([0.0, 8.0])
    )

    np.testing.assert_allclose(thickness, [[4.0, 0.0], [10.0, 0.0], [0.0, 0.0]])


REFUSALS = [
    pytest.param(
        step_history_from_history,
        (np.zeros((2, 2)),),
        {"n_steps": 3, "name": "h"},
        "expected 3 step rows",
        id="wrong row count",
    ),
    pytest.param(
        step_history_from_history,
        (np.zeros((2, 2, 2)),),
        {"n_steps": 2, "name": "h"},
        "h must be a 1D or 2D",
        id="3D history",
    ),
    pytest.param(
        snapshot_elapsed_seconds_from_payload,
        ({"snapshot_elapsed_seconds": [0.0, 5.0]},),
        {"n_snapshots": 3},
        "length does not match the requested snapshot count",
        id="axis of another length",
    ),
    pytest.param(
        saturated_thickness_from_head_history,
        (np.zeros(3),),
        {"top_m": np.zeros(3), "bottom_m": np.zeros(3)},
        r"must be \(n_snapshots, n_cells\)",
        id="head history not 2D",
    ),
    pytest.param(
        saturated_thickness_from_head_history,
        (np.zeros((2, 3)),),
        {"top_m": np.zeros(3), "bottom_m": np.zeros(2)},
        "holds 3 cells but top holds 3 and bottom holds 2",
        id="bottom of another size",
    ),
]


@pytest.mark.parametrize(("function", "args", "kwargs", "match"), REFUSALS)
def test_refusals(function, args, kwargs, match):
    with pytest.raises(ValueError, match=match):
        function(*args, **kwargs)
