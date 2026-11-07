"""The layer bottoms and ``idomain`` of a layering, by shares of the column or by surfaces.

A base comes from a thickness, a depth, an elevation or a raster, and the last layer ends on the
aquifer base. A cell thinner than its minimum passes through (``idomain = -1``) and gives its
thickness to its active neighbor, or keeps the minimum and pushes the layers below down.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.fields.vertical_column import check_layer_interfaces
from hydromodpy.model.domain.layering import (
    assert_bottom_below_top,
    base_interfaces,
    coerce_vertical_config,
    layer_proportions,
    layer_stack,
    pinch_out,
)
from hydromodpy.model.domain.layers_config import VerticalGridConfig
from tests._helpers.domain_cases import NODATA, surfaces_table


def _layers(*tables: dict) -> VerticalGridConfig:
    return VerticalGridConfig.model_validate(surfaces_table(*tables))


ROCK = _layers({"name": "a", "surface": "rock"}, {"name": "b"})


@pytest.mark.parametrize(
    ("top", "bottom", "tables", "bases", "z"),
    [
        ([100.0, 90.0], [20.0, 20.0], [{"name": "a", "depth": 5.0}, {"name": "b", "thickness": 10.0}, {"name": "c", "elevation": 60.0}, {"name": "d", "surface": "rock"}, {"name": "e"}],
         {"rock": np.array([50.0, 45.0])}, [[100.0, 90.0], [95.0, 85.0], [85.0, 75.0], [60.0, 60.0], [50.0, 45.0], [20.0, 20.0]]),
        ([100.0], [40.0], [{"name": "a", "elevation": 120.0}, {"name": "b", "depth": 80.0}, {"name": "c"}], {}, [[100.0], [100.0], [40.0], [40.0]]),
    ],
    ids=["each_kind_of_base_places_its_interface", "a_base_stays_between_the_aquifer_base_and_the_layer_above"],
)  # fmt: skip
def test_the_bases_place_the_interfaces(top, bottom, tables, bases, z) -> None:
    layers = _layers(*tables).layer

    placed = base_interfaces(top=np.array(top), bottom=np.array(bottom), layers=layers, bases=bases)

    np.testing.assert_allclose(placed, z)


@pytest.mark.parametrize(
    ("z", "minimum", "mode", "idomain", "botm"),
    [
        ([[100.0, 100.0], [99.7, 90.0], [60.0, 60.0], [20.0, 20.0]], [0.5, 0.5, 0.5], "pass_through", [[-1, 1], [1, 1], [1, 1]], [[100.0, 90.0], [60.0, 60.0], [20.0, 20.0]]),
        ([[100.0], [80.0], [40.2], [40.0]], [0.5, 0.5, 0.5], "pass_through", [[1], [1], [-1]], [[80.0], [40.0], [40.0]]),
        ([[100.0], [99.8], [99.5], [99.4]], [1.0, 1.0, 1.0], "pass_through", [[-1], [1], [-1]], [[100.0], [99.4], [99.4]]),
        ([[100.0, 100.0], [99.7, 90.0], [60.0, 60.0], [59.9, 20.0]], [0.5, 0.5, 1.0], "keep_min_thickness", [[1, 1], [1, 1], [1, 1]], [[99.5, 90.0], [60.0, 60.0], [59.0, 20.0]]),
    ],
    ids=["a_thin_cell_passes_through_and_the_cell_below_takes_its_thickness", "a_thin_cell_at_the_base_gives_its_thickness_to_the_cell_above",
         "a_column_of_thin_layers_keeps_its_thickest_one", "keeping_the_minimum_thickness_pushes_the_layers_below_down"],
)  # fmt: skip
def test_a_thin_cell_pinches_out(z, minimum, mode, idomain, botm) -> None:
    z = np.array(z)

    stack = pinch_out(z, minimum, mode=mode)

    np.testing.assert_array_equal(stack.idomain, idomain)
    np.testing.assert_allclose(stack.botm, botm)
    check_layer_interfaces(z[0], stack.botm, stack.idomain)


def test_the_stack_gives_cells_outside_the_domain_no_layer() -> None:
    layers = _layers({"name": "a", "depth": 50.0}, {"name": "b"})
    top = np.array([100.0, NODATA])
    bottom = np.array([60.0, NODATA])

    stack = layer_stack(top=top, bottom=bottom, invalid=top <= NODATA, vertical_config=layers, nodata=NODATA)  # fmt: skip

    # The base of 'a' falls below the aquifer, so 'b' is empty and gives way to 'a'.
    np.testing.assert_array_equal(stack.idomain, [[1, 0], [-1, 0]])
    np.testing.assert_allclose(stack.botm, [[60.0, NODATA], [60.0, NODATA]])


def test_shares_of_the_column_keep_their_bottoms_and_activate_every_valid_cell() -> None:
    top = np.array([[100.0, 80.0], [NODATA, 70.0]])
    bottom = np.array([[40.0, 20.0], [NODATA, 10.0]])
    vertical = VerticalGridConfig(genmtd_lay="decay", nlay=3, lay_decay=2.0)

    stack = layer_stack(top=top, bottom=bottom, invalid=top <= NODATA, vertical_config=vertical, nodata=NODATA)  # fmt: skip

    allp = (1 - 2.0 ** np.arange(1, 4)) / (1 - 2.0**3)
    expected = top[None] - (top - bottom)[None] * allp[:, None, None]
    expected[:, 1, 0] = NODATA
    np.testing.assert_array_equal(stack.botm, expected)
    np.testing.assert_array_equal(stack.idomain[:, 1, 0], [0, 0, 0])
    assert (stack.idomain[:, [0, 0, 1], [0, 1, 1]] == 1).all()


@pytest.mark.parametrize(
    ("kwargs", "allp"),
    [
        ({"genmtd_lay": "constant", "nlay": 4}, [0.25, 0.5, 0.75, 1.0]),
        ({"genmtd_lay": "list", "lay_proportions": [0.1, 0.2, 0.3, 0.4]}, [0.1, 0.3, 0.6, 1.0]),
        ({"genmtd_lay": "decay", "nlay": 3, "lay_decay": 2.0}, [1 / 7, 3 / 7, 1.0]),
    ],
    ids=["constant", "list", "decay"],
)
def test_the_shares_of_the_column_end_on_the_bottom_surface(kwargs, allp):
    shares, nlay = layer_proportions(**kwargs)

    assert nlay == len(allp)
    np.testing.assert_allclose(shares, allp)
    assert np.all(np.diff(shares) > 0)


@pytest.mark.parametrize(
    ("call", "error", "match"),
    [
        (lambda: base_interfaces(top=np.array([100.0, 100.0]), bottom=np.array([0.0, 0.0]), layers=ROCK.layer, bases={"rock": np.array([50.0, np.nan])}), ValueError, "no value on 1 cell"),
        (lambda: base_interfaces(top=np.array([100.0, 100.0]), bottom=np.array([0.0, 0.0]), layers=ROCK.layer, bases={}), ValueError, "reads the base surface 'rock'"),
        (lambda: layer_stack(top=np.array([100.0]), bottom=np.array([0.0]), invalid=np.array([False]), vertical_config=ROCK, bases={"rock": np.array([NODATA])}, nodata=NODATA),
         ValueError, "no value on 1 cell"),
        (lambda: layer_proportions(genmtd_lay="spline", nlay=2), ValueError, "Unsupported genmtd_lay"),
        (lambda: pinch_out(np.zeros((2, 1)), [1.0], mode="erode"), ValueError, "Unsupported pinch_out 'erode'"),
        (lambda: coerce_vertical_config("constant"), TypeError, "must be None, VerticalGridConfig, or a mapping"),
    ],
    ids=["a_base_cell_without_value", "an_undeclared_base", "a_base_at_the_nodata_sentinel", "unknown_layering", "unknown_pinch_out", "not_a_vertical_config"],
)  # fmt: skip
def test_a_layering_that_cannot_be_built_is_refused(call, error, match):
    with pytest.raises(error, match=match):
        call()


def test_a_vertical_config_is_read_from_none_a_table_or_itself_and_a_bottom_above_the_top_is_named():
    table = VerticalGridConfig(genmtd_lay="constant", nlay=3)

    assert coerce_vertical_config(None) == VerticalGridConfig()
    assert coerce_vertical_config({"genmtd_lay": "constant", "nlay": 3}) == table
    assert coerce_vertical_config(table) is table
    top = np.array([[10.0, 10.0]])
    assert_bottom_below_top(top=top, bot=np.array([[4.0, 5.0]]), nodata=NODATA)
    with pytest.raises(ValueError, match=r"1/2 violations"):
        assert_bottom_below_top(top=top, bot=np.array([[4.0, 10.0]]), nodata=NODATA)
    with pytest.raises(ValueError, match="No finite overlapping valid cells"):
        assert_bottom_below_top(top=top, bot=np.full((1, 2), NODATA), nodata=NODATA)
