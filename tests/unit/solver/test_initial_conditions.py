from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.solver.initial_conditions import (
    summarize_head_initial_condition_bounds,
)


def test_summarize_head_initial_condition_bounds_reports_valid_field() -> None:
    summary = summarize_head_initial_condition_bounds(
        head=np.asarray([2.0, 3.0, 4.0]),
        top=np.asarray([5.0, 5.0, 5.0]),
        bottom=np.asarray([1.0, 2.0, 3.0]),
    )

    assert summary["cell_count"] == 3
    assert summary["finite_cell_count"] == 3
    assert summary["nonfinite_cell_count"] == 0
    assert summary["below_bottom_count"] == 0
    assert summary["above_top_count"] == 0
    assert summary["max_below_bottom_m"] == pytest.approx(0.0)
    assert summary["max_above_top_m"] == pytest.approx(0.0)
    assert summary["head_min_m"] == pytest.approx(2.0)
    assert summary["head_max_m"] == pytest.approx(4.0)
    assert summary["within_bounds"] is True


def test_summarize_head_initial_condition_bounds_reports_violations() -> None:
    summary = summarize_head_initial_condition_bounds(
        head=np.asarray([0.0, 6.0, 3.0, np.nan]),
        top=np.asarray([5.0, 5.0, 5.0, 5.0]),
        bottom=np.asarray([1.0, 1.0, 4.0, 1.0]),
    )

    assert summary["cell_count"] == 4
    assert summary["finite_cell_count"] == 3
    assert summary["nonfinite_cell_count"] == 1
    assert summary["below_bottom_count"] == 2
    assert summary["above_top_count"] == 1
    assert summary["max_below_bottom_m"] == pytest.approx(1.0)
    assert summary["max_above_top_m"] == pytest.approx(1.0)
    assert summary["head_min_m"] == pytest.approx(0.0)
    assert summary["head_max_m"] == pytest.approx(6.0)
    assert summary["within_bounds"] is False


def test_summarize_head_initial_condition_bounds_rejects_shape_mismatch() -> None:
    with pytest.raises(ValueError, match="bounds cannot broadcast"):
        summarize_head_initial_condition_bounds(
            head=np.zeros((2, 3)),
            top=np.zeros((4,)),
            bottom=np.zeros((2, 3)),
        )
