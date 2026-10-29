"""``[domain.layers]``, the one layering table every solver reads.

The layering is never a key of a solver ``sgrid`` table: ``test_sgrid_config.py`` refuses it.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.core.vertical_column import VERTICAL_LAYOUT_COLUMN_FRACTIONS as FRACTIONS
from hydromodpy.core.vertical_column import VERTICAL_LAYOUT_SURFACES as SURFACES
from hydromodpy.spatial.domain.domain_config import DomainConfig
from hydromodpy.spatial.domain.layers_config import VerticalGridConfig
from tests._helpers.domain_cases import surfaces_table


@pytest.mark.parametrize(
    ("table", "read"),
    [
        ({}, {"genmtd_lay": "constant", "nlay": 1, "layer_count": 1, "vertical_layout": FRACTIONS, "base_surface_names": (), "has_pass_through_cells": False}),
        ({"genmtd_lay": "decay", "nlay": 4.0, "lay_decay": "1.5"}, {"layer_count": 4, "nlay": 4, "lay_decay": 1.5}),
        ({"genmtd_lay": "constant", "nlay": 3}, {"layer_count": 3, "nlay": 3, "lay_decay": None}),
        ({"genmtd_lay": "list", "lay_proportions": [0.25, 0.75]}, {"layer_count": 2, "nlay": None, "lay_proportions": [0.25, 0.75]}),
        (surfaces_table({"name": "weathered", "surface": "weathered_base"}, {"name": "fissured", "thickness": "30 m"}, {"name": "bedrock"}),
         {"layer_count": 3, "nlay": None, "base_surface_names": ("weathered_base",), "vertical_layout": SURFACES, "has_pass_through_cells": True}),
    ],
    ids=["default_one_constant_layer", "decay_with_a_float_count", "constant", "list", "surfaces"],
)  # fmt: skip
def test_domain_layers_validates_its_table_and_counts_its_layers(table, read):
    layers = (
        DomainConfig.model_validate({"layers": table}).layers if table else DomainConfig().layers
    )

    assert isinstance(layers, VerticalGridConfig)
    assert {key: getattr(layers, key) for key in read} == read
    assert VerticalGridConfig.from_mapping(table) == layers


@pytest.mark.parametrize("table", [{"genmtd_lay": "list", "lay_proportions": [0.5, 0.5]}, surfaces_table({"name": "rock"})])  # fmt: skip
def test_a_layer_count_beside_a_layering_that_derives_it_is_ignored_with_a_warning(table):
    with pytest.warns(UserWarning, match="nlay must not be provided"):
        assert VerticalGridConfig.model_validate({**table, "nlay": 5}).nlay is None


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
        (surfaces_table({"name": "weathered"}, {"name": "bedrock"}), "gives no base"),
        (surfaces_table({"name": "weathered", "depth": 5.0}), "ends on the base of the aquifer"),
        (surfaces_table({"name": "weathered", "depth": 5.0, "elevation": 40.0}, {"name": "bedrock"}), "one key only"),
        (surfaces_table({"name": "rock", "depth": 5.0}, {"name": "rock"}), "names a layer twice"),
        ({"genmtd_lay": "constant", "nlay": 2, "layer": [{"name": "rock"}]}, "read only with genmtd_lay = 'surfaces'"),
        (["constant"], None),
    ],
)  # fmt: skip
def test_a_layering_table_that_does_not_stack_is_refused(table, match):
    with pytest.raises(ValidationError, match=match):
        VerticalGridConfig.model_validate(table)
