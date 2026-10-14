"""A run says whether its mesh was stored with the cell-mesh layout, and what it lacks if not.

The new layout stores the cell centres, the families, the edges and the engine on
``mesh/``. A run sealed before has the vertices and the connectivity only: its mesh
reads as ``legacy``, its CRS comes from the catalog, and the readers that need what
it lacks refuse with the reason rather than guess.
"""

from __future__ import annotations

import dataclasses
import logging
import uuid
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.results.catalog import Catalog
from hydromodpy.results.derive.mesh_quality import MESH_QUALITY_DESCRIPTORS
from hydromodpy.results.derive.reading import read_variable
from hydromodpy.results.errors import FieldNotFoundError
from hydromodpy.results.manifest import build_manifest
from hydromodpy.results.run import Run
from hydromodpy.results.run.contracts import LEGACY_MESH_NOTE
from hydromodpy.results.run.mesh_families import mesh_families
from hydromodpy.results.zarr_store.mesh_layout import (
    cell_family_rows,
    face_family_rows,
    mesh_layout_from_cell_mesh,
)
from hydromodpy.spatial.mesh.model.planar_cell_mesh import CellChain, PlanarCellMesh
from tests._helpers.regular_cell_meshes import regular_cell_mesh

Z_INTERFACES = np.array([0.0, -10.0])
CRS = "EPSG:2154"


def _grid(*, with_river: bool = True) -> PlanarCellMesh:
    """A 3 x 4 regular grid, a river over the cells 4 to 7 when asked."""
    base = regular_cell_mesh(xmin=500000.0, ymin=6800000.0, dx=25.0, dy=25.0, nrow=3, ncol=4)
    if not with_river:
        return base
    chain = CellChain(family="rivers", chain_id=3, cell_ids=np.array([4, 5, 6, 7]))
    return dataclasses.replace(base, cell_chains=(chain,))


def _register(catalog: Catalog, cell_mesh: PlanarCellMesh, *, engine: str | None = None) -> str:
    sid = str(uuid.uuid4())
    config = None if engine is None else {"mesh": {"engine": engine}}
    registration = catalog.register_simulation(
        sid,
        project="demo",
        solver="modflow6",
        config=config,
        n_cells=cell_mesh.n_cells,
        n_layers=1,
    )
    if registration.zarr is not None:
        registration.zarr.close()
    return sid


def _write(catalog: Catalog, sid: str, cell_mesh: PlanarCellMesh, *, layout: bool) -> None:
    xy = np.asarray(cell_mesh.mesh.vertices, dtype=float)
    catalog.write_mesh(
        sid,
        np.column_stack([xy, np.zeros(xy.shape[0])]),
        cell_mesh.connectivity_rows,
        Z_INTERFACES,
        structured_shape=cell_mesh.structured_shape,
        layout=mesh_layout_from_cell_mesh(cell_mesh) if layout else None,
    )
    if layout:
        catalog.write_view(sid, "mesh_cell_families", cell_family_rows(cell_mesh))
        catalog.write_view(sid, "mesh_face_families", face_family_rows(cell_mesh))


@pytest.fixture
def catalog(tmp_path: Path):
    with Catalog(tmp_path / "demo") as opened:
        yield opened


@pytest.fixture
def new_run(catalog: Catalog) -> Run:
    cell_mesh = _grid()
    sid = _register(catalog, cell_mesh, engine="regular")
    _write(catalog, sid, cell_mesh, layout=True)
    return Run(sid, catalog)


@pytest.fixture
def old_run(catalog: Catalog) -> Run:
    cell_mesh = _grid()
    sid = _register(catalog, cell_mesh)
    _write(catalog, sid, cell_mesh, layout=False)
    return Run(sid, catalog)


def test_a_mesh_stored_with_the_layout_names_its_engine_and_its_crs(new_run):
    mesh = new_run.mesh

    assert mesh.layout == "cell_mesh"
    assert mesh.layout_note == ""
    assert mesh.identity is not None
    assert (mesh.identity.engine, mesh.identity.engine_version) == ("regular", "0")
    assert mesh.identity.center_kind == "cell_center"
    assert mesh.crs_source == "mesh"
    assert mesh.crs is not None
    assert mesh.face_x is not None
    assert mesh.structured_shape == (3, 4)


def test_a_mesh_stored_before_the_layout_reads_as_legacy_with_the_catalog_crs(catalog, old_run):
    catalog.write_geographic_metadata(old_run.sim_id, {"crs_proj": CRS})

    mesh = old_run.mesh

    assert mesh.layout == "legacy"
    assert mesh.layout_note == LEGACY_MESH_NOTE
    assert "centres are vertex means" in mesh.layout_note
    assert mesh.identity is None
    assert (mesh.crs, mesh.crs_source) == (CRS, "catalog")
    assert mesh.face_x is None
    expected = _grid().mesh.cell_centroids()
    np.testing.assert_allclose(mesh.cell_centers(), np.column_stack(expected), atol=1e-6)


def test_a_legacy_mesh_with_no_crs_anywhere_says_so(old_run):
    mesh = old_run.mesh

    assert mesh.crs is None
    assert mesh.crs_source is None


def test_the_legacy_layout_is_logged_once_per_run(old_run, caplog):
    with caplog.at_level(logging.INFO, logger="hydromodpy.results.run.geographic"):
        assert old_run.mesh.layout == "legacy"
        assert old_run.mesh.layout == "legacy"

    notes = [r for r in caplog.records if LEGACY_MESH_NOTE in r.getMessage()]
    assert len(notes) == 1


def test_a_mesh_with_the_layout_logs_no_note(new_run, caplog):
    with caplog.at_level(logging.INFO, logger="hydromodpy.results.run.geographic"):
        assert new_run.mesh.layout == "cell_mesh"

    assert not [r for r in caplog.records if "cell-mesh layout" in r.getMessage()]


def test_the_families_of_a_new_run_come_back_from_the_tables(new_run):
    families = mesh_families(new_run)

    assert families.cells["family"].unique().tolist() == ["rivers"]
    assert families.cells["chain_id"].tolist() == [3, 3, 3, 3]
    assert families.cells["position"].tolist() == [0, 1, 2, 3]
    assert families.cells["cell_id"].tolist() == [4, 5, 6, 7]
    assert "sim_id" not in families.cells
    assert families.faces.empty
    assert "face_row" in families.faces


def test_a_new_run_with_no_family_has_two_empty_tables(catalog):
    cell_mesh = _grid(with_river=False)
    sid = _register(catalog, cell_mesh, engine="regular")
    _write(catalog, sid, cell_mesh, layout=True)

    families = mesh_families(Run(sid, catalog))

    assert families.cells.empty
    assert families.faces.empty


def test_a_legacy_run_has_no_families_and_says_why(old_run):
    with pytest.raises(FieldNotFoundError, match="sealed before mesh families were stored"):
        mesh_families(old_run)


def test_a_legacy_run_serves_the_area_and_refuses_the_centre_fields_with_the_reason(old_run):
    area = old_run.field("mesh_cell_area")

    np.testing.assert_allclose(area, np.full(12, 625.0), rtol=1e-12)
    assert old_run.has_field("mesh_cell_area")
    assert not old_run.has_field("mesh_center_offset")
    with pytest.raises(FieldNotFoundError, match="before the cell-mesh layout.*cell centres"):
        old_run.field("mesh_center_offset")


def test_a_new_run_serves_every_quality_field(new_run):
    for name in ("mesh_cell_area", "mesh_neighbour_ratio", "mesh_center_offset"):
        assert new_run.has_field(name)
    np.testing.assert_allclose(new_run.field("mesh_center_offset"), np.zeros(12), atol=1e-12)
    np.testing.assert_allclose(new_run.field("mesh_nonorthogonality"), np.zeros(12), atol=1e-9)


def test_hmp_read_serves_every_quality_field_a_run_reports(new_run):
    for name in MESH_QUALITY_DESCRIPTORS:
        assert new_run.has_field(name)
        assert read_variable(new_run, name).shape == (12,)
        assert read_variable(new_run, name, time=3).shape == (12,)


def test_hmp_read_refuses_a_centre_field_of_a_legacy_run_with_the_reason(old_run):
    np.testing.assert_allclose(read_variable(old_run, "mesh_cell_area"), np.full(12, 625.0))
    with pytest.raises(FieldNotFoundError, match="before the cell-mesh layout.*cell centres"):
        read_variable(old_run, "mesh_center_offset")


def test_the_manifest_names_the_engine_of_a_new_run_and_nothing_for_an_old_one(
    catalog, new_run, old_run
):
    new = build_manifest(catalog, new_run.sim_id)["geometry"]
    old = build_manifest(catalog, old_run.sim_id)["geometry"]

    assert (new["mesh_engine"], new["mesh_engine_version"]) == ("regular", "0")
    assert "mesh_engine" not in old
    assert "mesh_engine_version" not in old


def test_the_dataset_of_a_new_run_keeps_the_stored_edge_numbering(new_run):
    cell_mesh = _grid()

    grid = new_run.array.dataset().ugrid.grid

    np.testing.assert_array_equal(
        grid.edge_node_connectivity, cell_mesh.geometry.edge_nodes.astype(np.int32)
    )
    np.testing.assert_array_equal(
        grid.edge_face_connectivity.astype(np.int64), cell_mesh.geometry.edge_cells
    )
