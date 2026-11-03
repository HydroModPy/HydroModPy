"""Keys no step read are refused."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.data.variables.lake_bathymetry.config import LakeBathymetryConfig
from hydromodpy.data.variables.lake_geometry.config import LakeGeometryConfig
from hydromodpy.physics.base.forcing import CsvForcing


@pytest.mark.parametrize("fill_method", ["none", "ffill", "bfill"])
def test_a_fill_method_is_refused_with_what_decides_instead(fill_method) -> None:
    payload = {"kind": "csv", "path_file": "a.csv", "fill_method": fill_method}
    with pytest.raises(ValidationError, match="coverage_policy"):
        CsvForcing.model_validate(payload)


@pytest.mark.parametrize("model", [LakeBathymetryConfig, LakeGeometryConfig])
def test_a_lake_data_name_is_refused(model) -> None:
    with pytest.raises(ValidationError, match="lake_id"):
        model.model_validate({"sources": [{"source": "custom", "path": "x"}], "id": "lake"})
