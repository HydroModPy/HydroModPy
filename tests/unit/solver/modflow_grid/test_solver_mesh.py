"""SolverMesh, the grid object every solver reads: prisms of 2D cells between elevations (m).

Geometry helpers (areas in m2, centers, thicknesses), the structured and unstructured split,
the DIS export of NWT and the DISV export of MODFLOW 6 (to_flopy_disv_args), and the
idomain (-1 pass-through, 0 inactive, 1 active) that gives the top active cell.
"""

from __future__ import annotations

import flopy
import numpy as np
import pytest
from shapely.geometry import box

from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh, to_flopy_disv_args
from tests._helpers.mesh_cases import regular_mesh, voronoi_lake_mesh
from tests._helpers.solver_meshes import solver_mesh_from, solver_mesh_from_structured_arrays


def two_quads() -> SolverMesh:
    """Two unit squares side by side, as an unstructured mesh."""
    vertices = np.array([[0, 0], [1, 0], [1, 1], [0, 1], [2, 0], [2, 1]], dtype=float)
    connectivity = np.array([[0, 1, 2, 3], [1, 4, 5, 2]])
    mesh = HydroMesh(
        vertices=vertices,
        cell_blocks=(CellBlock(CellType.QUADRILATERAL, connectivity),),
        structured_shape=None,
    )
    return solver_mesh_from(
        mesh,
        top=np.full(2, 10.0),
        botm=np.zeros((1, 2)),
        inactive_mask=np.zeros((1, 2), dtype=bool),
    )


def three_cells(
    top=np.array([10.0, 11.0, 12.0]), botm=np.array([[6.0, 7.0, 8.0], [0.0, 1.0, 2.0]])
):
    return solver_mesh_from_structured_arrays(nrow=1, ncol=3, top=top, botm=botm)


def test_cell_areas_and_characteristic_length():
    mesh = two_quads()

    np.testing.assert_allclose(mesh.cell_areas(), [1.0, 1.0])
    # characteristic_length = sqrt(mean area)
    assert mesh.characteristic_length == pytest.approx(1.0)


def test_cell_centers_are_vertex_means():
    centers = two_quads().cell_centers()

    assert centers[0] == pytest.approx([0.5, 0.5])
    assert centers[1] == pytest.approx([1.5, 0.5])


def test_layer_thicknesses_and_center_depths():
    mesh = solver_mesh_from_structured_arrays(
        nrow=1,
        ncol=2,
        top=np.array([[10.0, 10.0]]),
        botm=np.array([[[6.0, 6.0]], [[0.0, 0.0]]]),  # nlay = 2
    )

    thickness = mesh.layer_thicknesses()
    depths = mesh.layer_center_depths()

    assert thickness.shape == (2, 2)
    assert thickness[0] == pytest.approx([4.0, 4.0])  # 10 -> 6
    assert thickness[1] == pytest.approx([6.0, 6.0])  # 6 -> 0
    assert depths[0] == pytest.approx([2.0, 2.0])  # top 10 - center 8
    assert depths[1] == pytest.approx([7.0, 7.0])  # top 10 - center 3


def test_center_depths_are_never_negative():
    # A cell whose bottom lies above its top (a nodata-like inversion) has no depth below zero.
    mesh = solver_mesh_from_structured_arrays(
        nrow=1,
        ncol=2,
        top=np.array([[10.0, 10.0]]),
        botm=np.array([[[6.0, 12.0]], [[0.0, 14.0]]]),
    )

    assert (mesh.layer_center_depths() >= 0.0).all()
    assert mesh.layer_center_depths()[0, 0] == pytest.approx(2.0)


def test_row_0_is_at_the_north_like_modflow():
    mesh = solver_mesh_from_structured_arrays(
        nrow=3,
        ncol=2,
        top=np.zeros((3, 2)),
        botm=-np.ones((1, 3, 2)),
        dx=10.0,
        dy=5.0,
        xoff=100.0,
        yoff=200.0,
    )

    centers = mesh.cell_centers().reshape(3, 2, 2)

    assert centers[:, 0, 1] == pytest.approx([212.5, 207.5, 202.5])
    assert centers[0, :, 0] == pytest.approx([105.0, 115.0])
    assert mesh.yoffset == pytest.approx(200.0)
    assert mesh.yvertices[:, 0] == pytest.approx([215.0, 210.0, 205.0, 200.0])


def test_grid_from_arrays_is_a_regular_mesh_in_a_local_frame():
    mesh = solver_mesh_from_structured_arrays(
        nrow=2, ncol=3, top=np.zeros((2, 3)), botm=-np.ones((1, 2, 3)), dx=10.0, dy=5.0
    )

    assert mesh.cell_mesh.structured_shape == (2, 3)
    assert mesh.cell_mesh.center_kind == "cell_center"
    assert mesh.cell_mesh.crs_wkt
    assert mesh.cell_areas() == pytest.approx(np.full(6, 50.0))


def test_reshape_round_trip_on_a_non_square_grid():
    mesh = solver_mesh_from_structured_arrays(
        nrow=2, ncol=3, top=np.zeros((2, 3)), botm=np.zeros((1, 2, 3))
    )
    flat = np.arange(6, dtype=float)

    grid = mesh.reshape_to_grid(flat)

    assert grid.shape == (2, 3)
    np.testing.assert_array_equal(mesh.flatten_from_grid(grid), flat)


def test_delr_delc_of_a_structured_grid():
    mesh = solver_mesh_from_structured_arrays(
        nrow=2, ncol=2, top=np.zeros((2, 2)), botm=np.zeros((1, 2, 2)), dx=5.0, dy=7.0
    )

    delr, delc = mesh.structured_delr_delc()

    assert delr.tolist() == pytest.approx([5.0, 5.0])
    assert delc.tolist() == pytest.approx([7.0, 7.0])
    assert (mesh.nrow, mesh.ncol) == (2, 2)


def test_structured_only_members_raise_on_unstructured():
    mesh = two_quads()
    assert mesh.is_structured is False
    assert mesh.structured_shape is None

    for accessor in (
        lambda: mesh.nrow,
        lambda: mesh.ncol,
        lambda: mesh.delr,
        lambda: mesh.delc,
        lambda: mesh.xvertices,
        lambda: mesh.yvertices,
        lambda: mesh.structured_delr_delc(),
        lambda: mesh.to_dis_kwargs(),
    ):
        with pytest.raises(ValueError):
            accessor()


def test_reshape_is_identity_on_unstructured():
    flat = np.array([1.0, 2.0])

    np.testing.assert_array_equal(two_quads().reshape_to_grid(flat), flat)
    np.testing.assert_array_equal(two_quads().flatten_from_grid(flat), flat)


def test_closed_surface():
    # Column 1 has no active cell, column 2 is open only in the layer 2.
    mesh = three_cells()
    mesh = SolverMesh(
        cell_mesh=mesh.cell_mesh,
        top=mesh.top,
        botm=mesh.botm,
        idomain=np.array([[1, 0, 0], [1, 1, 0]]),
    )

    assert mesh.closed_surface().tolist() == [False, False, True]
    assert mesh.closed_surface([1]).tolist() == [False, True, True]


def test_to_dis_kwargs_of_a_structured_grid():
    mesh = solver_mesh_from_structured_arrays(
        nrow=2,
        ncol=3,
        top=np.full((2, 3), 10.0),
        botm=np.zeros((1, 2, 3)),
        dx=25.0,
        dy=25.0,
        xoff=300000.0,
        yoff=6800000.0,
    )

    kwargs = mesh.to_dis_kwargs()

    assert (kwargs["nlay"], kwargs["nrow"], kwargs["ncol"]) == (1, 2, 3)
    assert np.asarray(kwargs["delr"]).tolist() == pytest.approx([25.0, 25.0, 25.0])
    assert np.asarray(kwargs["delc"]).tolist() == pytest.approx([25.0, 25.0])
    np.testing.assert_array_equal(kwargs["top"], np.full((2, 3), 10.0))
    np.testing.assert_array_equal(kwargs["botm"], np.zeros((1, 2, 3)))


# MODFLOW 6 builds a DISV for every grid, even a regular one. Native DIS belongs to NWT only.


def test_modflow6_uses_disv_for_a_structured_grid(tmp_path):
    mesh = solver_mesh_from_structured_arrays(
        nrow=2,
        ncol=3,
        top=np.full((2, 3), 10.0),
        botm=np.zeros((1, 2, 3)),
        dx=25.0,
        dy=25.0,
        xoff=300000.0,
        yoff=6800000.0,
    )
    assert mesh.is_structured is True
    sim = flopy.mf6.MFSimulation(sim_name="sim", sim_ws=str(tmp_path), exe_name="mf6")
    flopy.mf6.ModflowTdis(sim, nper=1, perioddata=[(1.0, 1, 1.0)], time_units="SECONDS")
    gwf = flopy.mf6.ModflowGwf(sim, modelname="flow")
    ims = flopy.mf6.ModflowIms(sim, filename="flow.ims")
    sim.register_ims_package(ims, [gwf.name])

    # Vertices are absolute, so the origin is 0.
    disv = flopy.mf6.ModflowGwfdisv(
        gwf,
        nlay=mesh.nlay,
        **mesh.to_disv_kwargs(),
        idomain=mesh.idomain,
        xorigin=0.0,
        yorigin=0.0,
        length_units="METERS",
    )

    assert type(disv).__name__ == "ModflowGwfdisv"
    assert int(disv.ncpl.get_data()) == 6
    assert int(disv.nlay.get_data()) == 1
    assert int(disv.nvert.get_data()) == 12
    assert float(disv.xorigin.get_data()) == pytest.approx(0.0)
    assert np.asarray(disv.parent.modelgrid.xcellcenters).min() > 300000.0


def test_grid_mapping_descriptors_are_removed():
    with pytest.raises(ModuleNotFoundError):
        import hydromodpy.solver.modflow_grid.grid_mapping  # noqa: F401
    with pytest.raises(ImportError):
        from hydromodpy.solver.modflow_grid import describe_grid  # noqa: F401


# DISV cell centers. A regular mesh gives its cell centers, a Voronoi mesh its generators,
# any other mesh the vertex means.


def test_clockwise_grid_keeps_its_rings_and_its_cell_centres():
    cell_mesh = regular_mesh(2, 3, dx=10.0)

    result = to_flopy_disv_args(cell_mesh.mesh, top=10.0, botm=np.zeros((1, 6)))

    for row, nodes, centre in zip(
        result["cell2d"], cell_mesh.mesh.flat_connectivity, cell_mesh.centers, strict=True
    ):
        assert row[3] == 4
        assert row[4:] == nodes.tolist()
        assert row[1:3] == pytest.approx(centre.tolist())


def test_voronoi_seeds_are_the_disv_centres():
    vertices = np.array([[1, 0], [1, 1], [0, 1], [-0.3, 0.5], [0, 0], [2, 0], [2, 1]], dtype=float)
    seeds = np.array([[0.3, 0.5], [1.5, 0.5]])
    mesh = HydroMesh(
        vertices=vertices,
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


def test_voronoi_engine_mesh_writes_its_generators_as_the_disv_centres():
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


def test_mesh_without_generators_writes_the_vertex_means():
    vertices = np.array([[0, 0], [1, 0], [0, 1], [1, 1]], dtype=float)
    planar = HydroMesh(
        vertices=vertices, cell_blocks=(CellBlock(CellType.TRIANGLE, [[0, 1, 2], [1, 3, 2]]),)
    )
    solver = solver_mesh_from(planar, np.full(2, 10.0), np.zeros((1, 2)), np.zeros((1, 2), bool))
    by_hand = to_flopy_disv_args(planar, top=10.0, botm=np.zeros((1, 2)))

    assert solver.generator_centers is None
    assert solver.to_disv_kwargs()["cell2d"] == by_hand["cell2d"]
    assert by_hand["cell2d"][1][1:3] == pytest.approx([2.0 / 3.0, 2.0 / 3.0])


SOLVER_REFUSALS = [
    pytest.param(
        np.zeros(2), np.zeros((1, 3)), np.ones((1, 3), int), "top must have", id="top size"
    ),
    pytest.param(
        np.zeros(3), np.zeros((2, 3)), np.ones((1, 3), int), "idomain", id="idomain layers"
    ),
    pytest.param(
        np.zeros(3),
        np.zeros((2, 3)),
        np.array([[1, 2, 1], [1, 1, 1]]),
        "only -1, 0 and 1",
        id="idomain value",
    ),
]


@pytest.mark.parametrize(("top", "botm", "idomain", "match"), SOLVER_REFUSALS)
def test_solver_mesh_refusals(top, botm, idomain, match):
    with pytest.raises(ValueError, match=match):
        SolverMesh(cell_mesh=three_cells().cell_mesh, top=top, botm=botm, idomain=idomain)


def test_disv_refuses_a_3d_mesh():
    vertices = np.array(
        [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 1]], dtype=float
    )
    mesh = HydroMesh(
        vertices=vertices,
        cell_blocks=(CellBlock(CellType.WEDGE, np.array([[0, 1, 2, 3, 4, 5]])),),
    )

    with pytest.raises(ValueError, match="2D mesh"):
        to_flopy_disv_args(mesh, top=10.0, botm=np.array([[5.0]]))
