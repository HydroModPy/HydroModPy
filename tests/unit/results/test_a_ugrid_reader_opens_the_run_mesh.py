"""A UGRID reader opens the mesh of a run as HydroModPy stores and exports it.

xugrid stands for the outside tools (UXarray, QGIS through MDAL, ParaView): it
reads ``mesh/`` of the store and the NetCDF export without HydroModPy, with
the CRS of the run, on a regular grid and on a Voronoi mesh whose centers are
not the mean of the vertices.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import xarray as xr
import xugrid as xu

from hydromodpy.core.state.paths import PROJECT_MARKER_FILENAME, RUNS_DIRNAME
from hydromodpy.results.exporters.netcdf import export_netcdf
from hydromodpy.results.storage.attempt import close_sealed_attempt
from hydromodpy.results.storage.contract import FIELDS_STORE_NAME
from hydromodpy.results.storage.sealing import seal_completed
from hydromodpy.results.zarr_store import SimulationZarr
from hydromodpy.results.zarr_store.mesh_layout import mesh_layout_from_cell_mesh
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh
from hydromodpy.workflow.steps.prepare_solver.prepare import step_persist_mesh
from tests._helpers.bundle_cell_meshes import bundle_dual
from tests._helpers.regular_cell_meshes import regular_cell_mesh
from tests._helpers.run_stores import open_run_store

BUNDLE = "stream_depletion_glover_balmer_tri_refined_well"
EPSG = 2154


def _regular() -> PlanarCellMesh:
    return regular_cell_mesh(xmin=500000.0, ymin=6800000.0, dx=25.0, dy=25.0, nrow=3, ncol=4)


def _voronoi() -> PlanarCellMesh:
    return bundle_dual(BUNDLE)


MESHES = pytest.mark.parametrize("build", [_regular, _voronoi], ids=["regular", "voronoi"])


def _write_crs(store: SimulationZarr) -> None:
    store.write_crs(
        crs_wkt=f"EPSG:{EPSG}", grid_mapping_name="lambert_conformal_conic", epsg_code=EPSG
    )


def _write_mesh(store: SimulationZarr, cell_mesh: PlanarCellMesh) -> None:
    xy = np.asarray(cell_mesh.mesh.vertices, dtype=float)
    n = cell_mesh.n_cells
    store.write_mesh(
        np.column_stack([xy, np.zeros(xy.shape[0])]),
        cell_mesh.connectivity_rows,
        np.array([[10.0] * n, [0.0] * n]),
        topography=np.full(n, 10.0),
        layout=mesh_layout_from_cell_mesh(cell_mesh),
    )


def _store(path: Path, cell_mesh: PlanarCellMesh, *, crs: bool = True) -> Path:
    store = SimulationZarr.create(path, n_cells=cell_mesh.n_cells, n_layers=1)
    if crs:
        _write_crs(store)
    _write_mesh(store, cell_mesh)
    store.close()
    return path


def _open_mesh_group(path: Path) -> tuple[xr.Dataset, xu.Ugrid2d]:
    """Open ``mesh/`` as a stranger would, and fail on any warning xugrid raises."""
    dataset = xr.open_zarr(path, group="mesh", consolidated=False)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        grid = xu.UgridDataset(dataset).ugrid.grid
    return dataset, grid


@MESHES
def test_xugrid_opens_the_stored_mesh_group_with_its_crs(tmp_path, build):
    cell_mesh = build()
    dataset, grid = _open_mesh_group(_store(tmp_path / "fields.zarr", cell_mesh))

    assert grid.n_face == cell_mesh.n_cells
    assert grid.crs.to_epsg() == EPSG
    assert np.isclose(float(grid.area.sum()), float(cell_mesh.geometry.areas.sum()))
    assert np.array_equal(dataset["face_x"].values, cell_mesh.centers[:, 0])
    assert np.array_equal(dataset["node_x"].values, cell_mesh.mesh.vertices[:, 0])
    assert dataset["topology"].attrs["node_coordinates"] == "node_x node_y"


def test_the_vertices_stay_beside_the_node_axes(tmp_path):
    cell_mesh = _regular()
    store = SimulationZarr(_store(tmp_path / "fields.zarr", cell_mesh))
    mesh = store.root["mesh"]

    vertices = mesh["vertices"][:]
    assert vertices.shape == (cell_mesh.mesh.vertices.shape[0], 3)
    assert np.array_equal(mesh["node_x"][:], vertices[:, 0])
    assert np.array_equal(mesh["node_y"][:], vertices[:, 1])
    assert "node_z" not in mesh
    assert mesh["face_node_connectivity"].attrs["_FillValue"] == -1
    assert mesh["face_node_connectivity"].dtype == np.int32
    store.close()


@pytest.mark.parametrize("crs_first", [True, False], ids=["crs-first", "mesh-first"])
def test_the_mesh_group_holds_the_crs_whichever_is_written_first(tmp_path, crs_first):
    cell_mesh = _regular()
    store = SimulationZarr.create(tmp_path / "fields.zarr", n_cells=cell_mesh.n_cells, n_layers=1)
    if crs_first:
        _write_crs(store)
    _write_mesh(store, cell_mesh)
    if not crs_first:
        _write_crs(store)
    mesh = store.root["mesh"]

    assert dict(mesh["crs"].attrs) == dict(store.root["crs"].attrs)
    for name in ("topology", "node_x", "node_y", "face_x", "face_y"):
        assert mesh[name].attrs["grid_mapping"] == "crs"
    store.close()


def test_a_sealed_run_with_no_crs_names_none_and_still_opens(tmp_path):
    """The seal drops the ``grid_mapping`` of the topography, which names a CRS the run lacks."""
    cell_mesh = _regular()
    store = SimulationZarr(_store(tmp_path / "fields.zarr", cell_mesh, crs=False))
    store.harmonize_axis_references()
    store.close()
    dataset, grid = _open_mesh_group(tmp_path / "fields.zarr")

    assert "crs" not in dataset.variables
    assert "grid_mapping" not in dataset["node_x"].attrs
    assert grid.crs is None
    assert grid.is_projected


def test_a_sealed_run_keeps_the_mesh_readable_by_xugrid(tmp_path):
    """The seal drops the references that resolve to nothing; the CRS of the mesh resolves."""
    project = tmp_path / "project"
    project.mkdir()
    (project / PROJECT_MARKER_FILENAME).write_text("[workspace]\n", encoding="utf-8")
    cell_mesh = regular_cell_mesh(xmin=0.0, ymin=0.0, dx=10.0, dy=10.0, nrow=2, ncol=2)
    store = open_run_store(project, "ugrid_run", n_cells=cell_mesh.n_cells, n_layers=1)
    (store.run_dir / "config.toml").write_text("[flow]\nk = 1e-5\n", encoding="utf-8")
    store.write_crs(
        store.sim_id,
        crs_wkt=f"EPSG:{EPSG}",
        grid_mapping_name="lambert_conformal_conic",
        epsg_code=EPSG,
    )
    ctx = SimpleNamespace(
        setup=SimpleNamespace(
            domain=SimpleNamespace(z_interfaces=np.array([0.0, -10.0])),
            cell_mesh=cell_mesh,
            mesh_summary=None,
        )
    )
    step_persist_mesh(ctx, store.sim_id, store=store)
    seal_completed(store)
    close_sealed_attempt(store.run_dir)

    fields = project / RUNS_DIRNAME / "ugrid_run" / FIELDS_STORE_NAME
    _, grid = _open_mesh_group(fields)
    assert grid.n_face == 4
    assert grid.crs.to_epsg() == EPSG


@MESHES
def test_the_netcdf_export_carries_the_model_centres_and_the_crs(tmp_path, build):
    cell_mesh = build()
    fields = _store(tmp_path / "fields.zarr", cell_mesh)
    path = export_netcdf(fields, "ugrid-test", ["topography"], tmp_path / "mesh.nc")

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        exported = xu.open_dataset(path)
    grid = exported.ugrid.grid
    assert grid.n_face == cell_mesh.n_cells
    assert grid.crs.to_epsg() == EPSG
    assert np.array_equal(exported.obj["face_x"].values, cell_mesh.centers[:, 0])
    assert np.array_equal(exported.obj["face_y"].values, cell_mesh.centers[:, 1])
    assert exported.obj["face_x"].attrs["standard_name"] == "projection_x_coordinate"


def test_the_voronoi_centres_are_not_the_vertex_mean():
    """Guard of the test above: on this mesh the vertex mean is meters off the generator."""
    cell_mesh = _voronoi()
    rows = cell_mesh.connectivity_rows
    xs = np.where(rows >= 0, cell_mesh.mesh.vertices[np.maximum(rows, 0), 0], np.nan)

    assert np.max(np.abs(np.nanmean(xs, axis=1) - cell_mesh.centers[:, 0])) > 1.0


def test_a_store_without_centres_exports_the_vertex_mean(tmp_path):
    cell_mesh = _regular()
    store = SimulationZarr.create(tmp_path / "fields.zarr", n_cells=cell_mesh.n_cells, n_layers=1)
    xy = np.asarray(cell_mesh.mesh.vertices, dtype=float)
    store.write_mesh(xy, cell_mesh.connectivity_rows, np.array([0.0, -10.0]))
    store.close()

    path = export_netcdf(tmp_path / "fields.zarr", "old-run", [], tmp_path / "mesh.nc")
    with xr.open_dataset(path) as exported:
        assert np.allclose(exported["face_x"].values, cell_mesh.centers[:, 0])
        assert "node_z" not in exported


def test_export_netcdf_called_alone_writes_a_mapping_attribute_as_json(tmp_path):
    cell_mesh = _regular()
    store = SimulationZarr(_store(tmp_path / "fields.zarr", cell_mesh))
    identity = {"sim_id": "a-run", "case_id": "a-case"}
    store.root.attrs.update(
        {
            "hydromodpy_identity": identity,
            "cell_types": ["quadrilateral"],
            "ranges": [[0, 1], [2, 3]],
            "flag": True,
        }
    )
    store.close()

    path = export_netcdf(
        tmp_path / "fields.zarr",
        "a-run",
        [],
        tmp_path / "mesh.nc",
        global_attrs={"bounds": [np.float32(1.5), np.int64(2)], "counts": {"cells": np.int64(12)}},
    )
    with xr.open_dataset(path) as exported:
        assert json.loads(exported.attrs["hydromodpy_identity"]) == identity
        assert exported.attrs["cell_types"] == "quadrilateral"
        assert json.loads(exported.attrs["ranges"]) == [[0, 1], [2, 3]]
        assert exported.attrs["flag"] == 1
        assert np.asarray(exported.attrs["bounds"]).tolist() == [1.5, 2.0]
        assert json.loads(exported.attrs["counts"]) == {"cells": 12}
