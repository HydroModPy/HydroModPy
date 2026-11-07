"""The geology source a mesh follows, and its coastal override."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.model.properties.geology_config import (
    GeologyConfigBlock,
    GeologyLandSea,
    GeologySource,
)


@pytest.mark.parametrize(
    ("model", "data", "match"),
    [
        (GeologySource, {"path": "g.shp", "kind": "vector", "reference_raster_path": "r.tif"},
         "'code_field' is required"),
        (GeologySource, {"path": "g.shp", "kind": "vector", "code_field": "CODE"},
         "'reference_raster_path' is required"),
        (GeologyLandSea, {"enabled": True}, "landsea.path is required"),
    ],
    ids=["vector_without_code_field", "vector_without_reference_raster", "landsea_without_path"],
)  # fmt: skip
def test_a_geology_source_that_cannot_be_read_is_refused(model, data, match) -> None:
    with pytest.raises(ValidationError, match=match):
        model.model_validate(data)


def test_a_raster_source_needs_no_vector_option_and_takes_the_defaults() -> None:
    vector = {
        "path": "g.shp",
        "kind": "vector",
        "code_field": "C",
        "reference_raster_path": "r.tif",
    }
    assert GeologySource.model_validate(vector).code_field == "C"
    block = GeologyConfigBlock.model_validate({"source": {"path": "g.tif", "kind": " Raster "}})

    assert block.source.kind == "raster"
    assert block.id == GeologyConfigBlock.model_fields["id"].default
    assert block.landsea == GeologyLandSea()
