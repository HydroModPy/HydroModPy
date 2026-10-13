"""A Boussinesq mesh built from a cell mesh reads its river, sides and cells from the families.

The four committed mesh bundles are the oracle, with a river flagged along their
middle. The mesh read from the bundle finds its river edges in the ``is_river``
flags and its sides in the bounding box of the edge midpoints; the mesh built from the same bundle as a
cell mesh must find the same edges and the same cells in the face families.
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
from hydromodpy.spatial.mesh.adapters.cell_mesh import cell_mesh_from_triangulation
from hydromodpy.spatial.mesh.gmsh_grid.catchment_mesh_bundle_reader import (
    CatchmentMeshBundle,
    load_catchment_mesh_bundle,
)
from hydromodpy.spatial.mesh.gmsh_grid.exchange_api import load_planar_mesh
from hydromodpy.spatial.mesh.gmsh_grid.runtime_support import build_gmsh_support_metadata
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh
from hydromodpy.spatial.mesh.ops.family_cells import SIDE_IDS
from tests._helpers.bundle_cell_meshes import BUNDLE_CASES, BUNDLES
from tests._helpers.cell_meshes import TEST_CRS_WKT

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
    bundle = load_catchment_mesh_bundle(BUNDLES / case)
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
    """The triangles of the bundle as a cell mesh, with the families of its support."""
    triangles = load_planar_mesh(BUNDLES / case / "mesh_2d.msh").to_hydro_mesh()
    support = build_gmsh_support_metadata(_bundle(case))
    return cell_mesh_from_triangulation(triangles, support, crs_wkt=TEST_CRS_WKT)


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


def _from_bundle(case: str) -> BoussinesqMesh:
    return BoussinesqMesh.from_bundle(_bundle(case))


def _node_pairs(mesh: BoussinesqMesh, edges: np.ndarray) -> set[tuple[int, int]]:
    """The edges as pairs of node positions, whatever the order of the edge table."""
    node_a = [mesh.node_index_by_id[int(i)] for i in mesh.edge_node_a[edges]]
    node_b = [mesh.node_index_by_id[int(i)] for i in mesh.edge_node_b[edges]]
    return {(min(a, b), max(a, b)) for a, b in zip(node_a, node_b, strict=True)}


@pytest.mark.parametrize("case", BUNDLE_CASES)
def test_the_river_edges_are_those_the_bundle_files_flag(case: str) -> None:
    ours, reference = _from_cell_mesh(case), _from_bundle(case)

    flagged = _node_pairs(reference, reference.river_edge_indices())
    assert _node_pairs(ours, ours.river_edge_indices()) == flagged
    assert np.array_equal(
        np.unique(ours.cell_indices_for_label("stream")),
        np.unique(
            np.concatenate(
                [
                    reference.edge_cell_a[reference.river_edge_indices()],
                    reference.edge_cell_b[reference.river_edge_indices()][
                        reference.edge_cell_b[reference.river_edge_indices()] >= 0
                    ],
                ]
            )
        ),
    )


@pytest.mark.parametrize("case", BUNDLE_CASES)
@pytest.mark.parametrize("side", SIDE_IDS)
def test_the_side_edges_and_cells_are_those_of_the_bounding_box_rule(case: str, side: str) -> None:
    ours, reference = _from_cell_mesh(case), _from_bundle(case)

    edges = reference.boundary_edge_indices_for_side(side)
    assert _node_pairs(ours, ours.boundary_edge_indices_for_side(side)) == _node_pairs(
        reference, edges
    )
    assert np.array_equal(
        ours.boundary_cell_indices_for_side(side), reference.boundary_cell_indices_for_side(side)
    )
    assert np.array_equal(
        ours.cell_indices_for_label(side), ours.boundary_cell_indices_for_side(side)
    )
    assert np.array_equal(
        ours.edge_indices_for_label(side), ours.boundary_edge_indices_for_side(side)
    )


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
def test_a_point_is_located_in_the_cell_that_holds_it(case: str) -> None:
    ours, reference = _from_cell_mesh(case), _from_bundle(case)
    cells = np.random.default_rng(0).choice(ours.n_cells, 25, replace=False)

    for cell in cells.tolist():
        x, y = float(ours.cell_centroid_x_m[cell]), float(ours.cell_centroid_y_m[cell])
        assert ours.locate_cell_index_for_point(x, y) == cell
        assert ours.locate_cell_index_for_point(x, y) == reference.locate_cell_index_for_point(x, y)


def test_a_point_outside_the_mesh_takes_the_nearest_centre_or_is_refused() -> None:
    mesh = _from_cell_mesh(BUNDLE_CASES[0])
    far_x, far_y = mesh.x_max_m + 1.0e3, float(np.mean(mesh.node_y_m))

    nearest = mesh.locate_cell_index_for_point(far_x, far_y)
    assert nearest == int(
        np.argmin((mesh.cell_centroid_x_m - far_x) ** 2 + (mesh.cell_centroid_y_m - far_y) ** 2)
    )
    with pytest.raises(ValueError, match="outside"):
        mesh.locate_cell_index_for_point(far_x, far_y, allow_nearest=False)


def test_a_mesh_read_from_a_bundle_has_no_families_to_answer_a_label() -> None:
    reference = _from_bundle(BUNDLE_CASES[0])

    assert reference.cell_mesh is None
    assert reference.planar_mesh is None
    with pytest.raises(ValueError, match="face families"):
        reference.cell_indices_for_label("west_side")


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


def test_the_adapter_has_no_cell_to_give_on_a_mesh_read_from_a_bundle() -> None:
    ctx = SimpleNamespace(model=SimpleNamespace(mesh=_from_bundle(BUNDLE_CASES[1])))

    assert BoussinesqFlowAdapter().locate_cell(ctx, 0.0, 0.0) is None
    assert BoussinesqFlowAdapter().locate_cell(SimpleNamespace(model=None), 0.0, 0.0) is None


def test_a_support_label_resolves_on_the_families_of_a_mesh_built_from_a_cell_mesh() -> None:
    mesh = _from_cell_mesh(BUNDLE_CASES[1])
    resolver = BoussinesqForcingResolver(mesh=mesh, flow=SimpleNamespace(), time_grid=None)

    label, edges, cells = resolver.resolve_labelled_support(
        boundary={"support_label": "west_side"}, bc_id="west_side"
    )

    assert label == "flow.bc.west_side [west_side]"
    assert np.array_equal(edges, mesh.boundary_edge_indices_for_side("west_side"))
    assert np.array_equal(cells, mesh.boundary_cell_indices_for_side("west_side"))


def test_a_support_label_is_refused_where_no_family_and_no_support_exist() -> None:
    mesh = _from_bundle(BUNDLE_CASES[1])
    resolver = BoussinesqForcingResolver(mesh=mesh, flow=SimpleNamespace(), time_grid=None)

    with pytest.raises(ValueError, match="mesh support is unavailable"):
        resolver.resolve_labelled_support(boundary={"support_label": "stream"}, bc_id="stream")
