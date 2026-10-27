"""A Boussinesq mesh reads its river, sides and cells from the face families of its cell mesh.

The four committed mesh bundles are the oracle, with a river flagged along their middle.
The river edges are the ``is_river`` flags of the bundle files and the sides are the
boundary edges on the bounding box of the edge midpoints. A mesh built from the bundle and
a mesh built from the same triangles as a cell mesh must find the same edges and cells.
"""

from __future__ import annotations

from dataclasses import replace
from functools import cache, lru_cache
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.solver.boussinesq.adapters.flow import BoussinesqFlowAdapter
from hydromodpy.solver.boussinesq.forcing_resolution import BoussinesqForcingResolver
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh
from hydromodpy.spatial.mesh.io.bundle import (
    CatchmentMeshBundle,
    cell_mesh_from_bundle,
    load_catchment_mesh_bundle,
)
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh
from hydromodpy.spatial.mesh.ops.family_cells import SIDE_IDS, stream_cells
from tests._helpers.bundle_cell_meshes import BUNDLE_CASES
from tests._helpers.cell_meshes import TEST_CRS_WKT
from tests._helpers.mesh_cases import MESH_BUNDLES

pytestmark = pytest.mark.fast

TOP_M, BOTTOM_M = 10.0, 0.0
K_M_S, SY = 1.0e-5, 0.1


def _constant_surface(cell_mesh: PlanarCellMesh, value: float) -> SimpleNamespace:
    """A raster of one value covering the cell mesh, as the domain surfaces are sampled."""
    xmin, ymin, xmax, ymax = cell_mesh.mesh.bounds()
    support = SimpleNamespace(
        xmin=xmin - 1.0,
        xmax=xmax + 1.0,
        ymin=ymin - 1.0,
        ymax=ymax + 1.0,
        dx=xmax - xmin + 2.0,
        dy=ymax - ymin + 2.0,
        nrows=1,
        ncols=1,
        nodata=None,
    )
    return SimpleNamespace(values=np.full((1, 1), value), support=support)


@cache
def _bundle(case: str) -> CatchmentMeshBundle:
    """The bundle with a river along its middle: the committed bundles flag none."""
    bundle = load_catchment_mesh_bundle(MESH_BUNDLES / case)
    node_x = {node.node_id: node.x for node in bundle.nodes}
    midpoint = {
        edge.edge_id: 0.5 * (node_x[edge.node_a] + node_x[edge.node_b]) for edge in bundle.edges
    }
    x_mid = float(np.median(list(midpoint.values())))
    band = 0.05 * (max(node_x.values()) - min(node_x.values()))
    edges = tuple(
        replace(
            edge, is_river=edge.cell_b is not None and abs(midpoint[edge.edge_id] - x_mid) < band
        )
        for edge in bundle.edges
    )
    cells = tuple(
        replace(
            cell,
            z_top_centroid=TOP_M,
            z_bottom_centroid=BOTTOM_M,
            hydraulic_conductivity_m_s=K_M_S,
            storage_coefficient=SY,
        )
        for cell in bundle.cells
    )
    return replace(bundle, edges=edges, cells=cells)


@cache
def _cell_mesh(case: str) -> PlanarCellMesh:
    """The triangles of the bundle as a cell mesh, with its river and side families."""
    return cell_mesh_from_bundle(_bundle(case), crs_wkt=TEST_CRS_WKT)


@cache
def _from_cell_mesh(case: str) -> BoussinesqMesh:
    cell_mesh = _cell_mesh(case)
    domain = SimpleNamespace(
        surface_topo=_constant_surface(cell_mesh, TOP_M),
        substratum=_constant_surface(cell_mesh, BOTTOM_M),
    )
    return BoussinesqMesh.from_cell_mesh(
        cell_mesh,
        domain=domain,
        hydraulic_conductivity_m_s=np.full(cell_mesh.n_cells, K_M_S),
        storage_coefficient=np.full(cell_mesh.n_cells, SY),
    )


@cache
def _from_bundle(case: str) -> BoussinesqMesh:
    return BoussinesqMesh.from_bundle(_bundle(case))


def _node_pairs(mesh: BoussinesqMesh, edges: np.ndarray) -> set[tuple[int, int]]:
    """The edges as pairs of node positions, whatever the order of the edge table."""
    node_a = [mesh.node_index_by_id[int(i)] for i in mesh.edge_node_a[edges]]
    node_b = [mesh.node_index_by_id[int(i)] for i in mesh.edge_node_b[edges]]
    return {(min(a, b), max(a, b)) for a, b in zip(node_a, node_b, strict=True)}


def _edges_on_side(mesh: BoussinesqMesh, side: str) -> np.ndarray:
    """The boundary edges whose midpoint lies on a side of the bounding box of the nodes."""
    span = max(mesh.x_max_m - mesh.x_min_m, mesh.y_max_m - mesh.y_min_m, 1.0)
    tolerance = max(1.0e-9, 1.0e-8 * span)
    midpoint, edge = {
        "west_side": (mesh.edge_midpoint_x_m, mesh.x_min_m),
        "east_side": (mesh.edge_midpoint_x_m, mesh.x_max_m),
        "south_side": (mesh.edge_midpoint_y_m, mesh.y_min_m),
        "north_side": (mesh.edge_midpoint_y_m, mesh.y_max_m),
    }[side]
    return np.flatnonzero(
        mesh.boundary_edge_mask & np.isclose(midpoint, edge, atol=tolerance, rtol=0)
    )


@pytest.mark.parametrize("case", BUNDLE_CASES)
@pytest.mark.parametrize("build", [_from_bundle, _from_cell_mesh])
def test_the_river_edges_and_cells_are_those_the_bundle_files_flag(case: str, build) -> None:
    mesh, reference = build(case), _from_bundle(case)
    flagged = reference.river_edge_indices()

    assert flagged.size > 0
    assert _node_pairs(mesh, mesh.river_edge_indices()) == _node_pairs(reference, flagged)
    assert np.array_equal(mesh.family_edge_indices("rivers"), mesh.river_edge_indices())
    assert np.array_equal(mesh.edge_indices_for_label("stream"), mesh.river_edge_indices())
    both_banks = np.unique(
        np.concatenate([reference.edge_cell_a[flagged], reference.edge_cell_b[flagged]])
    )
    assert np.array_equal(mesh.cell_indices_for_label("stream"), both_banks[both_banks >= 0])
    assert np.array_equal(
        mesh.cell_indices_for_label("river"), mesh.cell_indices_for_label("stream")
    )


@pytest.mark.parametrize("case", BUNDLE_CASES)
@pytest.mark.parametrize("side", SIDE_IDS)
@pytest.mark.parametrize("build", [_from_bundle, _from_cell_mesh])
def test_the_side_edges_and_cells_are_those_of_the_bounding_box_rule(
    case: str, side: str, build
) -> None:
    mesh, reference = build(case), _from_bundle(case)

    edges = _edges_on_side(reference, side)
    assert _node_pairs(mesh, mesh.boundary_edge_indices_for_side(side)) == _node_pairs(
        reference, edges
    )
    owners = np.unique(reference.edge_cell_a[edges])
    assert np.array_equal(mesh.boundary_cell_indices_for_side(side), owners)
    assert np.array_equal(
        mesh.cell_indices_for_label(side), mesh.boundary_cell_indices_for_side(side)
    )
    assert np.array_equal(
        mesh.edge_indices_for_label(side), mesh.boundary_edge_indices_for_side(side)
    )


@pytest.mark.parametrize("case", BUNDLE_CASES)
def test_the_edge_indices_follow_the_order_of_the_bundle_edge_file(case: str) -> None:
    bundle = _bundle(case)
    mesh = _from_bundle(case)

    assert np.array_equal(mesh.edge_ids, [edge.edge_id for edge in bundle.edges])
    flagged = np.flatnonzero([edge.is_river for edge in bundle.edges])
    assert np.array_equal(mesh.family_edge_indices("rivers"), flagged)


@pytest.mark.parametrize("case", BUNDLE_CASES)
def test_the_edges_are_the_edges_of_the_cell_mesh(case: str) -> None:
    cell_mesh = _cell_mesh(case)
    ours, reference = _from_cell_mesh(case), _from_bundle(case)
    geometry = cell_mesh.geometry

    assert np.array_equal(ours.edge_node_a, geometry.edge_nodes[:, 0])
    assert np.array_equal(ours.edge_node_b, geometry.edge_nodes[:, 1])
    assert np.array_equal(ours.edge_cell_a, geometry.edge_cells[:, 0])
    assert np.array_equal(ours.edge_cell_b, geometry.edge_cells[:, 1])
    assert np.array_equal(ours.edge_length_m, geometry.edge_length)
    assert ours.n_edges == reference.n_edges
    assert _node_pairs(ours, np.arange(ours.n_edges)) == _node_pairs(
        reference, np.arange(reference.n_edges)
    )


@pytest.mark.parametrize("case", BUNDLE_CASES)
@pytest.mark.parametrize("build", [_from_bundle, _from_cell_mesh])
def test_a_point_is_located_in_the_cell_that_holds_it(case: str, build) -> None:
    mesh = build(case)
    cells = np.random.default_rng(0).choice(mesh.n_cells, 25, replace=False)

    for cell in cells.tolist():
        x, y = float(mesh.cell_centroid_x_m[cell]), float(mesh.cell_centroid_y_m[cell])
        assert mesh.locate_cell_index_for_point(x, y) == cell


def test_a_point_outside_the_mesh_takes_the_nearest_centre_or_is_refused() -> None:
    mesh = _from_cell_mesh(BUNDLE_CASES[0])
    far_x, far_y = mesh.x_max_m + 1.0e3, float(np.mean(mesh.node_y_m))

    nearest = mesh.locate_cell_index_for_point(far_x, far_y)
    assert nearest == int(
        np.argmin((mesh.cell_centroid_x_m - far_x) ** 2 + (mesh.cell_centroid_y_m - far_y) ** 2)
    )
    with pytest.raises(ValueError, match="outside"):
        mesh.locate_cell_index_for_point(far_x, far_y, allow_nearest=False)


def test_a_bundle_mesh_keeps_the_cell_mesh_of_its_triangles() -> None:
    mesh = _from_bundle(BUNDLE_CASES[0])

    assert mesh.cell_mesh.n_cells == mesh.n_cells
    assert mesh.planar_mesh is mesh.cell_mesh.mesh
    assert mesh.cell_mesh.crs_wkt == _bundle(BUNDLE_CASES[0]).metadata_view.crs


def test_a_bundle_that_declares_no_crs_is_refused() -> None:
    bundle = _bundle(BUNDLE_CASES[0])
    metadata = {key: value for key, value in bundle.metadata.items() if key != "crs"}

    with pytest.raises(ValueError, match="no 'crs'"):
        BoussinesqMesh.from_bundle(replace(bundle, metadata=metadata))


def test_the_comparisons_are_not_vacuous() -> None:
    """An island has no river and no straight side; the other bundles must have both."""
    rivers = sum(_from_bundle(case).river_edge_indices().size > 0 for case in BUNDLE_CASES)
    sides = sum(
        _from_bundle(case).boundary_edge_indices_for_side(side).size > 0
        for case in BUNDLE_CASES
        for side in SIDE_IDS
    )

    assert rivers >= 1
    assert sides >= len(SIDE_IDS)


def test_the_adapter_locates_a_cell_as_the_flat_selector_of_the_one_layer_mesh() -> None:
    mesh = _from_cell_mesh(BUNDLE_CASES[1])
    ctx = SimpleNamespace(model=SimpleNamespace(mesh=mesh))
    cell = 7
    x, y = float(mesh.cell_centroid_x_m[cell]), float(mesh.cell_centroid_y_m[cell])

    assert BoussinesqFlowAdapter().locate_cell(ctx, x, y) == (0, 0, cell)


def test_the_adapter_has_no_cell_to_give_without_a_model() -> None:
    assert BoussinesqFlowAdapter().locate_cell(SimpleNamespace(model=None), 0.0, 0.0) is None


@pytest.mark.parametrize("build", [_from_bundle, _from_cell_mesh])
def test_a_support_label_resolves_on_the_families_of_the_mesh(build) -> None:
    mesh = build(BUNDLE_CASES[1])
    resolver = BoussinesqForcingResolver(mesh=mesh, flow=SimpleNamespace(), time_grid=None)

    label, edges, cells = resolver.resolve_labelled_support(
        boundary={"support_label": "west_side"}, bc_id="west_side"
    )

    assert label == "flow.bc.west_side [west_side]"
    assert np.array_equal(edges, mesh.boundary_edge_indices_for_side("west_side"))
    assert np.array_equal(cells, mesh.boundary_cell_indices_for_side("west_side"))


@pytest.mark.parametrize("build", [_from_bundle, _from_cell_mesh])
def test_the_stream_support_is_the_river_faces_and_the_cells_on_both_banks(build) -> None:
    mesh = build(BUNDLE_CASES[1])
    resolver = BoussinesqForcingResolver(mesh=mesh, flow=SimpleNamespace(), time_grid=None)

    label, edges, cells = resolver.resolve_stream_dirichlet_support(boundary={})

    assert label == "flow.bc.stream"
    assert np.array_equal(edges, mesh.river_edge_indices())
    assert np.array_equal(cells, stream_cells(mesh.cell_mesh))
