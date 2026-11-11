"""Tests of export outputs."""

from __future__ import annotations

import dataclasses
import json
import logging
import re
import warnings
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import pytest
import rasterio
import shapely
import xarray as xr
import xugrid as xu
import zarr
from pyproj import CRS
from shapely.geometry import LineString, box

from hydromodpy.core.exceptions import ExportError
from hydromodpy.core.io.file_digest import sha256_and_size
from hydromodpy.core.licensing import UNDETERMINED_LICENSE
from hydromodpy.core.state.layout import PROJECT_MARKER_FILENAME, RUNS_DIRNAME
from hydromodpy.core.time import TimeSelectionError
from hydromodpy.core.tracking.input_file import TrackedFileEntry
from hydromodpy.core.workspace.workspace_toml import write_workspace_toml
from hydromodpy.display.config import DisplayConfig
from hydromodpy.display.runs import figures_dir_of, render_figures_for_run
from hydromodpy.mesh.planar.planar_cell_mesh import CellChain, FaceFamilyTable, PlanarCellMesh
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.export.directory import context_from_directory, publication_of
from hydromodpy.results.exporters import job as job_module
from hydromodpy.results.exporters import request as request_module
from hydromodpy.results.exporters import vocabulary
from hydromodpy.results.exporters.export_spec import (
    MESH_LAYERS,
    ExportKind,
    ExportRequest,
    load_export_requests,
)
from hydromodpy.results.exporters.geotiff import export_geographic_raster
from hydromodpy.results.exporters.mesh_layers import (
    available_mesh_layers,
    export_mesh_layers,
    mesh_layer_reasons,
)
from hydromodpy.results.exporters.netcdf import export_netcdf
from hydromodpy.results.exporters.request import export_data_requests, export_run
from hydromodpy.results.exporters.vocabulary import _stored_rasters, list_exportable
from hydromodpy.results.identity import ZARR_IDENTITY_ATTR, Identity, read_identity_from
from hydromodpy.results.ledger import Ledger
from hydromodpy.results.record.manifest import list_artifacts
from hydromodpy.results.record.record import PROVENANCE_VERSION, sealed_artifacts
from hydromodpy.results.run import Run
from hydromodpy.results.storage.attempt import close_sealed_attempt
from hydromodpy.results.storage.contract import (
    ALLOWED_RUN_ENTRIES,
    FIELDS_STORE_NAME,
    PARQUET_FILE_SUFFIX,
    RUN_CONFIG_FILENAME,
    TABLES_DIRNAME,
)
from hydromodpy.results.storage.parquet_io import read_kv_metadata
from hydromodpy.results.storage.run_store import RunStore
from hydromodpy.results.storage.sealing import IDENTITY_NOTICE_FILENAME, seal_completed
from hydromodpy.results.zarr_store.constants import ZARR_SCHEMA_VERSION
from hydromodpy.results.zarr_store.mesh_layout import (
    cell_family_rows,
    face_family_rows,
    mesh_layout_from_cell_mesh,
)
from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr
from hydromodpy.schema.job.directory import JobDirectory
from hydromodpy.schema.job.documents import read_document, write_document
from hydromodpy.schema.job.extent import SpatialExtent
from hydromodpy.schema.job.inputset import Licence, build_inputset, file_resource
from hydromodpy.schema.job.layout import ALLOWED_JOB_ENTRIES
from hydromodpy.schema.job.outcome import JobOutcome, OutputRecord
from hydromodpy.schema.media_types import GEOPACKAGE_MEDIA_TYPE, GEOTIFF_MEDIA_TYPE
from hydromodpy.workflow.steps.prepare_solver.prepare import step_persist_mesh
from tests._helpers.bundle_cell_meshes import bundle_dual
from tests._helpers.regular_cell_meshes import regular_cell_mesh
from tests._helpers.run_records import make_record
from tests._helpers.run_stores import RUN_NAME, open_run_store, seal_demo_run
from tests._helpers.sealed_runs import manifest_document

# The group stored its nodata as a float ``_FillValue`` attribute, which
# ``xarray.open_zarr`` refuses on a Zarr 3 array, and its rasters had neither
# pixel coordinates nor a grid mapping. A run written that way still reads
# through HydroModPy.
pytestmark = pytest.mark.fast


TRANSFORM = (75.0, 0.0, 385_762.5, 0.0, -75.0, 6_826_612.5)


NODATA = -9999.0


def _dem() -> np.ndarray:
    dem = np.arange(12.0, dtype="float32").reshape(3, 4) + 100.0
    dem[0, 0] = NODATA
    return dem


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    path = tmp_path / "fields.zarr"
    with SimulationZarr.create(path, n_cells=4, n_layers=1) as sz:
        sz.write_geographic_raster(
            "watershed_dem", _dem(), transform=TRANSFORM, crs="EPSG:2154", nodata=NODATA
        )
    return path


def test_xarray_opens_the_group_with_its_nodata_axes_and_crs(store_path: Path):
    ds = xr.open_zarr(store_path, group="geographic", consolidated=False, decode_coords="all")
    dem = ds["watershed_dem"]

    assert np.isnan(dem.values[0, 0])
    assert dem.values[2, 3] == 111.0
    np.testing.assert_allclose(dem["watershed_dem_x"], 385_762.5 + 75.0 * (np.arange(4) + 0.5))
    np.testing.assert_allclose(dem["watershed_dem_y"], 6_826_612.5 - 75.0 * (np.arange(3) + 0.5))
    assert CRS.from_cf(dem["watershed_dem_crs"].attrs).to_epsg() == 2154


def test_the_hydromodpy_reader_reads_a_new_run_and_an_old_one(store_path: Path, tmp_path: Path):
    old_path = tmp_path / "old.zarr"
    with SimulationZarr.create(old_path, n_cells=4, n_layers=1) as sz:
        geo = sz.root.require_group("geographic")
        old = geo.create_array("watershed_dem", data=_dem(), dimension_names=("d0", "d1"))
        old.attrs.update(
            {"transform": list(TRANSFORM), "crs": "EPSG:2154", "nodata": NODATA, "shape": [3, 4]}
        )
        old.attrs["_FillValue"] = NODATA

    for path in (store_path, old_path):
        with SimulationZarr(path) as sz:
            data, meta = sz.read_geographic_raster("watershed_dem")
        np.testing.assert_array_equal(data, _dem())
        assert meta == {
            "transform": TRANSFORM,
            "crs": "EPSG:2154",
            "nodata": NODATA,
            "shape": (3, 4),
        }


def test_only_the_rasters_are_offered_for_export(store_path: Path, tmp_path: Path):
    class _Store:
        def open_zarr(self, _sim_id):
            return SimulationZarr(store_path)

    assert _stored_rasters(_Store(), "run") == ["watershed_dem"]

    tif = export_geographic_raster(store_path, "run", "watershed_dem", tmp_path / "dem.tif")
    with rasterio.open(tif) as src:
        assert src.nodata == NODATA
        assert src.crs.to_epsg() == 2154
        np.testing.assert_array_equal(src.read(1), _dem())


@pytest.mark.parametrize(
    ("values", "transform", "crs", "units"),
    [
        (
            np.array([[1.0, -1.0]], dtype="float32"),
            (0.01, 0.0, -2.0, 0.0, -0.01, 48.0),
            "EPSG:4326",
            ("degrees_east", "degrees_north"),
        ),
        (np.array([[1, -1]], dtype="int16"), TRANSFORM, "EPSG:2154", ("m", "m")),
    ],
    ids=["degrees", "integer"],
)
def test_the_axes_take_the_unit_of_the_crs_and_an_integer_keeps_its_nodata(
    tmp_path: Path, values, transform, crs, units
):
    path = tmp_path / "fields.zarr"
    with SimulationZarr.create(path, n_cells=4, n_layers=1) as sz:
        sz.write_geographic_raster("grid", values, transform=transform, crs=crs, nodata=-1)

    ds = xr.open_zarr(path, group="geographic", consolidated=False, decode_coords="all")

    assert (ds["grid_x"].attrs["units"], ds["grid_y"].attrs["units"]) == units
    assert int(ds["grid"].isnull().sum()) == 1


# The Zarr attributes and the Parquet footers carry the roll-up of the inputs'
# sidecars, derived from the facts of the run. The warning about a missing
# identity or licence is said once per workspace, not once per run.
def _input(root: Path, name: str, **sidecar: object) -> Path:
    path = root / "data" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(name.encode())
    if sidecar:
        path.with_name(path.name + ".json").write_text(json.dumps(sidecar), encoding="utf-8")
    return path


def _tracked(paths: list[Path]) -> list[TrackedFileEntry]:
    return [
        TrackedFileEntry(
            role=path.stem,
            category="data",
            original_path=str(path),
            canonical_path=path,
            portable=True,
        )
        for path in paths
    ]


def _open(project: Path, inputs: list[Path], name: str = "run") -> RunStore:
    store = open_run_store(project, name, n_cells=4, crs_wkt="EPSG:2154", crs_epsg=2154)
    store.register_tracked_files(store.sim_id, _tracked(inputs))
    return store


def _seal(store: RunStore) -> dict:
    (store.run_dir / RUN_CONFIG_FILENAME).write_text("[flow]\nhk = 1e-5\n", encoding="utf-8")
    seal_completed(store)
    return dict(zarr.open_group(str(store.fields_path), mode="r").attrs)


def test_inputs_with_a_stated_licence_give_it_to_the_run(tmp_path: Path) -> None:
    project = tmp_path / "demo"
    dem = _input(project, "dem.tif", source="ign_geoplateforme_dem", license="etalab-2.0")
    geology = _input(project, "geology.gpkg", source="brgm_1m", license=None)
    store = _open(project, [dem, geology])
    assert store.licence() == "etalab-2.0"
    index = pd.date_range("2020-01-01", periods=2, freq="D")
    store.write_timeseries(store.sim_id, "P01", "head", pd.Series([1.0, 2.0], index=index))

    attrs = _seal(store)

    footer = read_kv_metadata(store.tables_dir / f"timeseries{PARQUET_FILE_SUFFIX}")
    assert attrs["license"] == "etalab-2.0"
    assert footer["license"] == "etalab-2.0"
    assert footer["hmp.identity"]


def test_the_workspace_toml_identity_is_stamped(tmp_path: Path) -> None:
    write_workspace_toml(
        tmp_path, project_name="ws", creator_name="Ada Lovelace", creator_email="a@b.c"
    )
    toml_path = tmp_path / "workspace.toml"
    toml_path.write_text(
        toml_path.read_text().replace(
            'creator_institution = ""', 'creator_institution = "Univ Rennes"'
        )
    )
    project = tmp_path / "projects" / "demo"
    project.mkdir(parents=True)

    attrs = _seal(_open(project, []))

    assert attrs["creator_name"] == "Ada Lovelace"
    assert attrs["creator_institution"] == "Univ Rennes"


def test_the_unix_account_is_never_the_creator(tmp_path: Path) -> None:
    attrs = _seal(_open(tmp_path / "demo", []))
    assert "creator_name" not in attrs


def _sealed_without(caplog: pytest.LogCaptureFixture, level: int) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if "sealed without" in r.getMessage() and r.levelno == level
    ]


def test_the_warning_is_said_once_per_workspace(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="hydromodpy")
    project = tmp_path / "demo"
    for index in range(3):
        _seal(_open(project, [], name=f"run_{index}"))
    warnings = _sealed_without(caplog, logging.WARNING)
    assert len(warnings) == 1
    assert len(_sealed_without(caplog, logging.INFO)) == 2
    (message,) = warnings
    assert message.startswith(
        "Runs of this workspace are sealed without creator_name, creator_institution "
        "and a known licence. "
    )
    assert 'Add creator_name = "..." and creator_institution = "..." under [workspace]' in message
    assert "workspace.toml" in message
    assert "'license' key of each input sidecar" in message
    assert message.count(". ") == 1
    assert "--verbose" not in message


def test_a_later_process_of_the_same_workspace_is_not_warned_again(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Each ``hmp run`` is a new process: the fact lives on disk, not in memory."""
    caplog.set_level(logging.INFO, logger="hydromodpy")
    project = tmp_path / "demo"
    _seal(_open(project, [], name="first"))
    marker = project / ".hmp" / IDENTITY_NOTICE_FILENAME
    assert json.loads(marker.read_text(encoding="utf-8"))["missing"] == [
        "a known licence",
        "creator_institution",
        "creator_name",
    ]
    caplog.clear()
    _seal(_open(project, [], name="second"))
    assert _sealed_without(caplog, logging.WARNING) == []
    assert (project / "runs" / "second" / TABLES_DIRNAME).is_dir()


# The export step writes the ``[[export]]`` blocks with the store of the run,
# before the index knows the run. The names a run can export, the layers of
# its mesh and the default resolution of a GeoTIFF are read from the run
# directory, so the export succeeds while ``Catalog`` cannot be opened.
@pytest.fixture
def store(tmp_path, monkeypatch):
    run_dir, _sim_id = seal_demo_run(tmp_path / "project")

    def refuse(*_args, **_kwargs):
        raise AssertionError("an export of a run store opened the index")

    monkeypatch.setattr(Catalog, "__init__", refuse)
    with RunStore.open(run_dir) as opened:
        yield opened


def test_the_listing_reads_the_run_directory(store) -> None:
    held = list_exportable(Run(store.sim_id, store))

    assert held["head"] is ExportKind.field
    assert held["discharge"] is ExportKind.series
    assert held["watershed"] is ExportKind.vector
    assert held["budget"] is ExportKind.table
    assert "mesh_family_faces" not in held


def test_the_data_requests_write_under_the_run_without_the_index(store) -> None:
    requests = load_export_requests(
        [
            {"variables": "watershed"},
            {"variables": "mesh_cell_area", "format": "geotiff"},
            {"variables": "all", "format": "rocrate"},
        ]
    )

    written = export_data_requests(store, store.sim_id, requests)

    exports = store.run_dir / "exports"
    assert sorted(path.name for path in written) == ["mesh_cell_area.tif", "watershed.gpkg"]
    for path in written:
        assert path.parent == exports
        identity = read_identity_from(path)
        assert identity is not None
        assert identity.sim_id == store.sim_id


# The run holds a head field of one layer and ``budget/storage_sy`` (the
# MODFLOW 6 specific-yield term) on four Lambert-93 cells, over three monthly
# periods, written by its store, sealed and indexed.
X0, Y0, STEP = 385000.0, 6814000.0, 500.0


STAMPS = pd.to_datetime(["2000-02-01", "2000-03-01", "2000-04-01"])


# Multiples of 1/4 are exact in float32, the width the store keeps.
STORAGE_SY = np.arange(12, dtype="float64").reshape(3, 1, 4) * 0.25


@pytest.fixture
def storage_run(tmp_path):
    project = tmp_path / "workspace"
    store = open_run_store(
        project,
        "demo",
        n_cells=4,
        n_layers=1,
        n_timesteps=3,
        crs_epsg=2154,
        crs_wkt="EPSG:2154",
        period_start=datetime(2000, 1, 1, tzinfo=UTC),
        period_end=datetime(2000, 4, 1, tzinfo=UTC),
        time_unit="month",
    )
    sid = store.sim_id
    verts = np.array(
        [[X0 + i * STEP, Y0 + j * STEP] for j in range(3) for i in range(3)], dtype="float64"
    )
    conn = np.array([[0, 1, 4, 3], [1, 2, 5, 4], [3, 4, 7, 6], [4, 5, 8, 7]], dtype="int32")
    store.write_mesh(sid, verts, conn, np.array([50.0, 0.0]))
    store.write_time(sid, STAMPS.values.astype("datetime64[s]").astype("int64"))
    store.write_crs(sid, crs_wkt="EPSG:2154", epsg_code=2154)
    for t in range(3):
        store.write_field(
            sid,
            "head",
            t,
            np.array([[12.5, 14.25, 16.75, 19.0]]) + t,
            n_timesteps=3 if t == 0 else None,
        )
    store.write_field_stack(sid, "storage_sy", STORAGE_SY, subgroup="budget")
    run_dir = store.run_dir
    seal_completed(store)
    rebuild_index(project)
    with Catalog(project) as catalog:
        yield catalog, sid, run_dir / "exports"


def test_the_run_lists_and_reads_the_storage_term(storage_run) -> None:
    catalog, sid, _exports = storage_run
    run = catalog[sid]
    assert "storage_sy" in run.array.list_fields()
    assert list_exportable(run)["storage_sy"] is ExportKind.field
    np.testing.assert_allclose(run.field("storage_sy", time=1, layer=0), STORAGE_SY[1, 0])


def test_the_storage_term_exports_to_netcdf(storage_run) -> None:
    catalog, sid, exports = storage_run
    written = export_run(catalog, sid, ExportRequest(variables="storage_sy"))
    assert written == [exports / "storage_sy.nc"]
    with xr.open_dataset(written[0]) as ds:
        assert ds["storage_sy"].attrs["units"] == "m3 s-1"
        np.testing.assert_allclose(ds["storage_sy"].values.reshape(3, 1, 4), STORAGE_SY)


def test_the_storage_term_exports_to_geotiff(storage_run) -> None:
    import rasterio

    catalog, sid, exports = storage_run
    written = export_run(
        catalog, sid, ExportRequest(variables="storage_sy", time="2000-02-15", format="geotiff")
    )
    assert written == [exports / "storage_sy_2000-02-15.tif"]
    with rasterio.open(written[0]) as src:
        assert np.nanmax(src.read(1)) == pytest.approx(STORAGE_SY[1, 0].max())


def test_all_includes_the_storage_term(storage_run) -> None:
    catalog, sid, _exports = storage_run
    (written,) = export_run(catalog, sid, ExportRequest(variables="all"))
    with xr.open_dataset(written) as ds:
        assert {"head", "storage_sy"} <= set(ds.data_vars)


# xugrid stands for the outside tools (UXarray, QGIS through MDAL, ParaView): it
# reads ``mesh/`` of the store and the NetCDF export without HydroModPy, with
# the CRS of the run, on a regular grid and on a Voronoi mesh whose centers are
# not the mean of the vertices.
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


# ``[publication] license`` in ``config.toml`` names the licence and the
# creators; a run whose configuration declares none says
# ``LicenseRef-undetermined``, never a default.
def _sealed(tmp_path: Path, config: str | None) -> Path:
    record = make_record()
    run_dir = tmp_path / record.run.rel_dir
    run_dir.mkdir(parents=True)
    record.write(run_dir)
    if config is not None:
        (run_dir / "config.toml").write_text(config, encoding="utf-8")
    return run_dir


def test_the_declared_licence_and_creators_reach_the_view(tmp_path) -> None:
    run_dir = _sealed(
        tmp_path, '[publication]\nlicense = "CC-BY-4.0"\ncreators = ["A. Author", "B. Author"]\n'
    )

    context = context_from_directory(run_dir)

    assert context.license_url == "https://creativecommons.org/licenses/by/4.0/"
    assert context.creator_name == "A. Author, B. Author"


def test_a_run_that_declares_nothing_stays_undetermined(tmp_path) -> None:
    for config in (None, "[simulation]\nname = 'x'\n"):
        run_dir = _sealed(tmp_path / str(config is None), config)
        context = context_from_directory(run_dir)
        assert context.license_url == "LicenseRef-undetermined"
        assert context.creator_name is None
        assert publication_of(run_dir).license is None


# The run is a monthly transient run of three stress periods (January to March
# 2000) on four Lambert-93 cells, written by its store, sealed and indexed. It
# holds a head field of one layer, the simulated discharge at the catchment and
# the gauged discharge from October 1999, the delineated catchment and the
# mapped network as vector layers, the DEM as a raster layer, and the water
# budget. Every file lands under ``runs/demo/exports/``.
X0, Y0, STEP = 385000.0, 6814000.0, 500.0


@pytest.fixture
def dated_run(tmp_path):
    project = tmp_path / "workspace"
    store = open_run_store(
        project,
        "demo",
        n_cells=4,
        n_layers=1,
        n_timesteps=3,
        crs_epsg=2154,
        crs_wkt="EPSG:2154",
        period_start=datetime(2000, 1, 1, tzinfo=UTC),
        period_end=datetime(2000, 4, 1, tzinfo=UTC),
        time_unit="month",
    )
    sid = store.sim_id
    verts = np.array(
        [[X0 + i * STEP, Y0 + j * STEP] for j in range(3) for i in range(3)], dtype="float64"
    )
    conn = np.array([[0, 1, 4, 3], [1, 2, 5, 4], [3, 4, 7, 6], [4, 5, 8, 7]], dtype="int32")
    store.write_mesh(sid, verts, conn, np.array([50.0, 0.0]))
    store.write_time(sid, STAMPS.values.astype("datetime64[s]").astype("int64"))
    store.write_crs(sid, crs_wkt="EPSG:2154", epsg_code=2154)
    for t in range(3):
        store.write_field(
            sid,
            "head",
            t,
            np.array([[12.5, 14.25, 16.75, 19.0]]) + t,
            n_timesteps=3 if t == 0 else None,
        )
    store.write_timeseries(
        sid, "catchment", "discharge", pd.Series([1.0, 2.0, 3.0], index=STAMPS), unit="m3/s"
    )
    gauged = pd.Series(np.arange(200.0), index=pd.date_range("1999-10-01", periods=200, freq="D"))
    store.write_timeseries(sid, "NANCON", "discharge", gauged, unit="m3/s", source="observed")
    extent = box(X0, Y0, X0 + 2 * STEP, Y0 + 2 * STEP)
    store.write_geographic_feature(
        sid, "watershed", gpd.GeoDataFrame(geometry=[extent], crs="EPSG:2154")
    )
    river = LineString([(X0 + STEP, Y0), (X0 + STEP, Y0 + 2 * STEP)])
    store.write_geographic_feature(
        sid,
        "hydrographic_network_reference",
        gpd.GeoDataFrame(geometry=[river], crs="EPSG:2154"),
    )
    dem = np.arange(100.0, dtype="float64").reshape(10, 10)
    store.write_geographic_raster(
        sid,
        "watershed_dem",
        dem,
        transform=(100.0, 0.0, X0, 0.0, -100.0, Y0 + 1000.0),
        crs="EPSG:2154",
        nodata=-99999.0,
    )
    store.write_budgets(
        sid,
        [
            {
                "timestep": t,
                "zone_id": "catchment",
                "component": "recharge",
                "flux_in": 1.0 + t,
                "flux_out": 0.0,
            }
            for t in range(3)
        ],
    )
    run_dir = store.run_dir
    seal_completed(store)
    rebuild_index(project)
    with Catalog(project) as reader:
        yield reader, sid, run_dir / "exports"


def _names(paths: list[Path]) -> list[str]:
    return sorted(path.name for path in paths)


def test_the_run_lists_what_it_can_export_by_kind(dated_run) -> None:
    catalog, sid, _exports = dated_run
    names = list_exportable(catalog[sid])
    assert names["head"] is ExportKind.field
    assert names["watertable_depth"] is ExportKind.field
    assert names["discharge"] is ExportKind.series
    assert names["discharge_obs"] is ExportKind.series
    assert names["watershed"] is ExportKind.vector
    assert names["hydrographic_network_reference"] is ExportKind.vector
    assert names["watershed_dem"] is ExportKind.raster
    assert names["budget"] is ExportKind.table
    # No release flux, no network criterion: the simulated network is not offered.
    assert "simulated_active_network" not in names


def test_a_field_at_one_date_is_one_geotiff_named_by_the_date(dated_run) -> None:
    import rasterio

    catalog, sid, exports = dated_run
    written = export_run(catalog, sid, ExportRequest(variables="head", time="2000-02-15"))
    assert written == [exports / "head_2000-02-15.tif"]
    with rasterio.open(written[0]) as src:
        # 2000-02-15 falls in the February period, the second one.
        assert np.nanmax(src.read(1)) == pytest.approx(20.0)
        assert src.tags()["HMP_PERIOD"] == "2000-02"


def test_several_dates_are_one_netcdf_by_default(dated_run) -> None:
    catalog, sid, exports = dated_run
    written = export_run(catalog, sid, ExportRequest(variables="head", time=["2000-01-10", "last"]))
    assert written == [exports / "head.nc"]
    with xr.open_dataset(written[0]) as ds:
        assert ds.sizes["time"] == 2


def test_several_dates_in_a_one_instant_format_write_one_file_per_date(dated_run) -> None:
    catalog, sid, exports = dated_run
    written = export_run(
        catalog,
        sid,
        ExportRequest(
            variables=["head", "watertable_depth"], time=["2000-01-10", "last"], format="geotiff"
        ),
    )
    assert _names(written) == [
        "head_2000-01-10.tif",
        "head_last.tif",
        "watertable_depth_2000-01-10.tif",
        "watertable_depth_last.tif",
    ]
    assert all(path.parent == exports for path in written)


def test_a_one_instant_format_over_the_whole_run_writes_one_file_per_period(dated_run) -> None:
    catalog, sid, _exports = dated_run
    written = export_run(catalog, sid, ExportRequest(variables="head", format="geotiff"))
    assert _names(written) == ["head_2000-01.tif", "head_2000-02.tif", "head_2000-03.tif"]


def test_fields_over_the_run_share_one_netcdf_with_the_run_metadata(dated_run) -> None:
    catalog, sid, exports = dated_run
    written = export_run(catalog, sid, ExportRequest(variables=["head", "watertable_depth"]))
    assert written == [exports / "demo_fields.nc"]
    with xr.open_dataset(written[0]) as ds:
        assert {"head", "watertable_depth"} <= set(ds.data_vars)
        assert ds.sizes["time"] == 3
        # Exported before the seal, the file still says how large the mesh is
        # and carries the ACDD block the seal composes.
        assert int(ds.attrs["n_cells"]) == 4
        assert ds.attrs["title"] == "demo"


def test_a_file_that_takes_the_name_of_the_run_is_refused_before_it_is_written(
    dated_run,
) -> None:
    catalog, sid, exports = dated_run
    requests = [
        ExportRequest(variables=["head", "watertable_depth"]),
        ExportRequest(variables="head", file="demo_fields.nc"),
    ]

    with pytest.raises(ExportError, match=r"demo_fields\.nc is already written by an earlier"):
        export_data_requests(catalog, sid, requests)
    with xr.open_dataset(exports / "demo_fields.nc") as ds:
        assert {"head", "watertable_depth"} <= set(ds.data_vars)


def test_a_period_keeps_the_periods_it_overlaps(dated_run) -> None:
    catalog, sid, exports = dated_run
    written = export_run(
        catalog, sid, ExportRequest(variables="head", period=["2000-02-15", "2000-03-10"])
    )
    assert written == [exports / "head_2000-02-15_2000-03-10.nc"]
    with xr.open_dataset(written[0]) as ds:
        assert ds.sizes["time"] == 2


def test_all_in_one_format_writes_every_data_that_format_holds(dated_run) -> None:
    catalog, sid, _exports = dated_run
    written = export_run(
        catalog, sid, ExportRequest(variables="all", time="2000-03-01", format="geotiff")
    )
    assert _names(written) == [
        "head_2000-03-01.tif",
        "seepage_mask_2000-03-01.tif",
        "watershed_dem.tif",
        "watertable_depth_2000-03-01.tif",
        "watertable_elevation_2000-03-01.tif",
    ]


def test_all_writes_each_data_in_its_natural_format(dated_run) -> None:
    catalog, sid, _exports = dated_run
    written = export_run(catalog, sid, ExportRequest(variables="all"))
    assert _names(written) == [
        "budget.csv",
        "demo_fields.nc",
        "demo_series.csv",
        "hydrographic_network_reference.gpkg",
        "watershed.gpkg",
        "watershed_dem.tif",
    ]


def test_the_catchment_is_a_geopackage_in_the_model_crs(dated_run) -> None:
    catalog, sid, exports = dated_run
    written = export_run(catalog, sid, ExportRequest(variables="watershed"))
    assert written == [exports / "watershed.gpkg"]
    layer = gpd.read_file(written[0])
    assert len(layer) == 1
    assert layer.crs.to_epsg() == 2154


def test_a_vector_layer_is_written_as_a_shapefile_and_reprojected(dated_run) -> None:
    catalog, sid, exports = dated_run
    written = export_run(
        catalog,
        sid,
        ExportRequest(
            variables="hydrographic_network_reference", format="shapefile", crs="EPSG:4326"
        ),
    )
    assert written == [exports / "hydrographic_network_reference.shp"]
    layer = gpd.read_file(written[0])
    assert layer.crs.to_epsg() == 4326
    assert layer.total_bounds[0] == pytest.approx(-1.6, abs=2.0)


def test_the_dem_is_a_geotiff_on_its_own_grid(dated_run) -> None:
    import rasterio

    catalog, sid, exports = dated_run
    (dem,) = export_run(catalog, sid, ExportRequest(variables="watershed_dem"))
    assert dem == exports / "watershed_dem.tif"
    with rasterio.open(dem) as src:
        assert src.crs.to_epsg() == 2154
        assert src.res == (100.0, 100.0)
        assert src.read(1)[0, 0] == 0.0
        assert src.nodata == -99999.0


def test_the_dem_is_warped_to_the_crs_and_resolution_asked(dated_run) -> None:
    import rasterio

    catalog, sid, exports = dated_run
    (dem,) = export_run(
        catalog, sid, ExportRequest(variables="watershed_dem", file="dem_50m.tif", resolution=50)
    )
    assert dem == exports / "dem_50m.tif"
    with rasterio.open(dem) as src:
        assert src.res == (50.0, 50.0)
    (wgs84,) = export_run(
        catalog, sid, ExportRequest(variables="watershed_dem", file="dem.tif", crs="EPSG:4326")
    )
    with rasterio.open(wgs84) as src:
        assert src.crs.to_epsg() == 4326


def test_the_budget_is_a_csv_naming_each_period(dated_run) -> None:
    catalog, sid, exports = dated_run
    (written,) = export_run(catalog, sid, ExportRequest(variables="budget", time="2000-02-10"))
    assert written == exports / "budget_2000-02-10.csv"
    frame = pd.read_csv(written)
    assert list(frame.columns) == [
        "site",
        "case_id",
        "period_start",
        "period_end",
        "timestep",
        "zone_id",
        "component",
        "flux_in",
        "flux_out",
        "unit",
    ]
    assert frame["timestep"].tolist() == [1]
    assert frame["period_start"].tolist() == ["2000-02-01 00:00:00"]
    assert frame["period_end"].tolist() == ["2000-03-01 00:00:00"]


def test_series_are_written_on_the_run_clock_and_clipped_to_the_simulation(dated_run) -> None:
    catalog, sid, exports = dated_run
    (written,) = export_run(catalog, sid, ExportRequest(variables=["discharge", "discharge_obs"]))
    assert written == exports / "demo_series.csv"
    frame = pd.read_csv(written)
    simulated = frame[frame["source"] == "simulated"]
    # Naive times of the run clock: no session-zone offset, midnight stays midnight.
    assert simulated["datetime"].tolist() == [
        "2000-02-01 00:00:00",
        "2000-03-01 00:00:00",
        "2000-04-01 00:00:00",
    ]
    assert set(simulated["station_id"]) == {"catchment"}
    assert set(frame["variable"]) == {"discharge"}
    gauged = frame[frame["source"] == "observed"]
    # The record starts in October 1999; the file keeps the simulated window only.
    assert gauged["datetime"].min() == "2000-01-01 00:00:00"
    assert gauged["datetime"].max() == "2000-03-31 00:00:00"


def test_a_period_clips_each_series_to_the_periods_it_overlaps(dated_run) -> None:
    catalog, sid, exports = dated_run
    (written,) = export_run(
        catalog,
        sid,
        ExportRequest(
            variables=["discharge", "discharge_obs"], period=["2000-02-01", "2000-02-20"]
        ),
    )
    assert written == exports / "demo_series_2000-02-01_2000-02-20.csv"
    frame = pd.read_csv(written)
    simulated = frame[frame["source"] == "simulated"]
    assert simulated["datetime"].tolist() == ["2000-03-01 00:00:00"]
    gauged = frame[frame["source"] == "observed"]
    assert gauged["datetime"].min() == "2000-02-01 00:00:00"
    assert gauged["datetime"].max() == "2000-02-29 00:00:00"


def test_a_folder_and_a_file_are_read_from_the_exports_of_the_run(dated_run) -> None:
    catalog, sid, exports = dated_run
    written = export_run(catalog, sid, ExportRequest(variables="watershed", folder="livrables"))
    assert written == [exports / "livrables" / "watershed.gpkg"]
    written = export_run(catalog, sid, ExportRequest(variables="watershed", file="bassin.gpkg"))
    assert written == [exports / "bassin.gpkg"]


def test_every_file_is_recorded_in_the_ledger_of_the_exports(dated_run) -> None:
    catalog, sid, exports = dated_run
    (written,) = export_run(catalog, sid, ExportRequest(variables="head", time="last"))
    (entry,) = Ledger.read(exports).entries
    assert entry.file == written.name
    assert entry.options == {"variables": "head", "time": "last", "nodata": -9999.0}


def test_a_metadata_view_is_written_beside_the_seal(dated_run) -> None:
    """The RO-Crate view of the wheel renders the seal, beside it or under exports/.

    ``stac`` and ``prov`` live in hydromodpy_annex now: a metadata view without
    the annex is refused by the registry, and the sealed-directory case is read
    on the view the wheel ships.
    """
    catalog, sid, exports = dated_run
    (view,) = export_run(catalog, sid, ExportRequest(variables="all", format="rocrate"))
    assert view == catalog.run_dir_for(sid) / "ro-crate-metadata.json"
    assert view.is_file()
    (lineage,) = export_run(
        catalog, sid, ExportRequest(variables="all", format="rocrate", folder="meta")
    )
    assert lineage == exports / "meta" / "ro-crate-metadata.json"
    assert lineage.is_file()


def test_the_simulated_network_is_exported_by_date_and_over_the_run(dated_run, monkeypatch) -> None:
    import rasterio

    catalog, sid, exports = dated_run
    flowing = {0: [1.0, 0.0, 0.0, 0.0], 1: [1.0, 1.0, 0.0, 0.0], 2: [1.0, 1.0, 1.0, 0.0]}
    asked: list[list[int]] = []

    def stack(_run, steps):
        asked.append([int(step) for step in steps])
        return np.asarray([flowing[int(step)] for step in steps])

    monkeypatch.setattr(vocabulary, "network_unavailable_reason", lambda _run: None)
    monkeypatch.setattr(job_module, "simulated_active_network_stack", stack)

    (tif,) = export_run(
        catalog, sid, ExportRequest(variables="simulated_active_network", time="2000-02-15")
    )
    assert tif == exports / "simulated_active_network_2000-02-15.tif"
    with rasterio.open(tif) as src:
        values = src.read(1)
        assert set(np.unique(values[values != src.nodata])) == {0.0, 1.0}

    (gpkg,) = export_run(
        catalog,
        sid,
        ExportRequest(variables="simulated_active_network", time="last", format="geopackage"),
    )
    # Only the active cells are written: flowing[2] holds one inactive cell,
    # and a network export is not a raster of the whole domain.
    assert gpd.read_file(gpkg)["simulated_active_network"].tolist() == [1.0, 1.0, 1.0]

    (nc,) = export_run(catalog, sid, ExportRequest(variables=["head", "simulated_active_network"]))
    with xr.open_dataset(nc) as ds:
        np.testing.assert_array_equal(ds["simulated_active_network"].values, list(flowing.values()))
        assert ds["simulated_active_network"].attrs["units"] == "1"
    # The graph is built once per request, never once per step.
    assert asked == [[1], [2], [0, 1, 2]]


def test_a_run_without_the_network_says_why_it_cannot_export_it(dated_run) -> None:
    from hydromodpy.core.exceptions import ExportError

    catalog, sid, _exports = dated_run
    with pytest.raises(ExportError, match="no per-cell release_flux"):
        export_run(catalog, sid, ExportRequest(variables="simulated_active_network", time="last"))


def test_run_export_and_hmp_export_speak_the_words_of_the_toml(dated_run) -> None:
    import hydromodpy as hmp

    catalog, sid, exports = dated_run
    run = catalog[sid]
    assert run.export("head", time="2000-01-15") == [exports / "head_2000-01-15.tif"]
    assert hmp.export(run, "discharge", period=("2000-01-01", "2000-01-31")) == [
        exports / "discharge_2000-01-01_2000-01-31.csv"
    ]


@pytest.mark.parametrize("fmt", ["netcdf", "geotiff"])
def test_two_dates_that_read_one_period_are_refused_in_every_format(dated_run, fmt: str) -> None:
    catalog, sid, exports = dated_run
    request = ExportRequest(variables="head", time=["2000-01-10", "2000-01-20"], format=fmt)

    with pytest.raises(TimeSelectionError, match="'2000-01-10' and '2000-01-20' read the same"):
        export_run(catalog, sid, request)

    assert not exports.exists() or not any(exports.iterdir())


def test_an_empty_time_list_is_refused_before_any_file(dated_run) -> None:
    from pydantic import ValidationError

    catalog, sid, exports = dated_run
    with pytest.raises(ValidationError, match="names no instant"):
        catalog[sid].export("discharge", time=[])
    assert not exports.exists() or not any(exports.iterdir())


def test_a_selection_of_no_period_is_an_export_error(dated_run, monkeypatch) -> None:
    """A series asked over no period says so, never as a SQL syntax error."""
    from hydromodpy.core.exceptions import ExportError
    from hydromodpy.results.run.periods import RunPeriods

    catalog, sid, _exports = dated_run
    monkeypatch.setattr(RunPeriods, "steps_for", lambda self, **_: ())
    with pytest.raises(ExportError, match="selects no stress period"):
        export_run(catalog, sid, ExportRequest(variables="discharge", time="last"))


# The run is sealed by the run store (three monthly periods on four Lambert-93
# cells, a head field, a discharge series, the catchment outline, the budget),
# indexed, and read through the catalog. Each export format is opened as a
# reader would open it and the block is looked for in it: the GeoPackage in its
# ``gpkg_metadata`` table, every other export in its ``.meta.json`` sidecar, the
# CSV also in its ``site`` and ``case_id`` columns, the NetCDF also in its
# global attributes, a figure in its PNG text chunk, the Zarr store in its root
# attributes and every Parquet table in its schema metadata.
REQUESTS = {
    "csv": {"variables": "discharge"},
    "budget_csv": {"variables": "budget"},
    "netcdf": {"variables": "head"},
    "geotiff": {"variables": "head", "time": "2000-02-15"},
    "geopackage_field": {"variables": "head", "time": "first", "format": "geopackage"},
    "geopackage_layer": {"variables": "watershed"},
    "shapefile": {"variables": "head", "time": "first", "format": "shapefile"},
    "vtu": {"variables": "head", "time": "first", "format": "vtu"},
}


@pytest.fixture(scope="module")
def exported(tmp_path_factory) -> tuple[Path, dict[str, list[Path]], list[Path]]:
    project = tmp_path_factory.mktemp("identity") / "project"
    run_dir, sim_id = seal_demo_run(project)
    written: dict[str, list[Path]] = {}
    with Catalog(project) as catalog:
        for key, payload in REQUESTS.items():
            written[key] = export_run(catalog, sim_id, ExportRequest.model_validate(payload))
        report = render_figures_for_run(
            catalog[sim_id],
            DisplayConfig(figures=["water_budget"]),
            output_dir=figures_dir_of(run_dir),
        )
    return run_dir, written, list(report.written)


def _sim_id(run_dir: Path) -> str:
    from hydromodpy.results.outcome import read_outcome

    return read_outcome(run_dir).sim_id


def _identity(run_dir: Path) -> Identity:
    identity = read_identity_from(run_dir / "fields.zarr")
    assert identity is not None
    return identity


@pytest.mark.parametrize("key", sorted(REQUESTS))
def test_each_export_format_carries_the_block(exported, key) -> None:
    run_dir, written, _figures = exported
    assert written[key]
    for path in written[key]:
        found = read_identity_from(path)
        assert found is not None, path.name
        assert found.sim_id == _sim_id(run_dir)
        assert found.case_id == RUN_NAME


def test_a_geopackage_holds_the_block_in_its_metadata_table(exported) -> None:
    import sqlite3

    run_dir, written, _figures = exported
    (gpkg,) = written["geopackage_layer"]
    assert not gpkg.with_name(gpkg.name + ".meta.json").exists()
    with sqlite3.connect(gpkg) as connection:
        (payload,) = connection.execute("SELECT metadata FROM gpkg_metadata").fetchone()
    assert Identity.from_json(payload).sim_id == _sim_id(run_dir)


def test_every_csv_row_names_its_site_and_case(exported) -> None:
    run_dir, written, _figures = exported
    for path in written["csv"] + written["budget_csv"]:
        frame = pd.read_csv(path)
        assert list(frame.columns[:2]) == ["site", "case_id"]
        assert set(frame["case_id"]) == {RUN_NAME}


def test_a_netcdf_carries_the_block_in_its_global_attributes(exported) -> None:
    import xarray as xr

    run_dir, written, _figures = exported
    (netcdf,) = written["netcdf"]
    with xr.open_dataset(netcdf) as dataset:
        assert Identity.from_json(dataset.attrs[ZARR_IDENTITY_ATTR]).sim_id == _sim_id(run_dir)


def test_every_export_is_recorded_in_the_ledger(exported) -> None:
    run_dir, written, _figures = exported
    exports = run_dir / "exports"
    recorded = {entry.file for entry in Ledger.read(exports).entries}
    files = {path.relative_to(exports).as_posix() for paths in written.values() for path in paths}
    assert recorded == files


def test_a_figure_carries_the_block_and_its_ledger_entry(exported) -> None:
    run_dir, _written, figures = exported
    assert figures
    ledger = Ledger.read(figures_dir_of(run_dir))
    for path in figures:
        found = read_identity_from(path)
        assert found is not None
        assert found.sim_id == _sim_id(run_dir)
        assert ledger.entry_for(path.name) is not None


def test_the_field_store_and_the_tables_carry_the_block(exported) -> None:
    run_dir, _written, _figures = exported
    assert _identity(run_dir).sim_id == _sim_id(run_dir)
    tables = sorted((run_dir / "tables.parquet").glob("*.parquet"))
    assert tables
    for table in tables:
        found = read_identity_from(table)
        assert found is not None, table.name
        assert found.sim_id == _sim_id(run_dir)


# ``mesh_cells``, ``mesh_seeds`` and ``mesh_family_faces`` are placed in the CRS the
# ``mesh/`` group states. A run sealed before the cell-mesh layout states none, so it
# holds no layer and the export says why. Each run is written by its store, sealed
# and indexed; the files land under ``runs/<run>/exports/``.
Z_INTERFACES = np.array([0.0, -10.0])


LAMBERT = CRS.from_epsg(2154).to_wkt()


STAMPS_2 = pd.to_datetime(["2000-02-01", "2000-03-01"])


def _grid(*, lake_face: bool = True) -> PlanarCellMesh:
    """A 3 x 4 grid in Lambert-93 with a river over cells 4 to 7 and, when asked, a lake face."""
    base = regular_cell_mesh(xmin=500000.0, ymin=6800000.0, dx=25.0, dy=25.0, nrow=3, ncol=4)
    geometry = base.geometry
    chain = CellChain(family="rivers", chain_id=3, cell_ids=np.array([4, 5, 6, 7]))
    table = None
    if lake_face:
        rank = int(np.flatnonzero((geometry.edge_cells == [5, 9]).all(axis=1))[0])
        table = FaceFamilyTable(
            names=("lakes",),
            family=[0],
            cell_a=[5],
            cell_b=[9],
            node_a=[geometry.edge_nodes[rank, 0]],
            node_b=[geometry.edge_nodes[rank, 1]],
            zone_left=[-1],
            zone_right=[-1],
        )
    return dataclasses.replace(base, cell_chains=(chain,), face_families=table, crs_wkt=LAMBERT)


def _seal_2(
    project: Path,
    name: str,
    cell_mesh: PlanarCellMesh,
    *,
    layout: bool = True,
    before_seal: Callable[[RunStore, str], None] | None = None,
) -> str:
    """Write the mesh run *name* under *project*, seal it, index the project; return its id.

    ``before_seal`` writes more into the store of the run before its seal.
    """
    store = open_run_store(
        project,
        name,
        n_cells=cell_mesh.n_cells,
        n_layers=1,
        n_timesteps=2,
        crs_epsg=2154,
        crs_wkt="EPSG:2154",
        period_start=datetime(2000, 1, 1, tzinfo=UTC),
        period_end=datetime(2000, 3, 1, tzinfo=UTC),
        time_unit="month",
    )
    sid = store.sim_id
    store.write_time(sid, STAMPS_2.values.astype("datetime64[s]").astype("int64"))
    _write(store, sid, cell_mesh, layout=layout)
    if before_seal is not None:
        before_seal(store, sid)
    seal_completed(store)
    rebuild_index(project)
    return sid


def _write(store: RunStore, sid: str, cell_mesh: PlanarCellMesh, *, layout: bool = True) -> None:
    xy = np.asarray(cell_mesh.mesh.vertices, dtype=float)
    store.write_mesh(
        sid,
        np.column_stack([xy, np.zeros(xy.shape[0])]),
        cell_mesh.connectivity_rows,
        Z_INTERFACES,
        structured_shape=cell_mesh.structured_shape,
        layout=mesh_layout_from_cell_mesh(cell_mesh) if layout else None,
    )
    zarr_store = store.open_zarr(sid)
    try:
        zarr_store.write_topography(np.linspace(10.0, 21.0, cell_mesh.n_cells))
    finally:
        zarr_store.close()
    if layout:
        store.write_view(sid, "mesh_cell_families", cell_family_rows(cell_mesh))
        store.write_view(sid, "mesh_face_families", face_family_rows(cell_mesh))


@pytest.fixture
def runs(project: Path) -> dict[str, str]:
    """A run of the current layout, ``demo``, and one sealed before it, ``legacy``."""
    return {
        "new": _seal_2(project, "demo", _grid()),
        "old": _seal_2(project, "legacy", _grid(), layout=False),
    }


@pytest.fixture
def catalog(project: Path, runs: dict[str, str]):
    with Catalog(project) as opened:
        yield opened


@pytest.fixture
def new_run(runs: dict[str, str]) -> str:
    return runs["new"]


@pytest.fixture
def old_run(runs: dict[str, str]) -> str:
    return runs["old"]


def _exports(catalog: Catalog, sid: str) -> Path:
    return catalog.run_dir_for(sid) / "exports"


def test_the_three_layers_share_one_geopackage_in_the_crs_of_the_mesh(catalog, new_run):
    written = export_run(catalog, new_run, ExportRequest(variables=list(MESH_LAYERS)))

    assert written == [_exports(catalog, new_run) / "demo_mesh.gpkg"]
    layers = pyogrio.list_layers(written[0])
    assert sorted(layers[:, 0]) == sorted(MESH_LAYERS)
    for name in MESH_LAYERS:
        assert (
            CRS.from_user_input(pyogrio.read_info(written[0], layer=name)["crs"]).to_epsg() == 2154
        )


def test_one_layer_is_a_geopackage_named_after_it(catalog, new_run):
    written = export_run(catalog, new_run, ExportRequest(variables="mesh_seeds"))

    assert written == [_exports(catalog, new_run) / "mesh_seeds.gpkg"]
    assert pyogrio.list_layers(written[0])[:, 0].tolist() == ["mesh_seeds"]


def test_a_shapefile_holds_one_layer_per_file(catalog, new_run):
    written = export_run(
        catalog, new_run, ExportRequest(variables=["mesh_cells", "mesh_seeds"], format="shapefile")
    )

    assert sorted(path.name for path in written) == ["mesh_cells.shp", "mesh_seeds.shp"]


def test_the_cells_carry_their_area_families_and_quality(catalog, new_run):
    (path,) = export_run(catalog, new_run, ExportRequest(variables="mesh_cells"))

    cells = gpd.read_file(path, layer="mesh_cells")

    assert cells["cell_id"].tolist() == list(range(12))
    np.testing.assert_allclose(cells["area_m2"], 625.0)
    np.testing.assert_allclose(cells.geometry.area, 625.0)
    assert cells.geometry.is_valid.all()
    assert cells["family_rivers"].tolist() == [False] * 4 + [True] * 4 + [False] * 4
    assert cells.index[cells["family_lakes"]].tolist() == [5, 9]
    np.testing.assert_allclose(cells["topography"], np.linspace(10.0, 21.0, 12))
    np.testing.assert_allclose(cells["center_offset"], 0.0, atol=1e-9)
    np.testing.assert_allclose(cells["neighbour_ratio"], 1.0)
    np.testing.assert_allclose(cells["nonorthogonality_deg"], 0.0, atol=1e-6)
    np.testing.assert_allclose(cells["bisection_offset"], 0.0, atol=1e-9)
    np.testing.assert_allclose(cells["min_angle_deg"], 90.0)
    np.testing.assert_allclose(cells["max_angle_deg"], 90.0)
    np.testing.assert_array_equal(cells["concavity_deg"], 0.0)
    assert "zone" not in cells
    assert "in_basin" not in cells


def test_the_cells_say_which_ones_the_basin_of_d_holds(project):
    n_cells = _grid().n_cells
    basin = np.zeros(n_cells, dtype=bool)
    basin[[4, 5, 8]] = True
    fraction = np.where(basin, 0.75, 0.0)
    fraction[4] = 1.0
    flags = np.zeros(n_cells, dtype=bool)

    def write_descent(store: RunStore, sid: str) -> None:
        zarr_store = store.open_zarr(sid)
        try:
            zarr_store.write_descent(
                receiver=np.full(n_cells, -1, dtype=np.int64),
                surface=np.linspace(10.0, 21.0, n_cells),
                base_level=flags,
                constant_head=flags,
                raised=flags,
                channel=flags,
                pinned=flags,
                attrs={},
                basin=basin,
                basin_attrs={
                    "descent_outlet": 4,
                    "basin_rule": "near_point",
                    "basin_area_m2": 3 * 625.0,
                    "basin_seeded_at_outlet": False,
                    "basin_version": 1,
                },
                catchment_fraction=fraction,
            )
        finally:
            zarr_store.close()

    sid = _seal_2(project, "basin", _grid(), before_seal=write_descent)
    with Catalog(project) as catalog:
        (path,) = export_run(catalog, sid, ExportRequest(variables="mesh_cells"))

    cells = gpd.read_file(path, layer="mesh_cells")
    assert cells.index[cells["in_basin"]].tolist() == [4, 5, 8]
    np.testing.assert_array_equal(cells["catchment_fraction"].to_numpy(), fraction)


def test_a_seed_sits_on_the_solver_centre_and_names_its_families(catalog, new_run):
    (path,) = export_run(catalog, new_run, ExportRequest(variables="mesh_seeds"))

    seeds = gpd.read_file(path, layer="mesh_seeds")
    cell_mesh = _grid()

    np.testing.assert_allclose(seeds.geometry.x, cell_mesh.centers[:, 0])
    np.testing.assert_allclose(seeds.geometry.y, cell_mesh.centers[:, 1])
    assert set(seeds["center_kind"]) == {"cell_center"}
    expected = [""] * 12
    for cell in range(4, 8):
        expected[cell] = "rivers"
    expected[5], expected[9] = "rivers;lakes", "lakes"
    assert seeds["families"].fillna("").tolist() == expected


def test_a_family_face_is_the_segment_between_its_two_nodes(catalog, new_run):
    (path,) = export_run(catalog, new_run, ExportRequest(variables="mesh_family_faces"))

    faces = gpd.read_file(path, layer="mesh_family_faces")

    assert len(faces) == 1
    row = faces.iloc[0]
    assert (row["family"], row["face_row"], row["cell_a"], row["cell_b"]) == ("lakes", 0, 5, 9)
    # Cells 5 and 9 share a horizontal side of the 25 m grid.
    assert row.geometry.length == pytest.approx(25.0)
    assert shapely.get_coordinates(row.geometry)[:, 1].std() == pytest.approx(0.0)


def test_a_crs_reprojects_every_layer(catalog, new_run):
    (path,) = export_run(
        catalog, new_run, ExportRequest(variables=list(MESH_LAYERS), crs="EPSG:4326")
    )

    for name in MESH_LAYERS:
        assert CRS.from_user_input(pyogrio.read_info(path, layer=name)["crs"]).to_epsg() == 4326
    seed = gpd.read_file(path, layer="mesh_seeds").geometry.iloc[0]
    assert -5.0 < seed.x < 10.0
    assert 40.0 < seed.y < 52.0


def test_a_ragged_mesh_keeps_every_cell_as_a_valid_polygon(project):
    cell_mesh = bundle_dual(BUNDLE)
    cell_mesh = dataclasses.replace(cell_mesh, crs_wkt=LAMBERT)
    sid = _seal_2(project, "ragged", cell_mesh)
    with Catalog(project) as catalog:
        (path,) = export_run(catalog, sid, ExportRequest(variables="mesh_cells"))
        cells = gpd.read_file(path, layer="mesh_cells")

    assert len(cells) == cell_mesh.n_cells
    assert len({len(shapely.get_coordinates(g)) for g in cells.geometry}) > 1
    np.testing.assert_allclose(cells["area_m2"], cells.geometry.area, rtol=1e-9)
    assert cells.geometry.is_valid.all()
    families = [column for column in cells.columns if column.startswith("family_")]
    assert "family_boundary_west" in families


def test_a_mesh_without_a_crs_holds_no_mesh_layer_and_says_why(catalog, old_run):
    held = list_exportable(catalog[old_run])

    assert not set(MESH_LAYERS) & set(held)
    assert available_mesh_layers(catalog, old_run) == []
    with pytest.raises(ExportError, match=r"mesh_cells: the mesh of the run states no CRS"):
        export_run(catalog, old_run, ExportRequest(variables="mesh_cells"))
    with pytest.raises(ExportError, match="states no CRS"):
        export_mesh_layers(catalog, old_run, ["mesh_cells"], Path("unused.gpkg"))


def test_a_run_with_no_face_family_has_no_family_faces_layer(project):
    sid = _seal_2(project, "no_face", _grid(lake_face=False))

    with Catalog(project) as catalog:
        assert available_mesh_layers(catalog, sid) == ["mesh_cells", "mesh_seeds"]
        assert "no face on a line family" in mesh_layer_reasons(catalog, sid)["mesh_family_faces"]
        with pytest.raises(ExportError, match="mesh_family_faces: the mesh has no face on a line"):
            export_run(catalog, sid, ExportRequest(variables="mesh_family_faces"))


def test_variables_all_writes_the_layers_a_run_holds(catalog, new_run):
    names = list_exportable(catalog[new_run])
    assert all(names[name] is ExportKind.vector for name in MESH_LAYERS)

    written = export_run(
        catalog,
        new_run,
        ExportRequest(variables="all", format="geopackage", folder=Path("everything")),
    )

    assert not [path for path in written if "mesh_cell_area" in path.name]
    mesh_file = next(path for path in written if path.name == "demo_mesh.gpkg")
    assert sorted(pyogrio.list_layers(mesh_file)[:, 0]) == sorted(MESH_LAYERS)


def test_an_export_replaces_the_previous_file_cleanly(catalog, new_run):
    request = ExportRequest(variables=list(MESH_LAYERS))
    (first,) = export_run(catalog, new_run, request)
    (second,) = export_run(catalog, new_run, request)

    assert first == second
    assert len(pyogrio.list_layers(second)) == 3
    assert not list(second.parent.glob("*.tmp"))


def test_a_quality_field_exports_once_in_a_netcdf(catalog, new_run):
    names = list_exportable(catalog[new_run])
    assert names["mesh_cell_area"] is ExportKind.field

    (path,) = export_run(
        catalog, new_run, ExportRequest(variables="mesh_cell_area", format="netcdf")
    )

    with xr.open_dataset(path) as ds:
        assert ds["mesh_cell_area"].dims == ("n_face",)
        np.testing.assert_allclose(ds["mesh_cell_area"].values, 625.0)


def test_a_legacy_run_lists_the_area_but_not_the_centre_fields(catalog, old_run):
    names = list_exportable(catalog[old_run])

    assert names["mesh_cell_area"] is ExportKind.field
    assert "mesh_neighbour_ratio" in names
    assert "mesh_center_offset" not in names
    assert "mesh_nonorthogonality" not in names
    assert "mesh_bisection_offset" not in names
    assert names["mesh_min_angle"] is ExportKind.field
    assert names["mesh_max_angle"] is ExportKind.field
    assert names["mesh_concavity"] is ExportKind.field
