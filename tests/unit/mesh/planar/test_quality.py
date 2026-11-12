"""Mesh QA on meshes whose quality is known."""

from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.geometry import derive_geometry
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.mesh.planar.planar_cell_mesh import CellChain, FaceFamilyTable
from hydromodpy.mesh.planar.quality import (
    RELATIVE_FACE_TOLERANCE,
    cell_angle_range,
    cell_corner_angles,
    cell_edge_max,
    compute_mesh_qa,
    connection_nonorthogonality_deg,
    edge_bisection_offset,
    mixed_cells,
    nonorthogonality_summary,
    quality_warnings,
)
from tests._helpers.mesh_cases import L93_ORIGIN, regular_mesh

X0, Y0 = L93_ORIGIN
"""North-west corner of the grid."""
DECLARATIONS = {"graded": False, "exact_faces": False, "deterministic": True, "needs_cache": False}
NROW, NCOL, DX, DY = 4, 5, 25.0, 25.0


def _grid() -> tuple[HydroMesh, np.ndarray]:
    mesh = regular_mesh(NROW, NCOL, dx=DX, dy=DY, xmin=X0, ymin=Y0 - NROW * DY).mesh
    x = X0 + (np.arange(NCOL) + 0.5) * DX
    y = Y0 - (np.arange(NROW) + 0.5) * DY
    xx, yy = np.meshgrid(x, y)
    return mesh, np.column_stack([xx.ravel(), yy.ravel()])


def _qa(mesh: HydroMesh, centers: np.ndarray, **kwargs):
    return compute_mesh_qa(
        mesh, centers, derive_geometry(mesh), declarations=DECLARATIONS, **kwargs
    )


def test_regular_grid_is_clean() -> None:
    mesh, centers = _grid()
    qa = _qa(mesh, centers, domain_area_m2=NROW * NCOL * DX * DY)

    assert qa.n_cells == NROW * NCOL
    assert qa.area_sum_rel_error == pytest.approx(0.0, abs=1e-15)
    assert qa.nonorthogonality_deg["max"] == pytest.approx(0.0, abs=1e-9)
    assert qa.neighbour_ratio == {
        "p50": 1.0,
        "p95": 1.0,
        "p99": 1.0,
        "max": 1.0,
        "share_gt_1_5": 0.0,
    }
    assert qa.center_offset["max"] == pytest.approx(0.0, abs=1e-9)
    assert qa.area_quantiles_m2["min"] == pytest.approx(DX * DY, rel=1e-12)
    assert qa.size_quantiles_m["p50"] == pytest.approx(DX, rel=1e-12)
    assert qa.min_face_length_m == pytest.approx(RELATIVE_FACE_TOLERANCE * DX)
    assert qa.n_degenerate_faces == 0
    assert qa.n_duplicate_vertices_in_cells == 0
    assert qa.bisection_offset["max"] == pytest.approx(0.0, abs=1e-9)
    assert qa.bisection_offset["n_cells_gt_0_25"] == 0.0
    assert qa.min_angle_deg["min"] == pytest.approx(90.0)
    assert qa.min_angle_deg["n_triangles_lt_20"] == 0.0
    assert qa.max_angle_deg["max"] == pytest.approx(90.0)
    assert qa.n_concave_cells == 0
    assert quality_warnings(qa) == ()


def test_offset_centre() -> None:
    mesh, centers = _grid()
    centers[0, 0] += 0.25 * DX
    qa = _qa(mesh, centers)

    assert qa.center_offset["max"] == pytest.approx(0.25)
    assert qa.nonorthogonality_deg["max"] == pytest.approx(np.degrees(np.arctan(0.25)))


def test_share_above_30_degrees() -> None:
    mesh, centers = _grid()
    n_interior_faces = NROW * (NCOL - 1) + (NROW - 1) * NCOL
    centers[0, 0] += 0.6 * DX
    tilted = _qa(mesh, centers)
    centers[0, 0] -= 0.35 * DX
    gentle = _qa(mesh, centers)

    assert tilted.nonorthogonality_deg["share_gt_30"] == pytest.approx(1.0 / n_interior_faces)
    assert gentle.nonorthogonality_deg["share_gt_30"] == 0.0


def test_neighbour_ratio() -> None:
    vertices = np.array([[0, 0], [1, 0], [3, 0], [3, 2], [1, 2], [0, 2]], dtype=float)
    quads = np.array([[0, 1, 4, 5], [1, 2, 3, 4]])
    mesh = HydroMesh(vertices=vertices, cell_blocks=(CellBlock(CellType.QUADRILATERAL, quads),))
    centers = np.array([[0.5, 1.0], [2.0, 1.0]])
    qa = _qa(mesh, centers)

    assert qa.neighbour_ratio["max"] == pytest.approx(np.sqrt(2.0))
    assert qa.neighbour_ratio["share_gt_1_5"] == 0.0


def test_cell_chain_breaks_and_face_steps() -> None:
    mesh, centers = _grid()
    # 0 -> 1 face, 1 -> 7 vertex (diagonal), 7 -> 7 stay, 7 -> 19 break.
    chain = CellChain(family="rivers", chain_id=0, cell_ids=np.array([0, 1, 7, 7, 19]))
    line = LineString([centers[0], centers[1], centers[7]])
    qa = _qa(mesh, centers, cell_chains=(chain,), lines={"rivers": [line]})

    family = qa.families["rivers"]
    assert family["chains"] == 1.0
    assert family["cells"] == 4.0
    assert family["breaks"] == 1.0
    assert family["face_step_share"] == pytest.approx(1.0 / 3.0)
    assert family["max_line_offset_m"] == pytest.approx(np.hypot(*(centers[19] - centers[7])))


def _column_faces(mesh: HydroMesh, geometry) -> FaceFamilyTable:
    """The faces on the grid line x = X0 + 2 * DX, as the family ``geology``."""
    nodes = geometry.edge_nodes
    on_line = np.all(np.isclose(mesh.vertices[nodes][..., 0], X0 + 2 * DX), axis=1)
    rows = np.flatnonzero(on_line)
    return FaceFamilyTable(
        names=("geology",),
        family=np.zeros(rows.size),
        cell_a=geometry.edge_cells[rows, 0],
        cell_b=geometry.edge_cells[rows, 1],
        node_a=nodes[rows, 0],
        node_b=nodes[rows, 1],
        zone_left=np.full(rows.size, -1),
        zone_right=np.full(rows.size, -1),
    )


def test_face_family_coverage() -> None:
    mesh, centers = _grid()
    geometry = derive_geometry(mesh)
    table = _column_faces(mesh, geometry)
    exact = LineString([(X0 + 2 * DX, Y0), (X0 + 2 * DX, Y0 - NROW * DY)])
    shifted = LineString([(X0 + 2 * DX + 3.0, Y0), (X0 + 2 * DX + 3.0, Y0 - NROW * DY)])

    on = compute_mesh_qa(
        mesh,
        centers,
        geometry,
        declarations=DECLARATIONS,
        face_families=table,
        lines={"geology": [exact]},
    ).families["geology"]
    off = compute_mesh_qa(
        mesh,
        centers,
        geometry,
        declarations=DECLARATIONS,
        face_families=table,
        lines={"geology": [shifted]},
    ).families["geology"]

    assert on["faces"] == float(NROW)
    assert on["length_m"] == pytest.approx(NROW * DY)
    assert on["covered_length_rel"] == pytest.approx(1.0)
    assert on["hausdorff_m"] == pytest.approx(0.0, abs=1e-9)
    assert off["covered_length_rel"] == pytest.approx(0.0)
    assert off["hausdorff_m"] == pytest.approx(3.0)


def test_declarations_refused() -> None:
    mesh, centers = _grid()

    with pytest.raises(ValueError, match="declarations"):
        compute_mesh_qa(mesh, centers, derive_geometry(mesh), declarations={"graded": True})


def test_centres_shape_refused() -> None:
    mesh, centers = _grid()

    with pytest.raises(ValueError, match="centers"):
        _qa(mesh, centers[:-1])


def _mixed_cells(line: LineString) -> float:
    mesh, centers = _grid()
    geometry = derive_geometry(mesh)
    qa = compute_mesh_qa(
        mesh,
        centers,
        geometry,
        declarations=DECLARATIONS,
        face_families=_column_faces(mesh, geometry),
        lines={"geology": [line]},
    )
    return qa.families["geology"]["mixed_cells"]


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        # On the grid line, and within a millimeter of it: the faces follow the line.
        (LineString([(X0 + 2 * DX, Y0), (X0 + 2 * DX, Y0 - NROW * DY)]), 0.0),
        (LineString([(X0 + 2 * DX + 5e-4, Y0), (X0 + 2 * DX + 5e-4, Y0 - NROW * DY)]), 0.0),
        # Three meters inside the column of cells right of the grid line: four cells crossed.
        (LineString([(X0 + 2 * DX + 3.0, Y0), (X0 + 2 * DX + 3.0, Y0 - NROW * DY)]), 4.0),
        # The diagonal of two cells.
        (LineString([(X0, Y0), (X0 + 2 * DX, Y0 - 2 * DY)]), 2.0),
        # A contact mapped outside the grid crosses no cell.
        (LineString([(X0 - 3 * DX, Y0), (X0 - 3 * DX, Y0 - NROW * DY)]), 0.0),
    ],
)
def test_mixed_cells_crossed(line: LineString, expected: float) -> None:
    assert _mixed_cells(line) == expected


def _grid_mixed_cells(source) -> np.ndarray:
    mesh, _ = _grid()
    geometry = derive_geometry(mesh)
    tolerance = RELATIVE_FACE_TOLERANCE * float(np.median(geometry.edge_length))
    return mixed_cells(source, geometry, np.asarray(mesh.vertices, dtype=float), tolerance)


def test_line_off_mesh_crosses_no_cell() -> None:
    away = LineString([(X0 - 3 * DX, Y0), (X0 - 3 * DX, Y0 - NROW * DY)])

    assert _grid_mixed_cells(away).size == 0


def test_size_fidelity() -> None:
    mesh, centers = _grid()
    on_target = _qa(mesh, centers, target_size=np.full(NROW * NCOL, DX))
    twice = _qa(mesh, centers, target_size=np.full(NROW * NCOL, 2 * DX))

    assert on_target.size_fidelity == pytest.approx({"p5": 1.0, "p50": 1.0, "p95": 1.0})
    assert twice.size_fidelity["p50"] == pytest.approx(0.5)
    assert _qa(mesh, centers).size_fidelity == {}


@pytest.mark.parametrize(
    "target_size", [np.full(3, DX), np.zeros(NROW * NCOL)], ids=["wrong length", "zero size"]
)
def test_target_size_refused(target_size) -> None:
    mesh, centers = _grid()

    with pytest.raises(ValueError, match="target_size"):
        _qa(mesh, centers, target_size=target_size)


def _edge(geometry, first: int, second: int) -> int:
    """Return the row of the edge between two cells."""
    return int(np.flatnonzero((geometry.edge_cells == [first, second]).all(axis=1))[0])


def test_bisection_offset_range() -> None:
    mesh, centers = _grid()
    geometry = derive_geometry(mesh)
    vertices = np.asarray(mesh.vertices)
    interior = geometry.edge_cells[:, 1] >= 0
    face = _edge(geometry, 0, 1)

    centred = edge_bisection_offset(centers, vertices, geometry, interior)
    # Both centers moved up to the top edge of the row: the line runs through a face end.
    raised = centers.copy()
    raised[[0, 1], 1] += 0.5 * DY
    at_the_end = edge_bisection_offset(raised, vertices, geometry, interior)
    # Both centers on the line of the face: no crossing to measure.
    on_the_face = centers.copy()
    on_the_face[[0, 1]] = [[X0 + DX, Y0 - 5.0], [X0 + DX, Y0 - 20.0]]
    parallel = edge_bisection_offset(on_the_face, vertices, geometry, interior)

    np.testing.assert_allclose(centred[interior], 0.0, atol=1e-9)
    assert np.isnan(centred[~interior]).all()
    assert at_the_end[face] == pytest.approx(0.5)
    assert np.isnan(parallel[face])


def test_bisection_offset_slanted() -> None:
    mesh, centers = _grid()
    geometry = derive_geometry(mesh)
    interior = geometry.edge_cells[:, 1] >= 0
    shifted = centers.copy()
    shifted[0] += [3.0, 4.0]

    offset = edge_bisection_offset(shifted, np.asarray(mesh.vertices), geometry, interior)

    # From (15.5, -8.5) to (37.5, -12.5) relative to the origin, the line meets
    # x = 25 at y = -8.5 - 4 * 9.5 / 22, a face of 25 m centered on y = -12.5.
    crossing = -8.5 - 4.0 * 9.5 / 22.0
    assert offset[_edge(geometry, 0, 1)] == pytest.approx(abs(crossing + 12.5) / DX)


L_SHAPE = np.array([[0, 0], [2, 0], [2, 1], [1, 1], [1, 2], [0, 2]], dtype=float)
RIGHT_TRIANGLE = np.array([[0, 0], [2, 0], [0, 1]], dtype=float)


def test_reflex_corner_angles() -> None:
    vertices = np.vstack([L_SHAPE, RIGHT_TRIANGLE]) * 10.0 + [X0, Y0]
    padded = np.array(
        [
            [0, 1, 2, 3, 4, 5],
            [5, 4, 3, 2, 1, 0],
            [6, 7, 8, -1, -1, -1],
        ]
    )

    angles = cell_corner_angles(padded, vertices)

    np.testing.assert_allclose(angles[0], [90.0, 90.0, 90.0, 270.0, 90.0, 90.0], atol=1e-9)
    np.testing.assert_allclose(angles[1], angles[0][::-1], atol=1e-9)
    small = np.degrees(np.arctan2(1.0, 2.0))
    np.testing.assert_allclose(angles[2, :3], [90.0, small, 90.0 - small], atol=1e-9)
    assert np.isnan(angles[2, 3:]).all()


def test_repeated_vertex_has_no_angle() -> None:
    square = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])

    angles = cell_corner_angles(np.array([[0, 1, 1, 2, 3]]), square)

    assert np.isnan(angles[0, [1, 2]]).all()
    np.testing.assert_allclose(angles[0, [0, 3, 4]], 90.0, atol=1e-12)


def test_skewed_face_count() -> None:
    mesh, centers = _grid()
    centers[0] += [7.5, 10.0]
    qa = _qa(mesh, centers)

    # From (20, -2.5) to (37.5, -12.5) relative to the origin, the line meets x = 25
    # at y = -2.5 - 10 * 5 / 17.5, 2/7 of the face from its middle. The face below
    # is crossed 0.107 from its middle, under the threshold.
    assert qa.bisection_offset["max"] == pytest.approx(2.0 / 7.0)
    assert qa.bisection_offset["n_cells_gt_0_25"] == 2.0
    (warning,) = quality_warnings(qa)
    assert warning.startswith("2 of 20 cells have a face crossed")


def _l_and_sliver() -> tuple[HydroMesh, np.ndarray]:
    """An L-shaped cell and, apart, a triangle with a 14 degree corner."""
    sliver = np.array([[3.0, 0.0], [5.0, 0.0], [3.0, 0.5]])
    vertices = np.vstack([L_SHAPE, sliver]) * 10.0 + [X0, Y0]
    cells = (np.arange(6), np.array([6, 7, 8]))
    mesh = HydroMesh(vertices=vertices, cell_blocks=(CellBlock(CellType.POLYGON, cells),))
    centers = np.array([[X0 + 5.0, Y0 + 5.0], [X0 + 36.0, Y0 + 1.5]])
    return mesh, centers


def test_sliver_and_concave_warnings() -> None:
    qa = _qa(*_l_and_sliver())

    sharp = np.degrees(np.arctan2(0.5, 2.0))
    assert qa.min_angle_deg["min"] == pytest.approx(sharp)
    assert qa.min_angle_deg["n_triangles_lt_20"] == 1.0
    assert qa.max_angle_deg["max"] == pytest.approx(270.0)
    assert qa.n_concave_cells == 1
    warnings = quality_warnings(qa)
    assert len(warnings) == 2
    assert warnings[0].startswith("1 of 2 cells are triangles with a corner under 20 degrees")
    assert warnings[1] == "1 of 2 cells are concave (largest corner 270.0 degrees)."


def test_dart_is_concave_not_sliver() -> None:
    # A corner under 20 degrees counts only on a triangle.
    dart = np.array([[0.0, 0.0], [4.0, 0.5], [0.0, 1.0], [1.0, 0.5]]) * 10.0 + [X0, Y0]
    mesh = HydroMesh(vertices=dart, cell_blocks=(CellBlock(CellType.POLYGON, (np.arange(4),)),))
    smallest, largest = cell_angle_range(np.arange(4)[None, :], dart)
    qa = _qa(mesh, np.array([[X0 + 15.0, Y0 + 5.0]]))

    assert smallest[0] == pytest.approx(2.0 * np.degrees(np.arctan2(0.5, 4.0)))
    assert qa.min_angle_deg["min"] == pytest.approx(smallest[0])
    assert qa.min_angle_deg["n_triangles_lt_20"] == 0.0
    assert qa.n_concave_cells == 1
    assert qa.max_angle_deg["max"] == pytest.approx(largest[0])
    assert largest[0] > 180.0


def test_unmeasured_is_nan() -> None:
    square = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])
    smallest, largest = cell_angle_range(np.array([[0, 1, 2, 3], [0, 0, 0, -1]]), square)
    mesh, _ = _grid()
    geometry = derive_geometry(mesh)

    np.testing.assert_allclose([smallest[0], largest[0]], 90.0)
    assert np.isnan([smallest[1], largest[1]]).all()
    assert np.isnan(cell_edge_max(geometry, np.full(geometry.edge_cells.shape[0], np.nan))).all()


def test_orthogonal_mesh_no_warning() -> None:
    # Every center moved by the same vector keeps each connection normal to its
    # face, while the vertical faces are crossed 0.3 of their length off middle.
    mesh, centers = _grid()
    centers[:, 1] += 0.3 * DY
    qa = _qa(mesh, centers)

    assert qa.nonorthogonality_deg["p95"] == pytest.approx(0.0, abs=1e-9)
    assert qa.bisection_offset["max"] == pytest.approx(0.3)
    assert qa.bisection_offset["n_cells_gt_0_25"] > 0
    assert quality_warnings(qa) == ()


PENTAGON_AND_QUAD = np.array(
    [[1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [-0.3, 0.5], [0.0, 0.0], [2.0, 0.0], [2.0, 1.0]]
)
"""A left pentagon and a right quad that share the vertical edge (1, 0)-(1, 1)."""


PENTAGON_AND_QUAD_MESH = HydroMesh(
    vertices=PENTAGON_AND_QUAD,
    cell_blocks=(
        CellBlock(
            cell_type=CellType.POLYGON,
            connectivity=(np.array([0, 1, 2, 3, 4]), np.array([0, 5, 6, 1])),
        ),
    ),
)


def _angles_from(centres: list[list[float]]) -> np.ndarray:
    return connection_nonorthogonality_deg(
        PENTAGON_AND_QUAD_MESH, centers=np.array(centres, dtype=float)
    )


# Seeds on a horizontal line across the vertical shared face, then a link tilted by 45 degrees.
LINKS = [
    pytest.param([[0.3, 0.5], [1.5, 0.5]], 0.0, id="perpendicular to the face"),
    pytest.param([[0.5, 0.0], [1.5, 1.0]], 45.0, id="tilted by 45 degrees"),
]


@pytest.mark.parametrize(("centres", "expected_deg"), LINKS)
def test_link_nonorthogonality(centres, expected_deg) -> None:
    angles = _angles_from(centres)

    assert angles.shape == (1,)
    np.testing.assert_allclose(angles, [expected_deg], atol=1e-6)


def test_empty_mesh_summary() -> None:
    empty = HydroMesh(
        vertices=PENTAGON_AND_QUAD,
        cell_blocks=(CellBlock(cell_type=CellType.POLYGON, connectivity=()),),
    )

    assert connection_nonorthogonality_deg(empty).size == 0
    assert set(nonorthogonality_summary(empty).values()) == {0.0}


def test_three_cells_on_an_edge() -> None:
    vertices = np.array([[0.0, 0.0], [1.0, 0.0], [0.5, 1.0], [0.5, -1.0], [2.0, 0.5]])
    fan = HydroMesh(
        vertices=vertices,
        cell_blocks=(CellBlock(CellType.TRIANGLE, [[0, 1, 2], [1, 0, 3], [0, 1, 4]]),),
    )

    with pytest.raises(ValueError, match="shared by 3 cells"):
        connection_nonorthogonality_deg(fan)
