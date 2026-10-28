"""``[domain.depth_model]``: four kinds, two of them read a raster."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.spatial.domain.domain_config import DomainConfig


@pytest.mark.parametrize(
    ("depth_model", "match"),
    [
        ({"kind": "raster_substratum", "scale": 2.0}, "scale"),
        ({"kind": "constant_thickness", "thickness": -5.0}, "thickness"),
        ({"kind": "bedrock_map"}, "kind"),
    ],
    ids=["scale_beside_an_elevation_raster", "negative_thickness", "unknown_kind"],
)
def test_a_depth_model_its_kind_does_not_read_is_refused(depth_model, match):
    with pytest.raises(ValidationError, match=match):
        DomainConfig.model_validate({"depth_model": depth_model})
