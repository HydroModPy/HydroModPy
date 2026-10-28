"""The layer bottoms and ``idomain`` of a layering, by shares of the column or by surfaces.

A layering by surfaces gives each layer its base, and a thin layer pinches out. The bases come from a thickness below the layer above, a depth below the terrain,
an elevation or a raster, and the last layer ends on the base of the aquifer. A
cell thinner than the minimum of its layer becomes a pass-through cell
(``idomain = -1``) whose thickness goes to its active neighbour, or keeps the
minimum and pushes the layers below down.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.vertical_column import check_layer_interfaces
from hydromodpy.spatial.domain.layering import (
    assert_bottom_below_top,
    base_interfaces,
    coerce_vertical_config,
    layer_proportions,
    layer_stack,
    pinch_out,
)
from hydromodpy.spatial.domain.layers_config import VerticalGridConfig

NODATA = -9999.0


def _layers(*tables: dict, pinch_out: str = "pass_through") -> VerticalGridConfig:
    return VerticalGridConfig.model_validate(
        {"genmtd_lay": "surfaces", "layer": list(tables), "pinch_out": pinch_out}
    )


def test_each_kind_of_base_places_its_interface() -> None:
    top = np.array([100.0, 90.0])
    bottom = np.array([20.0, 20.0])
    layers = _layers(
        {"name": "a", "depth": 5.0},
        {"name": "b", "thickness": 10.0},
        {"name": "c", "elevation": 60.0},
        {"name": "d", "surface": "rock"},
        {"name": "e"},
    ).layer

    z = base_interfaces(
        top=top, bottom=bottom, layers=layers, bases={"rock": np.array([50.0, 45.0])}
    )

    np.testing.assert_allclose(z[:, 0], [100.0, 95.0, 85.0, 60.0, 50.0, 20.0])
    np.testing.assert_allclose(z[:, 1], [90.0, 85.0, 75.0, 60.0, 45.0, 20.0])


def test_a_base_stays_between_the_base_of_the_aquifer_and_the_layer_above() -> None:
    top = np.array([100.0])
    bottom = np.array([40.0])
    layers = _layers(
        {"name": "a", "elevation": 120.0}, {"name": "b", "depth": 80.0}, {"name": "c"}
    ).layer

    z = base_interfaces(top=top, bottom=bottom, layers=layers, bases={})

    np.testing.assert_allclose(z[:, 0], [100.0, 100.0, 40.0, 40.0])


@pytest.mark.parametrize(
    ("bases", "match"),
    [
        ({"rock": np.array([50.0, np.nan])}, "no value on 1 cell"),
        ({}, "reads the base surface 'rock'"),
    ],
    ids=["a_cell_without_value", "an_undeclared_base"],
)
def test_a_raster_base_that_cannot_place_every_cell_is_refused(bases, match) -> None:
    layers = _layers({"name": "a", "surface": "rock"}, {"name": "b"}).layer

    with pytest.raises(ValueError, match=match):
        base_interfaces(
            top=np.array([100.0, 100.0]), bottom=np.array([0.0, 0.0]), layers=layers, bases=bases
        )


def test_a_thin_cell_passes_through_and_the_cell_below_takes_its_thickness() -> None:
    z = np.array([[100.0, 100.0], [99.7, 90.0], [60.0, 60.0], [20.0, 20.0]])

    stack = pinch_out(z, [0.5, 0.5, 0.5], mode="pass_through")

    np.testing.assert_array_equal(stack.idomain[:, 0], [-1, 1, 1])
    np.testing.assert_array_equal(stack.idomain[:, 1], [1, 1, 1])
    np.testing.assert_allclose(stack.botm[:, 0], [100.0, 60.0, 20.0])
    np.testing.assert_allclose(stack.botm[:, 1], [90.0, 60.0, 20.0])
    check_layer_interfaces(z[0], stack.botm, stack.idomain)


def test_a_thin_cell_at_the_base_gives_its_thickness_to_the_cell_above() -> None:
    z = np.array([[100.0], [80.0], [40.2], [40.0]])

    stack = pinch_out(z, [0.5, 0.5, 0.5], mode="pass_through")

    np.testing.assert_array_equal(stack.idomain[:, 0], [1, 1, -1])
    np.testing.assert_allclose(stack.botm[:, 0], [80.0, 40.0, 40.0])


def test_a_column_of_thin_layers_keeps_its_thickest_one() -> None:
    z = np.array([[100.0], [99.8], [99.5], [99.4]])

    stack = pinch_out(z, [1.0, 1.0, 1.0], mode="pass_through")

    np.testing.assert_array_equal(stack.idomain[:, 0], [-1, 1, -1])
    np.testing.assert_allclose(stack.botm[:, 0], [100.0, 99.4, 99.4])


def test_keeping_the_minimum_thickness_pushes_the_layers_below_down() -> None:
    z = np.array([[100.0, 100.0], [99.7, 90.0], [60.0, 60.0], [59.9, 20.0]])

    stack = pinch_out(z, [0.5, 0.5, 1.0], mode="keep_min_thickness")

    np.testing.assert_array_equal(stack.idomain, np.ones((3, 2), dtype=int))
    np.testing.assert_allclose(stack.botm[:, 0], [99.5, 60.0, 59.0])
    np.testing.assert_allclose(stack.botm[:, 1], [90.0, 60.0, 20.0])


def test_the_stack_gives_cells_outside_the_domain_no_layer() -> None:
    layers = _layers({"name": "a", "depth": 50.0}, {"name": "b"})
    top = np.array([100.0, NODATA])
    bottom = np.array([60.0, NODATA])

    stack = layer_stack(
        top=top, bottom=bottom, invalid=top <= NODATA, vertical_config=layers, nodata=NODATA
    )

    # The base of 'a' falls below the aquifer, so 'b' is empty and gives way to 'a'.
    np.testing.assert_array_equal(stack.idomain, [[1, 0], [-1, 0]])
    np.testing.assert_allclose(stack.botm[:, 1], [NODATA, NODATA])
    np.testing.assert_allclose(stack.botm[:, 0], [60.0, 60.0])


def test_a_layer_base_at_the_nodata_sentinel_is_a_missing_value() -> None:
    layers = _layers({"name": "a", "surface": "rock"}, {"name": "b"})
    top = np.array([100.0])

    with pytest.raises(ValueError, match="no value on 1 cell"):
        layer_stack(
            top=top,
            bottom=np.array([0.0]),
            invalid=np.array([False]),
            vertical_config=layers,
            bases={"rock": np.array([NODATA])},
            nodata=NODATA,
        )


def test_shares_of_the_column_keep_their_bottoms_and_activate_every_valid_cell() -> None:
    top = np.array([[100.0, 80.0], [NODATA, 70.0]])
    bottom = np.array([[40.0, 20.0], [NODATA, 10.0]])
    vertical = VerticalGridConfig(genmtd_lay="decay", nlay=3, lay_decay=2.0)

    stack = layer_stack(
        top=top, bottom=bottom, invalid=top <= NODATA, vertical_config=vertical, nodata=NODATA
    )

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
        (lambda: layer_proportions(genmtd_lay="spline", nlay=2), ValueError, "Unsupported genmtd_lay"),
        (lambda: pinch_out(np.zeros((2, 1)), [1.0], mode="erode"), ValueError, "Unsupported pinch_out 'erode'"),
        (lambda: coerce_vertical_config("constant"), TypeError, "must be None, VerticalGridConfig, or a mapping"),
    ],
    ids=["layering", "pinch_out", "vertical_config"],
)  # fmt: skip
def test_an_unknown_layering_mode_is_refused(call, error, match):
    with pytest.raises(error, match=match):
        call()


def test_a_vertical_config_is_read_from_none_a_table_or_itself():
    table = VerticalGridConfig(genmtd_lay="constant", nlay=3)

    assert coerce_vertical_config(None) == VerticalGridConfig()
    assert coerce_vertical_config({"genmtd_lay": "constant", "nlay": 3}) == table
    assert coerce_vertical_config(table) is table


def test_assert_bottom_below_top_names_the_violations():
    top = np.array([[10.0, 10.0]])
    assert_bottom_below_top(top=top, bot=np.array([[4.0, 5.0]]), nodata=NODATA)
    with pytest.raises(ValueError, match=r"1/2 violations"):
        assert_bottom_below_top(top=top, bot=np.array([[4.0, 10.0]]), nodata=NODATA)
    with pytest.raises(ValueError, match="No finite overlapping valid cells"):
        assert_bottom_below_top(top=top, bot=np.full((1, 2), NODATA), nodata=NODATA)
