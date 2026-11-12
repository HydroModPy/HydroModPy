"""Time axes of a transient run (s) and the per-step histories laid on them."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.model.time.history_contract import (
    build_transient_time_axes,
    step_history_from_history,
)


def test_snapshot_times_of_three_steps():
    axes = build_transient_time_axes([10.0, 20.0, 30.0])

    assert axes.n_steps == 3
    assert axes.snapshot_elapsed_seconds.tolist() == [0.0, 10.0, 30.0, 60.0]


def test_history_drops_its_initial_row():
    # A history with n_steps + 1 rows starts from the initial state, which is dropped.
    history = np.asarray([1.0, 2.0, 3.0, 4.0])

    assert step_history_from_history(history, n_steps=3, name="h").tolist() == [2.0, 3.0, 4.0]


def test_history_with_one_row_per_step_is_kept():
    history = np.asarray([[1.0, 2.0], [3.0, 4.0]])

    np.testing.assert_allclose(step_history_from_history(history, n_steps=2, name="h"), history)


def test_refusal_of_a_wrong_row_count():
    with pytest.raises(ValueError, match="expected 3 step rows"):
        step_history_from_history(np.zeros((2, 2)), n_steps=3, name="h")
