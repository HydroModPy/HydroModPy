"""Planning the output files of an export request: the mesh layers share one GeoPackage, every
other layer keeps a file, and a Shapefile holds one layer so it writes one file per layer.
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


def test_one_geopackage_for_the_layers() -> None:
    request = ExportRequest(variables=list(MESH_LAYERS), file="out/mesh.gpkg")

    (planned,) = _plan(request)

    assert str(planned.path) == "out/mesh.gpkg"
    assert planned.variables == MESH_LAYERS


def test_file_refuses_a_layer_of_another_file() -> None:
    with pytest.raises(ValidationError, match="3 names write 2 files"):
        ExportRequest(variables=["watershed", "mesh_cells", "mesh_seeds"], file="out.gpkg")


def test_file_refuses_two_shapefile_layers() -> None:
    with pytest.raises(ValidationError, match="2 names write one file each"):
        ExportRequest(variables=["mesh_cells", "mesh_seeds"], format="shapefile", file="m.shp")


def test_mesh_layer_as_netcdf() -> None:
    with pytest.raises(ValueError, match="'mesh_cells' is a vector"):
        _plan(ExportRequest(variables="mesh_cells", format="netcdf"))
