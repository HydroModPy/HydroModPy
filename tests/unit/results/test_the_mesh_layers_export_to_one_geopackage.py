"""The cell mesh of a run exports as three vector layers that share one GeoPackage.

``mesh_cells``, ``mesh_seeds`` and ``mesh_family_faces`` are placed in the CRS the
``mesh/`` group states. A run sealed before the cell-mesh layout states none, so it
holds no layer and the export says why. Each run is written by its store, sealed
and indexed; the files land under ``runs/<run>/exports/``.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import pytest
import shapely
import xarray as xr
from pyproj import CRS

from hydromodpy.core.config_kit.export_spec import MESH_LAYERS, ExportKind, ExportRequest
from hydromodpy.core.exceptions import ExportError
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.exporters.mesh_layers import (
    available_mesh_layers,
    export_mesh_layers,
    mesh_layer_reasons,
)
from hydromodpy.results.exporters.request import export_run
from hydromodpy.results.exporters.vocabulary import list_exportable
from hydromodpy.results.storage.run_store import RunStore
from hydromodpy.results.storage.sealing import seal_completed
from hydromodpy.results.zarr_store.mesh_layout import (
    cell_family_rows,
    face_family_rows,
    mesh_layout_from_cell_mesh,
)
from hydromodpy.spatial.mesh.model.planar_cell_mesh import (
    CellChain,
    FaceFamilyTable,
    PlanarCellMesh,
)
from tests._helpers.bundle_cell_meshes import bundle_dual
from tests._helpers.regular_cell_meshes import regular_cell_mesh
from tests._helpers.run_stores import open_run_store

Z_INTERFACES = np.array([0.0, -10.0])
LAMBERT = CRS.from_epsg(2154).to_wkt()
STAMPS = pd.to_datetime(["2000-02-01", "2000-03-01"])
BUNDLE = "stream_depletion_glover_balmer_tri_refined_well"


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


def _seal(
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
    store.write_time(sid, STAMPS.values.astype("datetime64[s]").astype("int64"))
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
def project(tmp_path: Path) -> Path:
    return tmp_path / "workspace"


@pytest.fixture
def runs(project: Path) -> dict[str, str]:
    """A run of the current layout, ``demo``, and one sealed before it, ``legacy``."""
    return {
        "new": _seal(project, "demo", _grid()),
        "old": _seal(project, "legacy", _grid(), layout=False),
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
    assert "zone" not in cells
    assert "in_basin" not in cells


def test_the_cells_say_which_ones_the_basin_of_d_holds(project):
    n_cells = _grid().n_cells
    basin = np.zeros(n_cells, dtype=bool)
    basin[[4, 5, 8]] = True
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
            )
        finally:
            zarr_store.close()

    sid = _seal(project, "basin", _grid(), before_seal=write_descent)
    with Catalog(project) as catalog:
        (path,) = export_run(catalog, sid, ExportRequest(variables="mesh_cells"))

    cells = gpd.read_file(path, layer="mesh_cells")
    assert cells.index[cells["in_basin"]].tolist() == [4, 5, 8]


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
    sid = _seal(project, "ragged", cell_mesh)
    with Catalog(project) as catalog:
        (path,) = export_run(catalog, sid, ExportRequest(variables="mesh_cells"))
        cells = gpd.read_file(path, layer="mesh_cells")

    assert len(cells) == cell_mesh.n_cells
    assert len({len(shapely.get_coordinates(g)) for g in cells.geometry}) > 1
    np.testing.assert_allclose(cells["area_m2"], cells.geometry.area, rtol=1e-9)
    assert cells.geometry.is_valid.all()
    families = [column for column in cells.columns if column.startswith("family_")]
    assert "family_boundary_west" in families


def test_a_run_sealed_before_the_layout_holds_no_mesh_layer_and_says_why(catalog, old_run):
    held = list_exportable(catalog[old_run])

    assert not set(MESH_LAYERS) & set(held)
    assert available_mesh_layers(catalog, old_run) == []
    with pytest.raises(ExportError, match=r"mesh_cells: the run was sealed before the cell-mesh"):
        export_run(catalog, old_run, ExportRequest(variables="mesh_cells"))
    with pytest.raises(ExportError, match="states no CRS"):
        export_mesh_layers(catalog, old_run, ["mesh_cells"], Path("unused.gpkg"))


def test_a_run_with_no_face_family_has_no_family_faces_layer(project):
    sid = _seal(project, "no_face", _grid(lake_face=False))

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
