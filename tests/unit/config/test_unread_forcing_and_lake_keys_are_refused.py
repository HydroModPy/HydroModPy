"""Keys no step read are refused in a file, and dropped from a stored config."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.config.stored_config_migration import migrate_stored_config
from hydromodpy.data.variables.lake_bathymetry.config import LakeBathymetryConfig
from hydromodpy.data.variables.lake_geometry.config import LakeGeometryConfig
from hydromodpy.physics.base.forcing import CsvForcing
from hydromodpy.physics.flow.boundary_conditions import FlowBoundaryForcingCsvConfig
from hydromodpy.physics.flow.sinks_sources.wells import FlowWellForcingCsvConfig


@pytest.mark.parametrize(
    "model, payload",
    [
        (CsvForcing, {"kind": "csv", "path": "a.csv", "fill_method": "none"}),
        (FlowWellForcingCsvConfig, {"kind": "csv", "path": "a.csv", "fill_method": "ffill"}),
        (FlowBoundaryForcingCsvConfig, {"mode": "csv", "path": "a.csv", "fill_method": "bfill"}),
    ],
)
def test_a_fill_method_is_refused_with_what_decides_instead(model, payload) -> None:
    with pytest.raises(ValidationError, match="coverage_policy"):
        model.model_validate(payload)


@pytest.mark.parametrize("model", [LakeBathymetryConfig, LakeGeometryConfig])
def test_a_lake_data_name_is_refused(model) -> None:
    with pytest.raises(ValidationError, match="lake_id"):
        model.model_validate({"sources": [{"source": "custom", "path": "x"}], "id": "lake"})


def test_a_stored_config_loses_the_unread_keys() -> None:
    stored = {
        "data": {
            "lake_bathymetry": {"id": "lake_bathymetry", "sources": []},
            "lake_geometry": {"id": "lake_geometry", "sources": []},
        },
        "flow": {
            "sinks_sources": {"wells": {"w1": {"forcing": {"kind": "csv", "fill_method": "ffill"}}}}
        },
    }

    migrated = migrate_stored_config(stored)

    assert "id" not in migrated["data"]["lake_bathymetry"]
    assert "id" not in migrated["data"]["lake_geometry"]
    assert "fill_method" not in migrated["flow"]["sinks_sources"]["wells"]["w1"]["forcing"]
    assert stored["data"]["lake_bathymetry"]["id"] == "lake_bathymetry"
