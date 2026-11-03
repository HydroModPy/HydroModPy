"""The run store keeps the cell mesh once, with its centers, families and edges.

``step_persist_mesh`` writes the geometry and the layout before the run. The solver
extractors add the vertical part afterwards and never rewrite vertices or
connectivity. A layout read back gives the families of the ``PlanarCellMesh`` it
came from, and xugrid reads the stored edges as they are.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import zarr

from hydromodpy.core.exceptions import IncompatibleMeshError
from hydromodpy.results.zarr_store import SimulationZarr
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
from hydromodpy.workflow.steps.prepare_solver.prepare import step_persist_mesh
from tests._helpers.bundle_cell_meshes import bundle_dual, bundle_triangles
from tests._helpers.regular_cell_meshes import regular_cell_mesh

BUNDLE = "stream_depletion_glover_balmer_tri_refined_well"
Z_INTERFACES = np.array([0.0, -10.0])


def _river_grid() -> PlanarCellMesh:
    """A 3 x 4 regular grid with a river chain and one lake face."""
    base = regular_cell_mesh(xmin=500000.0, ymin=6800000.0, dx=25.0, dy=25.0, nrow=3, ncol=4)
    geometry = base.geometry
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
    chain = CellChain(family="rivers", chain_id=3, cell_ids=np.array([4, 5, 6, 7]))
    return dataclasses.replace(base, cell_chains=(chain,), face_families=table)


def _zoned_triangles() -> PlanarCellMesh:
    """The triangles of the bundle in two zones, split at the median x, with their contact faces."""
    base = bundle_triangles(BUNDLE)
    zone = (base.centers[:, 0] > np.median(base.centers[:, 0])).astype(np.int32)
    geometry = base.geometry
    cell_a, cell_b = geometry.edge_cells[:, 0], geometry.edge_cells[:, 1]
    contact = np.flatnonzero((cell_b >= 0) & (zone[cell_a] != zone[np.maximum(cell_b, 0)]))
    table = FaceFamilyTable(
        names=("geology",),
        family=np.zeros(contact.size),
        cell_a=cell_a[contact],
        cell_b=cell_b[contact],
        node_a=geometry.edge_nodes[contact, 0],
        node_b=geometry.edge_nodes[contact, 1],
        zone_left=zone[cell_a[contact]],
        zone_right=zone[cell_b[contact]],
    )
    return dataclasses.replace(
        base, cell_zone=zone, zone_names=("east", "west"), face_families=table
    )


def _vertices_3d(cell_mesh: PlanarCellMesh) -> np.ndarray:
    xy = np.asarray(cell_mesh.mesh.vertices, dtype=float)
    return np.column_stack([xy, np.zeros(xy.shape[0])])


def _store(path: Path, cell_mesh: PlanarCellMesh, *, with_layout: bool = True) -> SimulationZarr:
    store = SimulationZarr.create(path, n_cells=cell_mesh.n_cells, n_layers=1)
    store.write_mesh(
        _vertices_3d(cell_mesh),
        cell_mesh.connectivity_rows,
        Z_INTERFACES,
        structured_shape=cell_mesh.structured_shape,
        layout=mesh_layout_from_cell_mesh(cell_mesh) if with_layout else None,
    )
    return store


def _members(group: zarr.Group) -> set[str]:
    return {name for name, _ in group.members()}


def test_a_layout_adds_the_centres_the_families_and_the_edges(tmp_path):
    cell_mesh = _river_grid()
    store = _store(tmp_path / "fields.zarr", cell_mesh)
    mesh = store.root["mesh"]

    assert {
        "face_x",
        "face_y",
        "face_family",
        "edge_node_connectivity",
        "edge_face_connectivity",
        "edge_family",
    } <= _members(mesh)
    assert "face_zone" not in _members(mesh)
    assert np.array_equal(mesh["face_x"][:], cell_mesh.centers[:, 0])
    assert np.array_equal(mesh["face_y"][:], cell_mesh.centers[:, 1])
    assert mesh["face_x"].attrs["center_kind"] == "cell_center"
    assert mesh["face_x"].metadata.dimension_names == ("face",)
    assert mesh["edge_node_connectivity"].metadata.dimension_names == ("edge", "two")
    assert mesh["edge_family"].metadata.dimension_names == ("edge",)
    assert mesh["edge_node_connectivity"].dtype == np.int32
    assert np.array_equal(
        mesh["edge_node_connectivity"][:], cell_mesh.geometry.edge_nodes.astype(np.int32)
    )
    assert mesh["topology"].attrs["face_coordinates"] == "face_x face_y"
    assert mesh["topology"].attrs["edge_node_connectivity"] == "edge_node_connectivity"
    store.close()


def test_a_stored_layout_gives_back_the_families_of_the_mesh(tmp_path):
    cell_mesh = _river_grid()
    store = _store(tmp_path / "fields.zarr", cell_mesh)
    mesh = store.root["mesh"]
    attrs = dict(mesh["face_family"].attrs)

    assert attrs["family_names"] == ["rivers", "lakes"]
    assert attrs["flag_masks"] == [1, 2]
    assert attrs["flag_meanings"] == "rivers lakes"
    bits = mesh["face_family"][:]
    for k, name in enumerate(attrs["family_names"]):
        assert np.flatnonzero(bits & attrs["flag_masks"][k]).tolist() == (
            cell_mesh.family_cells(name).tolist()
        )
    assert dict(mesh["edge_family"].attrs)["family_names"] == ["lakes"]
    assert np.flatnonzero(mesh["edge_family"][:]).size == 1
    store.close()


def test_a_family_name_is_made_cf_safe_in_the_flag_meanings_only(tmp_path):
    cell_mesh = bundle_dual(BUNDLE)
    store = SimulationZarr.create(tmp_path / "fields.zarr", n_cells=cell_mesh.n_cells, n_layers=1)
    store.write_mesh(
        _vertices_3d(cell_mesh),
        cell_mesh.connectivity_rows,
        Z_INTERFACES,
        layout=mesh_layout_from_cell_mesh(cell_mesh),
    )
    attrs = dict(store.root["mesh"]["face_family"].attrs)

    assert "boundary:west" in attrs["family_names"]
    assert "boundary_west" in attrs["flag_meanings"].split()
    assert ":" not in attrs["flag_meanings"]
    store.close()


def test_the_group_names_the_engine_the_crs_and_the_request(tmp_path):
    cell_mesh = _river_grid()
    qa = {"p50": 1.0, "ratio": float("nan"), "far": float("inf"), "nested": {"v": np.float64(2.5)}}
    layout = mesh_layout_from_cell_mesh(
        cell_mesh, request_hash="ab12", qa=qa, library_versions={"shapely": "2.0.6"}
    )
    store = SimulationZarr.create(tmp_path / "fields.zarr", n_cells=cell_mesh.n_cells, n_layers=1)
    store.write_mesh(
        _vertices_3d(cell_mesh),
        cell_mesh.connectivity_rows,
        Z_INTERFACES,
        structured_shape=cell_mesh.structured_shape,
        layout=layout,
    )
    attrs = dict(store.root["mesh"].attrs)

    assert attrs["engine"] == "regular"
    assert attrs["engine_version"] == "0"
    assert attrs["crs"] == cell_mesh.crs_wkt
    assert attrs["mesh_request_hash"] == "ab12"
    assert attrs["library_versions"] == {"shapely": "2.0.6"}
    assert attrs["structured_shape"] == [3, 4]
    assert "engine_seed" not in attrs
    assert attrs["qa"] == {"p50": 1.0, "ratio": None, "far": None, "nested": {"v": 2.5}}
    store.close()
    json.loads((tmp_path / "fields.zarr" / "mesh" / "zarr.json").read_text(), parse_constant=_no)


def _no(token: str) -> None:
    raise AssertionError(f"the store holds the bare JSON token {token}")


def test_a_mesh_without_summary_leaves_the_request_and_the_qa_out(tmp_path):
    cell_mesh = _river_grid()
    attrs = mesh_layout_from_cell_mesh(cell_mesh).attrs

    assert {"mesh_request_hash", "qa", "library_versions"}.isdisjoint(attrs)


def test_the_zones_of_a_triangle_mesh_are_stored_by_name(tmp_path):
    cell_mesh = _zoned_triangles()
    store = _store(tmp_path / "fields.zarr", cell_mesh)
    zone = store.root["mesh"]["face_zone"]

    assert zone.attrs["zone_names"] == list(cell_mesh.zone_names)
    assert np.array_equal(zone[:], cell_mesh.cell_zone)
    store.close()


def test_without_a_layout_the_group_holds_the_topology_alone(tmp_path):
    cell_mesh = _river_grid()
    store = _store(tmp_path / "fields.zarr", cell_mesh, with_layout=False)

    assert _members(store.root["mesh"]) == {
        "vertices",
        "node_x",
        "node_y",
        "face_node_connectivity",
        "z_interfaces",
        "topology",
    }
    assert "engine" not in store.root["mesh"].attrs
    store.close()


def test_xugrid_reads_the_stored_edges_as_they_are(tmp_path):
    import xugrid as xu

    cell_mesh = bundle_triangles(BUNDLE)
    store = _store(tmp_path / "fields.zarr", cell_mesh)
    mesh = store.root["mesh"]
    grid = xu.Ugrid2d(
        node_x=mesh["vertices"][:, 0],
        node_y=mesh["vertices"][:, 1],
        fill_value=-1,
        face_node_connectivity=mesh["face_node_connectivity"][:],
        edge_node_connectivity=mesh["edge_node_connectivity"][:],
    )

    assert np.array_equal(grid.edge_node_connectivity, mesh["edge_node_connectivity"][:])
    stored = {tuple(sorted(row)) for row in mesh["edge_face_connectivity"][:].tolist()}
    derived = {tuple(sorted(row)) for row in grid.edge_face_connectivity.tolist()}
    assert stored == derived
    assert mesh["edge_family"].shape[0] == grid.n_edge
    store.close()


def test_a_stranger_opens_the_mesh_group_with_xarray(tmp_path):
    import xarray as xr

    cell_mesh = bundle_triangles(BUNDLE)
    store = _store(tmp_path / "fields.zarr", cell_mesh)
    store.close()

    with xr.open_zarr(tmp_path / "fields.zarr", group="mesh", consolidated=False) as ds:
        assert ds["face_x"].dims == ("face",)
        assert ds["edge_node_connectivity"].dims == ("edge", "two")
        assert ds.sizes["edge"] == cell_mesh.geometry.edge_nodes.shape[0]
        assert ds.attrs["engine"] == "triangle"


def test_a_layout_of_another_mesh_is_refused(tmp_path):
    cell_mesh = _river_grid()
    other = bundle_dual(BUNDLE)
    store = SimulationZarr.create(tmp_path / "fields.zarr", n_cells=cell_mesh.n_cells, n_layers=1)

    with pytest.raises(IncompatibleMeshError, match="cells"):
        store.write_mesh(
            _vertices_3d(cell_mesh),
            cell_mesh.connectivity_rows,
            Z_INTERFACES,
            layout=mesh_layout_from_cell_mesh(other),
        )
    store.close()


def test_the_post_run_writer_adds_the_vertical_part_and_keeps_the_geometry(tmp_path):
    cell_mesh = _river_grid()
    store = _store(tmp_path / "fields.zarr", cell_mesh)
    mesh = store.root["mesh"]
    vertices = mesh["vertices"][:]
    connectivity = mesh["face_node_connectivity"][:]
    n = cell_mesh.n_cells

    store.write_topography(
        np.linspace(10.0, 20.0, n),
        z_interfaces=np.array([0.0, -5.0, -9.0]),
        n_cells=n,
        n_layers=2,
        layer_thickness=np.full((2, n), 4.0),
        streambed_top=np.full(n, 9.0),
        streambed_connection=np.full(n, 1.0),
        grid_type="disv",
    )
    mesh = store.root["mesh"]

    assert {"topography", "layer_thickness", "streambed_top", "streambed_connection"} <= _members(
        mesh
    )
    assert mesh.attrs["grid_type"] == "disv"
    assert mesh.attrs["n_layers"] == 2
    assert mesh.attrs["engine"] == "regular"
    assert np.array_equal(mesh["vertices"][:], vertices)
    assert np.array_equal(mesh["face_node_connectivity"][:], connectivity)
    store.close()


def test_the_post_run_writer_refuses_a_grid_of_another_size(tmp_path):
    cell_mesh = _river_grid()
    store = _store(tmp_path / "fields.zarr", cell_mesh)

    with pytest.raises(IncompatibleMeshError, match="12 cells|13 cells"):
        store.write_topography(np.zeros(13), n_cells=13)
    assert store.root["mesh"].attrs["n_cells"] == cell_mesh.n_cells
    store.close()


def test_the_post_run_writer_sets_the_count_of_a_store_with_no_geometry(tmp_path):
    store = SimulationZarr.create(tmp_path / "fields.zarr", n_cells=6, n_layers=1)

    store.write_topography(np.zeros(6), n_cells=6, n_layers=1)

    assert store.root["mesh"].attrs["n_cells"] == 6
    store.close()


class _RecordingStore:
    """A store that records what ``step_persist_mesh`` hands it."""

    def __init__(self) -> None:
        self.meshes: list[dict] = []
        self.views: dict[str, list[dict]] = {}

    def write_mesh(self, sim_id, **kwargs) -> None:
        self.meshes.append(kwargs)

    def write_view(self, sim_id, view_name, records) -> None:
        self.views[view_name] = list(records)


def _context(cell_mesh: PlanarCellMesh, summary: dict | None) -> SimpleNamespace:
    domain = SimpleNamespace(z_interfaces=Z_INTERFACES)
    return SimpleNamespace(
        setup=SimpleNamespace(domain=domain, cell_mesh=cell_mesh, mesh_summary=summary)
    )


def test_the_workflow_writes_the_mesh_once_with_its_summary():
    cell_mesh = _river_grid()
    store = _RecordingStore()
    summary = {"request_hash": "feed", "qa": {"n_cells": 12}, "library_versions": {"scipy": "1.0"}}

    step_persist_mesh(_context(cell_mesh, summary), "sim", store=store)

    assert len(store.meshes) == 1
    written = store.meshes[0]
    assert np.array_equal(written["vertices"], _vertices_3d(cell_mesh))
    assert written["structured_shape"] == (3, 4)
    attrs = written["layout"].attrs
    assert attrs["mesh_request_hash"] == "feed"
    assert attrs["qa"] == {"n_cells": 12}
    assert attrs["library_versions"] == {"scipy": "1.0"}


def test_the_workflow_writes_the_two_family_tables():
    cell_mesh = _river_grid()
    store = _RecordingStore()

    step_persist_mesh(_context(cell_mesh, None), "sim", store=store)

    cells = store.views["mesh_cell_families"]
    assert [(r["family"], r["chain_id"], r["position"], r["cell_id"]) for r in cells] == [
        ("rivers", 3, 0, 4),
        ("rivers", 3, 1, 5),
        ("rivers", 3, 2, 6),
        ("rivers", 3, 3, 7),
    ]
    assert [r["offset_m"] for r in cells] == [None] * 4
    (face,) = store.views["mesh_face_families"]
    assert (face["family"], face["cell_a"], face["cell_b"], face["face_row"]) == ("lakes", 5, 9, 0)
    assert face["zone_left"] is None
    edge = cell_mesh.geometry.edge_nodes[face["edge_id"]]
    assert sorted([face["node_a"], face["node_b"]]) == edge.tolist()


def test_the_offsets_of_a_chain_fill_the_offset_column():
    base = _river_grid()
    chain = CellChain("rivers", 3, np.array([4, 5, 6]), offset_m=[0.0, 3.5, 0.0])
    cell_mesh = dataclasses.replace(base, cell_chains=(chain,))

    assert [r["offset_m"] for r in cell_family_rows(cell_mesh)] == [0.0, 3.5, 0.0]


def test_a_zone_index_becomes_its_name_in_the_face_table():
    cell_mesh = _zoned_triangles()

    rows = face_family_rows(cell_mesh)
    table = cell_mesh.face_families

    assert len(rows) == table.n_rows
    named = [r for r in rows if r["zone_left"] is not None]
    assert named
    assert {r["zone_left"] for r in named} <= set(cell_mesh.zone_names)
    assert all(r["zone_right"] is None for r, z in zip(rows, table.zone_right) if z < 0)
    assert cell_family_rows(cell_mesh) == []
