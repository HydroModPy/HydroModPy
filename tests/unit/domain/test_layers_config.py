"""``[domain.layers]``, the one layering table every solver reads.

The layering is never a key of a solver ``sgrid`` table: that refusal is in
``tests/unit/solver/modflow_grid/test_sgrid_config.py``.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.core.vertical_column import (
    VERTICAL_LAYOUT_COLUMN_FRACTIONS,
    VERTICAL_LAYOUT_SURFACES,
)
from hydromodpy.spatial.domain.domain_config import DomainConfig
from hydromodpy.spatial.domain.layers_config import VerticalGridConfig


def _surfaces(*tables: dict) -> dict:
    return {"genmtd_lay": "surfaces", "layer": list(tables)}


def test_domain_layers_defaults_to_one_constant_layer():
    layers = DomainConfig().layers

    assert isinstance(layers, VerticalGridConfig)
    assert (layers.genmtd_lay, layers.nlay, layers.layer_count) == ("constant", 1, 1)
    assert layers.vertical_layout == VERTICAL_LAYOUT_COLUMN_FRACTIONS
    assert layers.base_surface_names == ()
    assert not layers.has_pass_through_cells


@pytest.mark.parametrize(
    ("table", "count", "read"),
    [
        (
            {"genmtd_lay": "decay", "nlay": 4.0, "lay_decay": "1.5"},
            4,
            {"nlay": 4, "lay_decay": 1.5},
        ),
        ({"genmtd_lay": "constant", "nlay": 3}, 3, {"nlay": 3, "lay_decay": None}),
        (
            {"genmtd_lay": "list", "lay_proportions": [0.25, 0.75]},
            2,
            {"nlay": None, "lay_proportions": [0.25, 0.75]},
        ),
    ],
    ids=["decay_with_a_float_count", "constant", "list"],
)
def test_domain_layers_validates_its_table_and_counts_its_layers(table, count, read):
    layers = DomainConfig.model_validate({"layers": table}).layers

    assert layers.layer_count == count
    assert {key: getattr(layers, key) for key in read} == read
    assert VerticalGridConfig.from_mapping(table) == layers


def test_the_layering_by_surfaces_counts_its_tables_and_names_its_layout():
    layers = VerticalGridConfig.model_validate(
        _surfaces(
            {"name": "weathered", "surface": "weathered_base"},
            {"name": "fissured", "thickness": "30 m"},
            {"name": "bedrock"},
        )
    )

    assert layers.layer_count == 3
    assert layers.nlay is None
    assert layers.base_surface_names == ("weathered_base",)
    assert layers.vertical_layout == VERTICAL_LAYOUT_SURFACES
    assert layers.has_pass_through_cells


@pytest.mark.parametrize(
    "table", [{"genmtd_lay": "list", "lay_proportions": [0.5, 0.5]}, _surfaces({"name": "rock"})]
)
def test_a_layer_count_beside_a_layering_that_derives_it_is_ignored_with_a_warning(table):
    with pytest.warns(UserWarning, match="nlay must not be provided"):
        layers = VerticalGridConfig.model_validate({**table, "nlay": 5})

    assert layers.nlay is None


@pytest.mark.parametrize(
    ("table", "match"),
    [
        ({"nlay": 0}, "nlay must be >= 1"),
        ({"nlay": True}, "got bool"),
        ({"nlay": 2.5}, "must be an integer value, got 2.5"),
        ({"nlay": "two"}, "must be an integer value, got <class 'str'>"),
        ({"nlay": None}, "nlay is required"),
        ({"genmtd_lay": "decay", "nlay": 3}, "lay_decay is required"),
        ({"genmtd_lay": "decay", "nlay": 3, "lay_decay": 1.0}, "lay_decay must be > 1.0"),
        ({"genmtd_lay": "list"}, "lay_proportions is required"),
        ({"genmtd_lay": "list", "lay_proportions": []}, "cannot be empty"),
        ({"genmtd_lay": "list", "lay_proportions": [1.5, -0.5]}, "strictly positive"),
        ({"genmtd_lay": "list", "lay_proportions": [0.2, 0.3]}, "sum to 1.0"),
        ({"genmtd_lay": "surfaces"}, "needs at least one"),
        (_surfaces({"name": "weathered"}, {"name": "bedrock"}), "gives no base"),
        (_surfaces({"name": "weathered", "depth": 5.0}), "ends on the base of the aquifer"),
        (_surfaces({"name": "weathered", "depth": 5.0, "elevation": 40.0}, {"name": "bedrock"}), "one key only"),
        (_surfaces({"name": "rock", "depth": 5.0}, {"name": "rock"}), "names a layer twice"),
        ({"genmtd_lay": "constant", "nlay": 2, "layer": [{"name": "rock"}]}, "read only with genmtd_lay = 'surfaces'"),
    ],
)  # fmt: skip
def test_a_layering_table_that_does_not_stack_is_refused(table, match):
    with pytest.raises(ValidationError, match=match):
        VerticalGridConfig.model_validate(table)


def test_a_layering_table_that_is_not_a_table_is_refused():
    with pytest.raises(ValidationError):
        VerticalGridConfig.model_validate(["constant"])
