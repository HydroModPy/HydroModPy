"""A start point on a bound still gets a simplex with distinct vertices.

The vertex of an axis is the start plus 10 % of the range, clipped to the
bounds. A start on the upper bound clipped back onto itself and duplicated the
start vertex, so the simplex was flat along that axis.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.calibration.optim.optimizer import build_optimizer
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace


def _space() -> ParameterSpace:
    return ParameterSpace(
        [
            CalibParameter(name="x", lower=0.0, upper=1.0),
            CalibParameter(name="y", lower=-2.0, upper=2.0),
        ]
    )


def _vertices(start_at) -> np.ndarray:
    opt = build_optimizer("scipy_nelder_mead", _space(), seed=0, start_at=start_at)
    return np.array(
        [[s.values["x"], s.values["y"]] for s in opt.ask(3)],
        dtype=float,
    )


def _rank(vertices: np.ndarray) -> int:
    return int(np.linalg.matrix_rank(vertices[1:] - vertices[0]))


@pytest.mark.parametrize(
    "start_at",
    [[1.0, 0.0], [0.0, 2.0], [1.0, 2.0], [0.95, 1.9]],
    ids=["x_on_upper", "y_on_upper", "corner", "inside_one_step"],
)
def test_a_start_on_the_upper_bound_still_spans_the_space(start_at) -> None:
    vertices = _vertices(start_at)

    assert len({tuple(v) for v in vertices}) == 3
    assert _rank(vertices) == 2


def test_a_start_inside_the_box_steps_up_as_before() -> None:
    vertices = _vertices([0.5, 0.0])

    np.testing.assert_allclose(vertices[0], [0.5, 0.0])
    np.testing.assert_allclose(vertices[1], [0.6, 0.0])
    np.testing.assert_allclose(vertices[2], [0.5, 0.4])
