"""Unit tests for hydromodpy.spatial.domain.layering, the shares of the column."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.spatial.domain.layering import assert_bottom_below_top, layer_proportions
from hydromodpy.spatial.domain.layers_config import VerticalGridConfig


def test_a_list_of_proportions_must_sum_to_one():
    with pytest.raises(ValueError, match="sum to 1.0"):
        _ = VerticalGridConfig(genmtd_lay="list", lay_proportions=[0.2, 0.3])


def test_layer_proportions_decay_ends_on_the_bottom_surface():
    allp, nlay = layer_proportions(genmtd_lay="decay", nlay=3, lay_decay=2.0)
    assert nlay == 3
    assert np.all(np.diff(allp) > 0)
    assert allp[-1] == pytest.approx(1.0)


def test_layer_proportions_constant_and_list():
    allp, nlay = layer_proportions(genmtd_lay="constant", nlay=4)
    assert nlay == 4
    assert np.allclose(allp, [0.25, 0.5, 0.75, 1.0])
    allp, nlay = layer_proportions(genmtd_lay="list", lay_proportions=[0.1, 0.2, 0.3, 0.4])
    assert nlay == 4
    assert np.allclose(allp, [0.1, 0.3, 0.6, 1.0])
    with pytest.raises(ValueError, match="Unsupported genmtd_lay"):
        layer_proportions(genmtd_lay="spline", nlay=2)


def test_assert_bottom_below_top_names_the_violations():
    top = np.array([[10.0, 10.0]])
    assert_bottom_below_top(top=top, bot=np.array([[4.0, 5.0]]), nodata=-9999.0)
    with pytest.raises(ValueError, match=r"1/2 violations"):
        assert_bottom_below_top(top=top, bot=np.array([[4.0, 10.0]]), nodata=-9999.0)
    with pytest.raises(ValueError, match="No finite overlapping valid cells"):
        assert_bottom_below_top(top=top, bot=np.full((1, 2), -9999.0), nodata=-9999.0)
