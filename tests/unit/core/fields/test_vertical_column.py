"""The top active layer of a column, and the interfaces a cell can hold."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.fields.vertical_column import check_layer_interfaces


def test_an_active_cell_with_no_thickness_is_refused_and_named() -> None:
    top = np.array([10.0, 10.0])
    botm = np.array([[5.0, 5.0], [0.0, 5.0]])
    with pytest.raises(ValueError, match="layer 1 cell 1"):
        check_layer_interfaces(top, botm, np.ones((2, 2), dtype=int))


def test_an_upside_down_pass_through_cell_is_refused() -> None:
    with pytest.raises(ValueError, match="idomain -1"):
        check_layer_interfaces(
            np.array([10.0]), np.array([[5.0], [6.0], [0.0]]), np.array([[1], [-1], [1]])
        )
