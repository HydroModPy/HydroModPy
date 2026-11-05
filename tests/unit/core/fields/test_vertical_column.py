"""The top active layer of a column, and the interfaces a cell can hold."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.fields.vertical_column import (
    check_layer_interfaces,
    layer_interfaces,
    top_active_layer,
    values_at_layer,
)


def test_the_top_active_layer_skips_inactive_and_pass_through_cells() -> None:
    idomain = np.array(
        [
            [1, 0, -1, 0],
            [1, 1, 1, 0],
            [1, 1, 1, 0],
        ]
    )
    assert top_active_layer(idomain).tolist() == [0, 1, 1, -1]


def test_one_layer_is_a_column_of_one_cell() -> None:
    assert top_active_layer(np.array([1, 0, 1])).tolist() == [0, -1, 0]


def test_values_are_picked_at_the_layer_of_each_column_and_nan_where_there_is_none() -> None:
    values = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
    picked = values_at_layer(values, np.array([1, 0, -1]))
    assert picked[:2].tolist() == [4.0, 2.0]
    assert np.isnan(picked[2])


def test_a_stack_of_steps_is_picked_step_by_step() -> None:
    values = np.arange(12.0).reshape(2, 2, 3)
    picked = values_at_layer(values, np.array([1, 0, 1]))
    np.testing.assert_array_equal(picked, [[3.0, 1.0, 5.0], [9.0, 7.0, 11.0]])


def test_the_interfaces_are_the_top_then_each_bottom() -> None:
    interfaces = layer_interfaces(np.array([10.0, 12.0]), np.array([[5.0, 6.0], [0.0, 1.0]]))
    np.testing.assert_array_equal(interfaces, [[10.0, 12.0], [5.0, 6.0], [0.0, 1.0]])


def test_an_active_cell_with_no_thickness_is_refused_and_named() -> None:
    top = np.array([10.0, 10.0])
    botm = np.array([[5.0, 5.0], [0.0, 5.0]])
    with pytest.raises(ValueError, match="layer 1 cell 1"):
        check_layer_interfaces(top, botm, np.ones((2, 2), dtype=int))


def test_a_flat_pass_through_cell_and_an_inactive_cell_are_not_read() -> None:
    top = np.array([10.0, 10.0])
    botm = np.array([[5.0, 12.0], [5.0, 0.0]])
    # Cell 0 layer 1 is flat but a pass-through; cell 1 layer 0 is upside down but inactive.
    check_layer_interfaces(top, botm, np.array([[1, 0], [-1, 1]]))


def test_an_upside_down_pass_through_cell_is_refused() -> None:
    with pytest.raises(ValueError, match="idomain -1"):
        check_layer_interfaces(
            np.array([10.0]), np.array([[5.0], [6.0], [0.0]]), np.array([[1], [-1], [1]])
        )
