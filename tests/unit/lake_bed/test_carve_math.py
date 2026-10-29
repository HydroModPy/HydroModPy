"""One mesh column is re-graded around a carved lake bed and stays a valid prism."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.spatial.lake_bed.carve_math import (
    regrade_column_active_top,
    regrade_column_to_bed,
)

TOP = 100.0
FIVE_LAYERS = np.array([90.0, 80.0, 70.0, 60.0, 50.0])
UNEVEN = np.array([90.0, 80.0, 50.0])


def _thickness(top: float, botm: np.ndarray) -> np.ndarray:
    return np.concatenate(([top], botm[:-1])) - botm


@pytest.mark.parametrize(("bed", "occupied"), [(85.0, 1), (55.0, 2)], ids=["shallow", "deep"])
def test_the_bed_is_the_bottom_of_the_last_occupied_layer(bed, occupied) -> None:
    """A bed deeper than the original layering still gives a valid column."""
    new = regrade_column_to_bed(
        top=TOP, botm_col=FIVE_LAYERS, bed=bed, occupied_layers=occupied, min_thickness=0.1
    )
    assert new[occupied - 1] == pytest.approx(bed)
    assert new[-1] == pytest.approx(50.0)
    assert np.all(np.diff(new) < 0.0)
    assert np.all(new < TOP)


def test_a_bed_below_the_base_is_clamped_and_every_layer_holds_the_floor() -> None:
    """The floor is per layer: ``[90, 80, 50]`` once split its 2 m segment 0.5 m / 1.5 m."""
    new = regrade_column_to_bed(
        top=TOP, botm_col=UNEVEN, bed=10.0, occupied_layers=1, min_thickness=1.0
    )
    assert new[0] >= 50.0 + 1.0 - 1e-9
    assert np.all(_thickness(TOP, new) >= 1.0 - 1e-9)
    assert new[-1] == pytest.approx(50.0)
    assert np.all(np.diff(new) < 0.0)


def test_the_active_top_regrade_holds_the_floor_on_every_layer() -> None:
    """Same floor guarantee on the active-littoral (marnage) re-grade."""
    new_top, new = regrade_column_active_top(
        orig_top=TOP, botm_col=UNEVEN, bed=10.0, min_thickness=1.0
    )
    assert np.all(_thickness(new_top, new) >= 1.0 - 1e-9)
    assert new[-1] == pytest.approx(50.0)
    assert np.all(np.diff(new) < 0.0)


def test_the_regrade_keeps_the_original_shape_when_there_is_room() -> None:
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
        (regrade_column_to_bed, {"occupied_layers": 0, "min_thickness": 1.0}, "occupied_layers"),
        (regrade_column_to_bed, {"occupied_layers": 3, "min_thickness": 1.0}, "occupied_layers"),
        (regrade_column_to_bed, {"occupied_layers": 1, "min_thickness": 30.0}, "too thin"),
        (regrade_column_active_top, {"min_thickness": 30.0}, "too thin"),
    ],
)
def test_a_column_that_cannot_hold_its_layers_is_refused(regrade, kwargs, match) -> None:
    top = {"top": TOP} if regrade is regrade_column_to_bed else {"orig_top": TOP}
    with pytest.raises(ValueError, match=match):
        regrade(**top, botm_col=UNEVEN, bed=60.0, **kwargs)
