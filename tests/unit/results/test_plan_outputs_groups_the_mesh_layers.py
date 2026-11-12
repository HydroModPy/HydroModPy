"""The mesh layers of a request share one GeoPackage; every other layer keeps a file.

A Shapefile holds one layer, so the same request writes one file per layer there.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.results.exporters.export_spec import (
    MESH_LAYERS,
    ExportKind,
    ExportRequest,
    plan_outputs,
)

KINDS = {
    **dict.fromkeys(MESH_LAYERS, ExportKind.vector),
    "watershed": ExportKind.vector,
    "head": ExportKind.field,
}


def _plan(request: ExportRequest):
    return plan_outputs(request, KINDS, run_label="nancon")


def test_a_file_names_the_one_geopackage_of_the_layers() -> None:
    request = ExportRequest(variables=list(MESH_LAYERS), file="out/mesh.gpkg")

    (planned,) = _plan(request)

    assert str(planned.path) == "out/mesh.gpkg"
    assert planned.variables == MESH_LAYERS


def test_a_file_refuses_a_layer_that_is_another_file() -> None:
    with pytest.raises(ValidationError, match="3 names write 2 files"):
        ExportRequest(variables=["watershed", "mesh_cells", "mesh_seeds"], file="out.gpkg")


def test_a_file_refuses_two_layers_in_a_shapefile() -> None:
    with pytest.raises(ValidationError, match="2 names write one file each"):
        ExportRequest(variables=["mesh_cells", "mesh_seeds"], format="shapefile", file="m.shp")


def test_a_mesh_layer_cannot_be_written_as_a_netcdf() -> None:
    with pytest.raises(ValueError, match="'mesh_cells' is a vector"):
        _plan(ExportRequest(variables="mesh_cells", format="netcdf"))
