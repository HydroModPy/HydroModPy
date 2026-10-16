"""The mesh layers of a request share one GeoPackage; every other layer keeps a file.

A Shapefile holds one layer, so the same request writes one file per layer there.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hydromodpy.core.config_kit.export_spec import (
    MESH_LAYERS,
    ExportFormat,
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


def test_the_three_layers_are_one_file_named_after_the_run() -> None:
    (planned,) = _plan(ExportRequest(variables=list(MESH_LAYERS)))

    assert str(planned.path) == "nancon_mesh.gpkg"
    assert planned.format is ExportFormat.geopackage
    assert planned.variables == MESH_LAYERS


def test_two_layers_are_one_file_too() -> None:
    (planned,) = _plan(ExportRequest(variables=["mesh_seeds", "mesh_cells"]))

    assert str(planned.path) == "nancon_mesh.gpkg"
    assert planned.variables == ("mesh_seeds", "mesh_cells")


def test_one_layer_is_a_file_named_after_it() -> None:
    (planned,) = _plan(ExportRequest(variables="mesh_family_faces"))

    assert str(planned.path) == "mesh_family_faces.gpkg"
    assert planned.variables == ("mesh_family_faces",)


def test_a_shapefile_writes_one_file_per_layer() -> None:
    planned = _plan(ExportRequest(variables=list(MESH_LAYERS), format="shapefile"))

    assert [str(item.path) for item in planned] == [f"{name}.shp" for name in MESH_LAYERS]
    assert [item.variables for item in planned] == [(name,) for name in MESH_LAYERS]


def test_the_other_layers_keep_a_file_each() -> None:
    planned = _plan(ExportRequest(variables=["watershed", "mesh_cells", "mesh_seeds"]))

    assert [(str(item.path), item.variables) for item in planned] == [
        ("watershed.gpkg", ("watershed",)),
        ("nancon_mesh.gpkg", ("mesh_cells", "mesh_seeds")),
    ]


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


def test_a_crs_reprojects_the_mesh_layers() -> None:
    (planned,) = _plan(ExportRequest(variables=list(MESH_LAYERS), crs="EPSG:4326"))

    assert planned.format is ExportFormat.geopackage


def test_a_mesh_layer_cannot_be_written_as_a_netcdf() -> None:
    with pytest.raises(ValueError, match="'mesh_cells' is a vector"):
        _plan(ExportRequest(variables="mesh_cells", format="netcdf"))
