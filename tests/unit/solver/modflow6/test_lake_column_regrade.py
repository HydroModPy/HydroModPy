"""Re-grading of one mesh column (layer bottoms in m, top at 100 m) around a lake bed.

The new bottoms keep the base, decrease with depth and leave every layer at least
min_thickness (m). A column that cannot hold its layers is refused.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.solver.modflow6.builders.lake_column_regrade import (
    regrade_column_active_top,
    regrade_column_to_bed,
)

TOP = 100.0
FIVE_LAYERS = np.array([90.0, 80.0, 70.0, 60.0, 50.0])
UNEVEN = np.array([90.0, 80.0, 50.0])


def _thickness(top: float, botm: np.ndarray) -> np.ndarray:
    return np.concatenate(([top], botm[:-1])) - botm


@pytest.mark.parametrize(("bed", "occupied"), [(85.0, 1), (55.0, 2)], ids=["shallow", "deep"])
def test_bed_bottoms_last_occupied_layer(bed, occupied) -> None:
    new = regrade_column_to_bed(
        top=TOP, botm_col=FIVE_LAYERS, bed=bed, occupied_layers=occupied, min_thickness=0.1
    )
    assert new[occupied - 1] == pytest.approx(bed)
    assert new[-1] == pytest.approx(50.0)
    assert np.all(np.diff(new) < 0.0)
    assert np.all(new < TOP)


def test_bed_below_base_is_clamped() -> None:
    # The floor is per layer: [90, 80, 50] once split its 2 m segment 0.5 m / 1.5 m.
    new = regrade_column_to_bed(
        top=TOP, botm_col=UNEVEN, bed=10.0, occupied_layers=1, min_thickness=1.0
    )
    assert new[0] >= 50.0 + 1.0 - 1e-9
    assert np.all(_thickness(TOP, new) >= 1.0 - 1e-9)
    assert new[-1] == pytest.approx(50.0)
    assert np.all(np.diff(new) < 0.0)


def test_active_top_regrade_holds_floor() -> None:
    new_top, new = regrade_column_active_top(
        orig_top=TOP, botm_col=UNEVEN, bed=10.0, min_thickness=1.0
    )
    assert np.all(_thickness(new_top, new) >= 1.0 - 1e-9)
    assert new[-1] == pytest.approx(50.0)
    assert np.all(np.diff(new) < 0.0)


def test_original_shape_kept_with_room() -> None:
    new = regrade_column_to_bed(
        top=TOP, botm_col=np.array([90.0, 60.0, 0.0]), bed=90.0, occupied_layers=1,
        min_thickness=0.01,
    )  # fmt: skip
    thickness = _thickness(TOP, new)
    # The active segment keeps the 30 / 60 proportion of the original column.
    assert thickness[2] / thickness[1] == pytest.approx(2.0, rel=1e-3)


@pytest.mark.parametrize(
    ("regrade", "kwargs", "match"),
    [
        pytest.param(
            regrade_column_to_bed,
            {"occupied_layers": 0, "min_thickness": 1.0},
            "occupied_layers",
            id="no occupied layer",
        ),
        pytest.param(
            regrade_column_to_bed,
            {"occupied_layers": 3, "min_thickness": 1.0},
            "occupied_layers",
            id="too many occupied layers",
        ),
        pytest.param(
            regrade_column_to_bed,
            {"occupied_layers": 1, "min_thickness": 30.0},
            "too thin",
            id="column too thin",
        ),
        pytest.param(
            regrade_column_active_top, {"min_thickness": 30.0}, "too thin", id="active top too thin"
        ),
    ],
)
def test_refusals(regrade, kwargs, match) -> None:
    top = {"top": TOP} if regrade is regrade_column_to_bed else {"orig_top": TOP}
    with pytest.raises(ValueError, match=match):
        regrade(**top, botm_col=UNEVEN, bed=60.0, **kwargs)
