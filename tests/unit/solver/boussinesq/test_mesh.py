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

from hydromodpy.catchment.surface_sampling import PreparedSurfaceSampler
from hydromodpy.mesh.cells.boundary import SIDE_IDS, stream_cells
from hydromodpy.mesh.io.bundle import (
    CatchmentMeshBundle,
    cell_mesh_from_bundle,
    load_catchment_mesh_bundle,
)
from hydromodpy.mesh.planar.planar_cell_mesh import PlanarCellMesh
from hydromodpy.solver.boussinesq.adapter import BoussinesqFlowAdapter
from hydromodpy.solver.boussinesq.forcing import BoussinesqForcingResolver
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh
from tests._helpers.bundle_cell_meshes import BUNDLE_CASES, bundle_dual
from tests._helpers.cell_meshes import TEST_CRS_WKT
from tests._helpers.mesh_cases import MESH_BUNDLES
from tests._helpers.model_factory import make_model

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
@pytest.mark.parametrize("side", SIDE_IDS)
@pytest.mark.parametrize("build", [_from_bundle, _from_cell_mesh])
def test_side_edges_and_cells(case: str, side: str, build) -> None:
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
def test_cell_areas(case: str) -> None:
    ours, reference = _from_cell_mesh(case), _from_bundle(case)

    assert np.array_equal(ours.cell_area_m2, _cell_mesh(case).geometry.areas)
    np.testing.assert_allclose(ours.cell_area_m2, reference.cell_area_m2, rtol=1e-5)


def test_refuses_a_river_face_off_the_edge_list() -> None:
    mesh = _from_cell_mesh(BUNDLE_CASES[0])
    kept = np.setdiff1d(np.arange(mesh.n_edges), mesh.river_edge_indices())
    cut = replace(mesh, edge_node_a=mesh.edge_node_a[kept], edge_node_b=mesh.edge_node_b[kept])

    with pytest.raises(ValueError, match="not an edge of the mesh"):
        cut.family_edge_indices("rivers")


@pytest.mark.parametrize("case", BUNDLE_CASES)
@pytest.mark.parametrize("build", [_from_bundle, _from_cell_mesh])
def test_point_is_located_in_its_cell(case: str, build) -> None:
    mesh = build(case)
    cells = np.random.default_rng(0).choice(mesh.n_cells, 25, replace=False)

    for cell in cells.tolist():
        x, y = float(mesh.cell_centroid_x_m[cell]), float(mesh.cell_centroid_y_m[cell])
        assert mesh.locate_cell_index_for_point(x, y) == cell


def test_point_outside_the_mesh() -> None:
    mesh = _from_cell_mesh(BUNDLE_CASES[0])
    far_x, far_y = mesh.x_max_m + 1.0e3, float(np.mean(mesh.node_y_m))

    nearest = mesh.locate_cell_index_for_point(far_x, far_y)
    assert nearest == int(
        np.argmin((mesh.cell_centroid_x_m - far_x) ** 2 + (mesh.cell_centroid_y_m - far_y) ** 2)
    )
    with pytest.raises(ValueError, match="outside"):
        mesh.locate_cell_index_for_point(far_x, far_y, allow_nearest=False)


def test_bundle_mesh_keeps_its_cell_mesh() -> None:
    mesh = _from_bundle(BUNDLE_CASES[0])

    assert mesh.cell_mesh.n_cells == mesh.n_cells
    assert mesh.planar_mesh is mesh.cell_mesh.mesh
    assert mesh.cell_mesh.crs_wkt == _bundle(BUNDLE_CASES[0]).metadata_view.crs


def test_refuses_a_bundle_without_crs() -> None:
    bundle = _bundle(BUNDLE_CASES[0])
    metadata = {key: value for key, value in bundle.metadata.items() if key != "crs"}

    with pytest.raises(ValueError, match="no 'crs'"):
        BoussinesqMesh.from_bundle(replace(bundle, metadata=metadata))


def test_adapter_locates_a_cell() -> None:
    mesh = _from_cell_mesh(BUNDLE_CASES[1])
    run = SimpleNamespace(solver_model=SimpleNamespace(mesh=mesh))
    cell = 7
    x, y = float(mesh.cell_centroid_x_m[cell]), float(mesh.cell_centroid_y_m[cell])

    assert BoussinesqFlowAdapter().locate_cell(run, x, y) == (0, 0, cell)


def test_adapter_without_a_solver_model() -> None:
    assert BoussinesqFlowAdapter().locate_cell(SimpleNamespace(solver_model=None), 0.0, 0.0) is None


@pytest.mark.parametrize("build", [_from_bundle, _from_cell_mesh])
def test_support_label_resolves(build) -> None:
    mesh = build(BUNDLE_CASES[1])
    resolver = BoussinesqForcingResolver(mesh=mesh, inputs=make_model())

    label, edges, cells = resolver.resolve_labelled_support(
        boundary={"support_label": "west_side"}, bc_id="west_side"
    )

    assert label == "flow.bc.west_side [west_side]"
    assert np.array_equal(edges, mesh.boundary_edge_indices_for_side("west_side"))
    assert np.array_equal(cells, mesh.boundary_cell_indices_for_side("west_side"))


@pytest.mark.parametrize("build", [_from_bundle, _from_cell_mesh])
def test_stream_support(build) -> None:
    mesh = build(BUNDLE_CASES[1])
    resolver = BoussinesqForcingResolver(mesh=mesh, inputs=make_model())

    label, edges, cells = resolver.resolve_stream_dirichlet_support(boundary={})

    assert label == "flow.bc.stream"
    assert np.array_equal(edges, mesh.river_edge_indices())
    assert np.array_equal(cells, stream_cells(mesh.cell_mesh))


def _surface_with_a_dry_center(cell_mesh: PlanarCellMesh) -> SimpleNamespace:
    """A raster of TOP_M whose middle column has no data, centered on the first cell center.

    The first cell center falls in the empty column, so it reads no value, while its
    corners read the columns beside it.
    """
    center_x, center_y = (float(v) for v in cell_mesh.centers[0])
    width_m = 2.0**17
    support = SimpleNamespace(
        xmin=center_x - 1.5 * width_m,
        xmax=center_x + 1.5 * width_m,
        ymin=center_y - 0.5 * width_m,
        ymax=center_y + 0.5 * width_m,
        dx=width_m,
        dy=width_m,
        nrows=1,
        ncols=3,
        nodata=None,
    )
    return SimpleNamespace(values=np.asarray([[TOP_M, np.nan, TOP_M]]), support=support)


def test_cell_without_center_value_takes_its_corners() -> None:
    cell_mesh = _cell_mesh(BUNDLE_CASES[3])
    top = _surface_with_a_dry_center(cell_mesh)
    center_x, center_y = (float(v) for v in cell_mesh.centers[0])
    assert np.isnan(PreparedSurfaceSampler.from_surface(top).sample(center_x, center_y))
    domain = SimpleNamespace(surface_topo=top, substratum=_constant_surface(cell_mesh, BOTTOM_M))

    mesh = BoussinesqMesh.from_cell_mesh(
        cell_mesh,
        domain=domain,
        hydraulic_conductivity_m_s=np.full(cell_mesh.n_cells, K_M_S),
        storage_coefficient=np.full(cell_mesh.n_cells, SY),
    )

    # Every corner reads TOP_M, so the first cell takes the mean of its corners.
    np.testing.assert_allclose(mesh.z_top_m, TOP_M)


def _bundle_with_cell(**changes) -> CatchmentMeshBundle:
    bundle = _bundle(BUNDLE_CASES[3])
    return replace(bundle, cells=(replace(bundle.cells[0], **changes), *bundle.cells[1:]))


def _bundle_with_edge(**changes) -> CatchmentMeshBundle:
    bundle = _bundle(BUNDLE_CASES[3])
    return replace(bundle, edges=(replace(bundle.edges[0], **changes), *bundle.edges[1:]))


BUNDLE_REFUSALS = [
    pytest.param(replace(_bundle(BUNDLE_CASES[3]), cells=()), "at least one cell", id="no cell"),
    pytest.param(replace(_bundle(BUNDLE_CASES[3]), nodes=()), "at least one node", id="no node"),
    pytest.param(
        _bundle_with_cell(geom_type="quad"), "supports only triangular cells", id="quad cell"
    ),
    pytest.param(
        _bundle_with_cell(z_top_centroid=None),
        "requires z_top_centroid and z_bottom_centroid",
        id="cell without top",
    ),
    pytest.param(
        _bundle_with_cell(hydraulic_conductivity_m_s=None),
        "requires hydraulic_conductivity_m_s",
        id="cell without K",
    ),
    pytest.param(
        _bundle_with_cell(storage_coefficient=None),
        "requires storage_coefficient",
        id="cell without storage",
    ),
    pytest.param(
        _bundle_with_cell(z_top_centroid=-1.0),
        "z_top_centroid must be >= z_bottom_centroid",
        id="top below bottom",
    ),
    pytest.param(
        _bundle_with_cell(node_indices=(0, 1, 10**6)),
        "Unknown node_id=1000000 referenced by cell_id",
        id="cell on an unknown node",
    ),
    pytest.param(
        _bundle_with_edge(node_a=10**6), "Unknown node reference on edge_id", id="edge node"
    ),
    pytest.param(_bundle_with_edge(cell_a=10**6), "Unknown cell_a=1000000", id="edge cell a"),
    pytest.param(_bundle_with_edge(cell_b=10**6), "Unknown cell_b=1000000", id="edge cell b"),
]


@pytest.mark.parametrize(("bundle", "message"), BUNDLE_REFUSALS)
def test_bundle_refusals(bundle: CatchmentMeshBundle, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        BoussinesqMesh.from_bundle(bundle)


def _surface_without_data(cell_mesh: PlanarCellMesh) -> SimpleNamespace:
    """A raster of TOP_M that lies 1 km east of the mesh: every cell reads no value."""
    surface = _constant_surface(cell_mesh, TOP_M)
    far = replace_support(surface.support, shift_m=1.0e3 + cell_mesh.mesh.bounds()[2])
    return SimpleNamespace(values=surface.values, support=far)


def replace_support(support: SimpleNamespace, *, shift_m: float) -> SimpleNamespace:
    return SimpleNamespace(
        **{**vars(support), "xmin": support.xmin + shift_m, "xmax": support.xmax + shift_m}
    )


def _runtime_domain(cell_mesh: PlanarCellMesh, **surfaces) -> SimpleNamespace:
    """The domain of the 10 m column, a surface being replaced by what ``surfaces`` gives."""
    return SimpleNamespace(
        **{
            "surface_topo": _constant_surface(cell_mesh, TOP_M),
            "substratum": _constant_surface(cell_mesh, BOTTOM_M),
            **surfaces,
        }
    )


_TRIANGLES = _cell_mesh(BUNDLE_CASES[3])
CELL_MESH_REFUSALS = [
    pytest.param(_TRIANGLES, None, "requires a domain", id="no domain"),
    pytest.param(
        _TRIANGLES,
        SimpleNamespace(substratum=_constant_surface(_TRIANGLES, BOTTOM_M)),
        "surface_topo is required",
        id="no land surface",
    ),
    pytest.param(
        _TRIANGLES,
        SimpleNamespace(surface_topo=_constant_surface(_TRIANGLES, TOP_M)),
        "substratum is required",
        id="no substratum",
    ),
    pytest.param(
        bundle_dual(BUNDLE_CASES[3]),
        _runtime_domain(_TRIANGLES),
        "supports only triangular cells",
        id="polygon cells",
    ),
    pytest.param(
        _TRIANGLES,
        _runtime_domain(_TRIANGLES, surface_topo=_surface_without_data(_TRIANGLES)),
        "missing values on cell_id=0",
        id="land surface off the mesh",
    ),
    pytest.param(
        _TRIANGLES,
        _runtime_domain(_TRIANGLES, substratum=_constant_surface(_TRIANGLES, 2 * TOP_M)),
        "Invalid vertical geometry on cell_id=0",
        id="substratum above the land surface",
    ),
]


@pytest.mark.parametrize(("cell_mesh", "domain", "message"), CELL_MESH_REFUSALS)
def test_cell_mesh_refusals(cell_mesh: PlanarCellMesh, domain, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        BoussinesqMesh.from_cell_mesh(
            cell_mesh,
            domain=domain,
            hydraulic_conductivity_m_s=np.full(cell_mesh.n_cells, K_M_S),
            storage_coefficient=np.full(cell_mesh.n_cells, SY),
        )


def test_refuses_cell_values_of_the_wrong_size() -> None:
    cell_mesh = _TRIANGLES

    with pytest.raises(ValueError, match="exactly one value per cell"):
        BoussinesqMesh.from_cell_mesh(
            cell_mesh,
            domain=_runtime_domain(cell_mesh),
            hydraulic_conductivity_m_s=np.full(cell_mesh.n_cells - 1, K_M_S),
            storage_coefficient=np.full(cell_mesh.n_cells, SY),
        )
