"""A layering by surfaces gives each layer its base, and a thin layer pinches out.

The bases come from a thickness below the layer above, a depth below the terrain,
an elevation or a raster, and the last layer ends on the base of the aquifer. A
cell thinner than the minimum of its layer becomes a pass-through cell
(``idomain = -1``) whose thickness goes to its active neighbour, or keeps the
minimum and pushes the layers below down.
"""

from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from hydromodpy.core.vertical_column import (
    VERTICAL_LAYOUT_COLUMN_FRACTIONS,
    VERTICAL_LAYOUT_SURFACES,
    check_layer_interfaces,
)
from hydromodpy.spatial.mesh.cartesian_grid.layer_surfaces import base_interfaces, pinch_out
from hydromodpy.spatial.mesh.cartesian_grid.sgrid_config import VerticalGridConfig
from hydromodpy.spatial.mesh.cartesian_grid.sgrid_generation import layer_stack

NODATA = -9999.0


def _layers(*tables: dict, pinch_out: str = "pass_through") -> VerticalGridConfig:
    return VerticalGridConfig.model_validate(
        {"genmtd_lay": "surfaces", "layer": list(tables), "pinch_out": pinch_out}
    )


def test_every_layer_but_the_last_gives_its_base_with_one_key() -> None:
    with pytest.raises(ValidationError, match="gives no base"):
        _layers({"name": "weathered"}, {"name": "bedrock"})
    with pytest.raises(ValidationError, match="ends on the base of the aquifer"):
        _layers({"name": "weathered", "depth": 5.0})
    with pytest.raises(ValidationError, match="one key only"):
        _layers({"name": "weathered", "depth": 5.0, "elevation": 40.0}, {"name": "bedrock"})
    with pytest.raises(ValidationError, match="names a layer twice"):
        _layers({"name": "rock", "depth": 5.0}, {"name": "rock"})


def test_layer_tables_are_read_only_with_the_surfaces_layering() -> None:
    with pytest.raises(ValidationError, match="read only with genmtd_lay = 'surfaces'"):
        VerticalGridConfig.model_validate(
            {"genmtd_lay": "constant", "nlay": 2, "layer": [{"name": "rock"}]}
        )


def test_the_layering_by_surfaces_counts_its_tables_and_names_its_layout() -> None:
    layers = _layers(
        {"name": "weathered", "surface": "weathered_base"},
        {"name": "fissured", "thickness": "30 m"},
        {"name": "bedrock"},
    )

    assert layers.layer_count == 3
    assert layers.nlay is None
    assert layers.base_surface_names == ("weathered_base",)
    assert layers.vertical_layout == VERTICAL_LAYOUT_SURFACES
    assert layers.has_pass_through_cells
    assert VerticalGridConfig().vertical_layout == VERTICAL_LAYOUT_COLUMN_FRACTIONS


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


def test_a_raster_base_without_a_value_on_a_cell_is_refused() -> None:
    layers = _layers({"name": "a", "surface": "rock"}, {"name": "b"}).layer

    with pytest.raises(ValueError, match="no value on 1 cell"):
        base_interfaces(
            top=np.array([100.0, 100.0]),
            bottom=np.array([0.0, 0.0]),
            layers=layers,
            bases={"rock": np.array([50.0, np.nan])},
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
