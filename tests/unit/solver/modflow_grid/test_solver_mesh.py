"""Contract tests for SolverMesh, the central solver-facing grid object.

The whole solver pipeline depends on SolverMesh, so its public contract is owned
here: geometry helpers (areas, centroids, thicknesses, idomain), the
structured/unstructured split (reshape vs the structured-only raising members),
the DIS/DISV exports with the flopy DISV arguments of a planar HydroMesh
(``to_flopy_disv_args``), and the __post_init__ prismatic invariant.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest
from pydantic import ValidationError
from shapely.geometry import box

from hydromodpy.core.exceptions import MeshError
from hydromodpy.solver.modflow6.modflow6_config import Modflow6Config
from hydromodpy.solver.modflow_grid import build_spatial_discretization
from hydromodpy.solver.modflow_grid.sgrid_config import SolverSGridConfig
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh, to_flopy_disv_args
from hydromodpy.spatial import RasterSupport, Surface
from hydromodpy.spatial.domain.domain import Domain
from hydromodpy.spatial.domain.domain_config import DomainConfig
from hydromodpy.spatial.domain.layers_config import VerticalGridConfig
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh
from tests._helpers.mesh_cases import regular_mesh, voronoi_lake_mesh
from tests._helpers.regular_cell_meshes import regular_cell_mesh
from tests._helpers.solver_meshes import solver_mesh_from, solver_mesh_from_structured_arrays


def _unstructured_two_quads() -> SolverMesh:
    """Two side-by-side quads as an UNSTRUCTURED mesh (structured_shape=None)."""
    verts = np.array(
        [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [2.0, 0.0], [2.0, 1.0]], dtype=float
    )
    conn = np.array([[0, 1, 2, 3], [1, 4, 5, 2]], dtype=int)
    mesh = HydroMesh(
        vertices=verts,
        cell_blocks=(CellBlock(CellType.QUADRILATERAL, conn),),
        structured_shape=None,
    )
    return solver_mesh_from(
        mesh,
        top=np.full(2, 10.0),
        botm=np.zeros((1, 2)),
        inactive_mask=np.zeros((1, 2), dtype=bool),
    )


def test_cell_areas_shoelace_is_winding_invariant() -> None:
    # A unit square and a 2x1 rectangle, regardless of node winding.
    sm = _unstructured_two_quads()
    areas = sm.cell_areas()
    assert areas[0] == pytest.approx(1.0)
    assert areas[1] == pytest.approx(1.0)
    # characteristic_length = sqrt(mean area) = 1.0 here.
    assert sm.characteristic_length == pytest.approx(1.0)


def test_cell_centers_are_vertex_means() -> None:
    sm = _unstructured_two_quads()
    centroids = sm.cell_centers()
    assert centroids[0] == pytest.approx([0.5, 0.5])
    assert centroids[1] == pytest.approx([1.5, 0.5])


def test_layer_thicknesses_and_center_depths() -> None:
    sm = solver_mesh_from_structured_arrays(
        nrow=1,
        ncol=2,
        top=np.array([[10.0, 10.0]]),
        botm=np.array([[[6.0, 6.0]], [[0.0, 0.0]]]),  # (nlay=2, 1, 2)
    )
    thick = sm.layer_thicknesses()
    assert thick.shape == (2, 2)
    assert thick[0] == pytest.approx([4.0, 4.0])  # 10 -> 6
    assert thick[1] == pytest.approx([6.0, 6.0])  # 6 -> 0
    depths = sm.layer_center_depths()
    assert depths[0] == pytest.approx([2.0, 2.0])  # top(10) - center(8)
    assert depths[1] == pytest.approx([7.0, 7.0])  # top(10) - center(3)


def test_idomain_from_inactive_mask() -> None:
    mask = np.array([[False, True]])
    sm = solver_mesh_from_structured_arrays(
        nrow=1, ncol=2, top=np.zeros((1, 2)), botm=-np.ones((1, 1, 2)), inactive_mask=mask
    )
    assert sm.idomain.tolist() == [[1, 0]]


def test_structured_arrays_put_row_0_at_the_north_like_modflow() -> None:
    sm = solver_mesh_from_structured_arrays(
        nrow=3,
        ncol=2,
        top=np.zeros((3, 2)),
        botm=-np.ones((1, 3, 2)),
        dx=10.0,
        dy=5.0,
        xoff=100.0,
        yoff=200.0,
    )
    centroids = sm.cell_centers().reshape(3, 2, 2)
    assert centroids[:, 0, 1] == pytest.approx([212.5, 207.5, 202.5])
    assert centroids[0, :, 0] == pytest.approx([105.0, 115.0])
    assert sm.yoffset == pytest.approx(200.0)
    assert sm.yvertices[:, 0] == pytest.approx([215.0, 210.0, 205.0, 200.0])


def test_reshape_round_trip_on_non_square_structured_grid() -> None:
    sm = solver_mesh_from_structured_arrays(
        nrow=2, ncol=3, top=np.zeros((2, 3)), botm=np.zeros((1, 2, 3))
    )
    flat = np.arange(6, dtype=float)
    grid = sm.reshape_to_grid(flat)
    assert grid.shape == (2, 3)
    assert np.array_equal(sm.flatten_from_grid(grid), flat)


def test_structured_delr_delc_on_non_uniform_grid() -> None:
    sm = solver_mesh_from_structured_arrays(
        nrow=2, ncol=2, top=np.zeros((2, 2)), botm=np.zeros((1, 2, 2)), dx=5.0, dy=7.0
    )
    delr, delc = sm.structured_delr_delc()
    assert delr.tolist() == pytest.approx([5.0, 5.0])
    assert delc.tolist() == pytest.approx([7.0, 7.0])
    assert sm.nrow == 2 and sm.ncol == 2


def test_structured_only_members_raise_on_unstructured() -> None:
    sm = _unstructured_two_quads()
    assert sm.is_structured is False
    assert sm.structured_shape is None
    for accessor in (
        lambda: sm.nrow,
        lambda: sm.ncol,
        lambda: sm.delr,
        lambda: sm.delc,
        lambda: sm.xvertices,
        lambda: sm.yvertices,
        lambda: sm.structured_delr_delc(),
        lambda: sm.to_dis_kwargs(),
    ):
        with pytest.raises(ValueError):
            accessor()


def test_reshape_is_identity_on_unstructured() -> None:
    sm = _unstructured_two_quads()
    flat = np.array([1.0, 2.0])
    assert np.array_equal(sm.reshape_to_grid(flat), flat)
    assert np.array_equal(sm.flatten_from_grid(flat), flat)


def test_to_disv_kwargs_has_the_expected_keys() -> None:
    sm = solver_mesh_from_structured_arrays(
        nrow=2, ncol=2, top=np.zeros((2, 2)), botm=np.zeros((1, 2, 2))
    )
    kw = sm.to_disv_kwargs()
    for key in ("nvert", "ncpl", "vertices", "cell2d", "top", "botm"):
        assert key in kw
    assert kw["ncpl"] == 4


def test_post_init_rejects_wrong_top_size() -> None:
    cell_mesh = _unstructured_two_quads().cell_mesh
    with pytest.raises(ValueError, match="top must have"):
        SolverMesh(
            cell_mesh=cell_mesh,
            top=np.zeros(3),
            botm=np.zeros((1, 2)),
            idomain=np.ones((1, 2), int),
        )


def test_post_init_rejects_mask_shape_mismatch() -> None:
    cell_mesh = _unstructured_two_quads().cell_mesh
    with pytest.raises(ValueError, match="idomain"):
        SolverMesh(
            cell_mesh=cell_mesh,
            top=np.zeros(2),
            botm=np.zeros((2, 2)),
            idomain=np.ones((1, 2), int),  # nlay mismatch vs botm
        )


def test_centres_and_areas_are_those_of_the_cell_mesh() -> None:
    sm = _unstructured_two_quads()
    assert np.array_equal(sm.cell_centers(), sm.cell_mesh.centers)
    assert np.array_equal(sm.cell_areas(), sm.cell_mesh.geometry.areas)
    assert sm.planar_mesh is sm.cell_mesh.mesh


def test_centres_and_areas_are_copies() -> None:
    sm = _unstructured_two_quads()
    sm.cell_centers()[:] = -1.0
    sm.cell_areas()[:] = -1.0
    assert np.all(sm.cell_mesh.centers >= 0.0)
    assert np.all(sm.cell_mesh.geometry.areas > 0.0)


def test_face_adjacency_is_the_shared_face_graph_and_may_be_modified() -> None:
    sm = _unstructured_two_quads()
    adjacency = sm.face_adjacency()
    assert adjacency == [{1}, {0}]
    adjacency[0].add(7)
    assert sm.face_adjacency() == [{1}, {0}]


def test_face_adjacency_of_a_grid_has_no_diagonal() -> None:
    sm = solver_mesh_from_structured_arrays(
        nrow=3, ncol=3, top=np.zeros((3, 3)), botm=-np.ones((1, 3, 3))
    )
    adjacency = sm.face_adjacency()
    assert adjacency[4] == {1, 3, 5, 7}
    assert adjacency[0] == {1, 3}


def test_layer_center_depths_are_never_negative() -> None:
    # A cell whose bottom lies above its top (a nodata-like inversion) has no depth below zero.
    sm = solver_mesh_from_structured_arrays(
        nrow=1,
        ncol=2,
        top=np.array([[10.0, 10.0]]),
        botm=np.array([[[6.0, 12.0]], [[0.0, 14.0]]]),
    )
    assert (sm.layer_center_depths() >= 0.0).all()
    assert sm.layer_center_depths()[0, 0] == pytest.approx(2.0)


def test_a_grid_from_arrays_is_a_regular_cell_mesh_in_a_local_frame() -> None:
    sm = solver_mesh_from_structured_arrays(
        nrow=2, ncol=3, top=np.zeros((2, 3)), botm=-np.ones((1, 2, 3)), dx=10.0, dy=5.0
    )
    assert sm.cell_mesh.structured_shape == (2, 3)
    assert sm.cell_mesh.center_kind == "cell_center"
    assert sm.cell_mesh.crs_wkt
    assert sm.cell_areas() == pytest.approx(np.full(6, 50.0))


def test_a_counterclockwise_triangle_is_written_clockwise() -> None:
    verts = np.array([[0, 0], [1, 0], [0.5, 1]], dtype=float)
    mesh = HydroMesh(
        vertices=verts,
        cell_blocks=(CellBlock(CellType.TRIANGLE, np.array([[0, 1, 2]])),),
    )
    result = to_flopy_disv_args(mesh, top=10.0, botm=np.array([[5.0]]))
    assert result["nvert"] == 3
    assert result["ncpl"] == 1
    assert len(result["cell2d"]) == 1
    assert len(result["vertices"]) == 3
    assert result["cell2d"][0][4:] == [0, 2, 1]


def test_a_clockwise_grid_keeps_its_rings_and_its_cell_centres() -> None:
    cell_mesh = regular_mesh(2, 3, dx=10.0)

    result = to_flopy_disv_args(cell_mesh.mesh, top=10.0, botm=np.zeros((1, 6)))

    for row, nodes, centre in zip(
        result["cell2d"], cell_mesh.mesh.flat_connectivity, cell_mesh.centers, strict=True
    ):
        assert row[3] == 4
        assert row[4:] == nodes.tolist()
        assert row[1:3] == pytest.approx(centre.tolist())


def test_the_seeds_of_a_voronoi_mesh_are_its_disv_centres() -> None:
    verts = np.array([[1, 0], [1, 1], [0, 1], [-0.3, 0.5], [0, 0], [2, 0], [2, 1]], dtype=float)
    seeds = np.array([[0.3, 0.5], [1.5, 0.5]])
    mesh = HydroMesh(
        vertices=verts,
        cell_blocks=(
            CellBlock(CellType.POLYGON, (np.array([0, 1, 2, 3, 4]), np.array([0, 5, 6, 1]))),
        ),
    )
    solver = solver_mesh_from(
        mesh, np.full(2, 10.0), np.zeros((1, 2)), np.zeros((1, 2), bool), centers=seeds
    )

    result = to_flopy_disv_args(mesh, top=10.0, botm=np.zeros((1, 2)), centers=seeds)

    assert [row[1:3] for row in result["cell2d"]] == seeds.tolist()
    assert [row[3] for row in result["cell2d"]] == [5, 4]
    assert solver.to_disv_kwargs()["cell2d"] == result["cell2d"]
    np.testing.assert_array_equal(solver.generator_centers, seeds)


def test_a_voronoi_engine_mesh_writes_its_generators_as_the_disv_centres() -> None:
    lake = box(40.0, 40.0, 70.0, 65.0)
    cell_mesh = voronoi_lake_mesh(
        lake, domain=box(0.0, 0.0, 120.0, 100.0), pixel=5.0, cell_size=9.0
    )
    n = cell_mesh.n_cells
    solver = SolverMesh(
        cell_mesh=cell_mesh,
        top=np.zeros(n),
        botm=np.full((1, n), -1.0),
        idomain=np.ones((1, n), dtype=int),
    )

    cell2d = solver.to_disv_kwargs()["cell2d"]

    assert cell_mesh.center_kind == "generator"
    np.testing.assert_array_equal([row[1:3] for row in cell2d], cell_mesh.centers)
    assert not np.allclose(cell_mesh.centers, np.column_stack(cell_mesh.mesh.cell_centroids()))


def test_a_mesh_not_centred_on_generators_writes_the_vertex_means() -> None:
    verts = np.array([[0, 0], [1, 0], [0, 1], [1, 1]], dtype=float)
    planar = HydroMesh(
        vertices=verts, cell_blocks=(CellBlock(CellType.TRIANGLE, [[0, 1, 2], [1, 3, 2]]),)
    )
    solver = solver_mesh_from(planar, np.full(2, 10.0), np.zeros((1, 2)), np.zeros((1, 2), bool))
    by_hand = to_flopy_disv_args(planar, top=10.0, botm=np.zeros((1, 2)))

    assert solver.generator_centers is None
    assert solver.to_disv_kwargs()["cell2d"] == by_hand["cell2d"]
    assert by_hand["cell2d"][1][1:3] == pytest.approx([2.0 / 3.0, 2.0 / 3.0])


def test_a_3d_mesh_has_no_disv() -> None:
    verts = np.array(
        [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 1]], dtype=float
    )
    mesh = HydroMesh(
        vertices=verts,
        cell_blocks=(CellBlock(CellType.WEDGE, np.array([[0, 1, 2, 3, 4, 5]])),),
    )
    with pytest.raises(ValueError, match="2D mesh"):
        to_flopy_disv_args(mesh, top=10.0, botm=np.array([[5.0]]))


# The solver mesh holds MODFLOW's ``idomain`` and answers the top active cell from it.

TOP = np.array([10.0, 11.0, 12.0])


BOTM = np.array([[6.0, 7.0, 8.0], [0.0, 1.0, 2.0]])


def _mesh(idomain: np.ndarray) -> SolverMesh:
    base = solver_mesh_from_structured_arrays(nrow=1, ncol=3, top=TOP, botm=BOTM)
    return SolverMesh(cell_mesh=base.cell_mesh, top=base.top, botm=base.botm, idomain=idomain)


def test_the_idomain_keeps_its_three_values_and_cannot_be_written() -> None:
    mesh = _mesh(np.array([[1, 0, 1], [1, 1, -1]]))
    assert mesh.idomain.tolist() == [[1, 0, 1], [1, 1, -1]]
    with pytest.raises(ValueError):
        mesh.idomain[0, 0] = 0


def test_a_value_other_than_minus_one_zero_and_one_is_refused() -> None:
    with pytest.raises(ValueError, match="only -1, 0 and 1"):
        _mesh(np.array([[1, 2, 1], [1, 1, 1]]))


def test_a_pass_through_cell_is_not_active() -> None:
    mesh = _mesh(np.array([[1, 0, 1], [1, 1, -1]]))
    assert mesh.inactive_mask.tolist() == [[False, True, False], [False, False, True]]


def test_the_top_active_cell_and_its_top_follow_the_idomain() -> None:
    mesh = _mesh(np.array([[1, 0, 0], [1, 1, 0]]))
    assert mesh.top_active_layer().tolist() == [0, 1, -1]
    tops = mesh.top_active_cell_top()
    assert tops[:2].tolist() == [10.0, 7.0]
    assert np.isnan(tops[2])


def test_a_closed_column_has_no_active_cell_or_is_covered() -> None:
    mesh = _mesh(np.array([[1, 0, 0], [1, 1, 0]]))
    assert mesh.closed_surface().tolist() == [False, False, True]
    assert mesh.closed_surface([1]).tolist() == [False, True, True]


def test_the_interfaces_are_checked_on_demand() -> None:
    mesh = _mesh(np.ones((2, 3), dtype=int))
    mesh.check_interfaces()
    flat = SolverMesh(
        cell_mesh=mesh.cell_mesh, top=mesh.top, botm=np.vstack([TOP, BOTM[1]]), idomain=mesh.idomain
    )
    with pytest.raises(ValueError, match="layer 0 cell 0"):
        flat.check_interfaces()


# A regular mesh is extruded on the surfaces only if both describe one grid.
#
# The planar grid is the mesh's, the vertical part is the surfaces'. A mesh shifted
# by a meter, a step off by a part in a million, or a mesh that forgets its shape
# would move every cell against its elevation without a single array mismatch, so
# the builder refuses them.

_N = 6


_STEP = 40.0


_XMIN = 1_000.0


_YMIN = 2_000.0


def _surface(name: str, value: float) -> Surface:
    support = RasterSupport(
        crs="EPSG:2154",
        dx=_STEP,
        dy=_STEP,
        xmin=_XMIN,
        xmax=_XMIN + _STEP * _N,
        ymin=_YMIN,
        ymax=_YMIN + _STEP * _N,
        nrows=_N,
        ncols=_N,
        nodata=-9999.0,
    )
    return Surface(name=name, values=np.full((_N, _N), value), support=support)


def _domain() -> Domain:
    domain = Domain(config=DomainConfig(), surface_topo=_surface("surface_topo", 20.0))
    domain.substratum = _surface("substratum", 0.0)
    return domain


def _extrude(cell_mesh: PlanarCellMesh):
    return build_spatial_discretization(
        domain=_domain(),
        vertical_config=VerticalGridConfig(nlay=1, nodata=-9999.0),
        sgrid_config=SolverSGridConfig(),
        cell_mesh=cell_mesh,
    )


def _mesh_2(**changes: float) -> PlanarCellMesh:
    arguments = {"xmin": _XMIN, "ymin": _YMIN, "dx": _STEP, "dy": _STEP, "nrow": _N, "ncol": _N}
    return regular_cell_mesh(**{**arguments, **changes})


def test_a_mesh_on_the_grid_of_the_surfaces_is_extruded() -> None:
    ctx = _extrude(_mesh_2())

    assert ctx.solver_mesh.structured_shape == (_N, _N)


@pytest.mark.parametrize(
    "changes",
    [
        {"xmin": _XMIN + 1.0},
        {"ymin": _YMIN - 1.0},
        {"dx": _STEP * (1.0 + 1e-6)},
        {"dy": _STEP * (1.0 - 1e-6)},
    ],
    ids=["shifted_east", "shifted_south", "wider_cells", "shorter_cells"],
)
def test_a_mesh_off_the_grid_of_the_surfaces_is_refused(changes: dict[str, float]) -> None:
    with pytest.raises(MeshError, match="differ"):
        _extrude(_mesh_2(**changes))


def test_a_mesh_that_forgets_its_shape_on_the_hydro_mesh_is_refused() -> None:
    cell_mesh = _mesh_2()
    forgetful = replace(cell_mesh, mesh=replace(cell_mesh.mesh, structured_shape=None))

    with pytest.raises(MeshError, match="shape"):
        _extrude(forgetful)


def test_a_mesh_of_another_shape_resamples_the_surfaces_on_its_own_grid() -> None:
    ctx = _extrude(_mesh_2(dx=_STEP * 2, dy=_STEP * 3, nrow=_N // 3, ncol=_N // 2))

    assert ctx.solver_mesh.structured_shape == (_N // 3, _N // 2)
    assert ctx.top_surface.as_array().shape == (_N // 3, _N // 2)
    assert np.allclose(ctx.solver_mesh.top, 20.0)


# The ``sgrid`` table of a MODFLOW backend only says how the top is sampled from the DEM.


@pytest.mark.parametrize(
    ("model", "payload", "match"),
    [
        (SolverSGridConfig, {"planar": {"nlay": 2}}, r"sgrid\.planar is replaced by \[mesh\]: write cell_size"),
        (SolverSGridConfig, {"grid_dual": {"nlay": 2}}, r"sgrid\.grid_dual is replaced by \[mesh\] engine"),
        (SolverSGridConfig, {"vertical": {"nlay": 2}}, r"sgrid\.vertical is replaced by \[domain\.layers\]"),
        (SolverSGridConfig, "zonal", "Input should be a valid dictionary"),
        (Modflow6Config, {"sgrid": {"vertical": {"nlay": 2}}}, r"hmp doctor --fix-config"),
    ],
    ids=["planar", "grid_dual", "vertical", "not_a_table", "modflow6_vertical_names_the_doctor_fix"],
)  # fmt: skip
def test_a_retired_sgrid_key_is_refused_naming_the_table_that_replaces_it(model, payload, match):
    with pytest.raises(ValidationError, match=match):
        model.model_validate(payload)


@pytest.mark.parametrize(
    "payload",
    [{"sgrid": {"top_sampling": {"mode": "zonal", "hillslope_stat": "p25"}}}, {"top_sampling": {"mode": "zonal", "hillslope_stat": "p25"}}],
    ids=["backend-table", "bare-sgrid-table"],
)  # fmt: skip
def test_from_mapping_reads_the_sgrid_table_of_a_backend_or_the_table_itself(payload):
    config = SolverSGridConfig.from_mapping(payload)

    assert (config.top_sampling.mode, config.top_sampling.hillslope_stat) == ("zonal", "p25")
    assert SolverSGridConfig.from_mapping({}) == SolverSGridConfig()
