"""A calibration reads the water that leaves the aquifer as a positive number.

MODFLOW signs a budget from the aquifer, so water leaving is negative. The drain outflow inside a
catchment and the release per cell are magnitudes of the negative part. Water that enters releases
nothing, and a value that is not a number counts as no flow.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.solver.modflow_common.calibration_extractors import (
    _drain_outflow_on_mask,
    _positive_release_by_cell,
)


def _rows(nodes, flows) -> np.ndarray:
    rows = np.zeros(len(nodes), dtype=[("node", "<i4"), ("q", "<f8")])
    rows["node"] = nodes
    rows["q"] = flows
    return rows


# One row per drain record: the budget, the catchment mask and the outflow inside it, in the unit
# of the model. A dense array is summed on the mask, and a list record maps its 1-based nodes
# on the plan cells (node - 1) % ncpl, whatever the layer.
_DRAIN = [
    pytest.param(np.array([[-2.0, 3.0, -1.0]]), [True, True, False], 2.0, id="dense_negative_part"),
    pytest.param(np.array([[1.0, 3.0, 0.5]]), [True, True, True], 0.0, id="dense_inflow_only"),
    pytest.param(np.array([[-2.0, -0.0, 0.0]]), [True, True, True], 2.0, id="dense_negative_zero"),
    pytest.param(
        np.array([[-1.0, -1.0, -1.0], [-2.0, 0.0, 4.0]]),
        [True, False, True],
        4.0,
        id="dense_layers_add_up",
    ),
    pytest.param(
        _rows([1, 2, 3], [-2.0, 3.0, -1.0]), [True, True, False], 2.0, id="list_negative_part"
    ),
    pytest.param(
        _rows([1, 4], [-2.0, -3.0]), [True, False, False], 5.0, id="list_node_in_a_second_layer"
    ),
    pytest.param(_rows([2], [-1.0e-12]), [False, True, False], 1.0e-12, id="a_tiny_loss_counts"),
]


@pytest.mark.parametrize(("arr", "mask", "expected"), _DRAIN)
def test_the_drain_outflow_is_the_negative_part_inside_the_catchment(arr, mask, expected) -> None:
    result = _drain_outflow_on_mask(arr, np.array(mask))

    assert result == pytest.approx(expected, abs=1e-18)
    assert result >= 0.0


def test_a_dense_drain_budget_of_another_mesh_is_refused() -> None:
    with pytest.raises(ValueError, match="were not built for the same mesh"):
        _drain_outflow_on_mask(np.zeros((1, 4)), np.array([True, True, True]))


# One row per release field: the signed budget, the number of cells and the positive release
# per cell. A layer is summed onto the cell support.
_RELEASE = [
    pytest.param([-2.0, 3.0, 0.0], None, [2.0, 0.0, 0.0], id="negative_released_positive_kept_out"),
    pytest.param([-2.0, -0.0, -1.0e-12], None, [2.0, 0.0, 1.0e-12], id="signed_zero_and_tiny_loss"),
    pytest.param([np.nan, -1.0, np.inf], None, [0.0, 1.0, 0.0], id="not_a_number_is_no_release"),
    pytest.param([[-1.0, 2.0], [-3.0, -4.0]], 2, [4.0, 4.0], id="layers_added_per_cell"),
    pytest.param([[-1.0, 2.0], [3.0, -4.0]], 2, [1.0, 4.0], id="a_gain_in_one_layer_is_kept_out"),
]


@pytest.mark.parametrize(("signed", "n_cells", "expected"), _RELEASE)
def test_the_release_is_the_negative_part_as_a_positive_number(signed, n_cells, expected) -> None:
    release = _positive_release_by_cell(np.array(signed), n_cells=n_cells)

    np.testing.assert_allclose(release, expected, rtol=1e-12, atol=0.0)
    assert (release >= 0.0).all()


@pytest.mark.parametrize(
    ("signed", "n_cells", "message"),
    [
        pytest.param([1.0, 2.0, 3.0], 2, "multiple of n_cells", id="not_a_multiple"),
        pytest.param([1.0, 2.0], 0, "n_cells must be > 0", id="no_cells"),
    ],
)
def test_a_release_that_cannot_land_on_the_cells_is_refused(signed, n_cells, message) -> None:
    with pytest.raises(ValueError, match=message):
        _positive_release_by_cell(np.array(signed), n_cells=n_cells)
