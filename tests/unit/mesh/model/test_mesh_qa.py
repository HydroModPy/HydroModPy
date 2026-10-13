"""Mesh QA on meshes whose quality is known."""

from __future__ import annotations

import json

import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.derived_geometry import derive_geometry
from hydromodpy.spatial.mesh.model.grid_wrappers import RegularGrid
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.spatial.mesh.model.mesh_qa import compute_mesh_qa
from hydromodpy.spatial.mesh.model.planar_cell_mesh import CellChain, FaceFamilyTable

X0, Y0 = 351_250.0, 6_789_500.0
DECLARATIONS = {"graded": False, "exact_faces": False, "deterministic": True, "needs_cache": False}
NROW, NCOL, DX, DY = 4, 5, 25.0, 25.0


def _grid() -> tuple[HydroMesh, np.ndarray]:
    mesh = RegularGrid(shape=(NROW, NCOL), dx=DX, dy=DY, origin=(X0, Y0)).to_hydro_mesh()
    x = X0 + (np.arange(NCOL) + 0.5) * DX
    y = Y0 - (np.arange(NROW) + 0.5) * DY
    xx, yy = np.meshgrid(x, y)
    return mesh, np.column_stack([xx.ravel(), yy.ravel()])


def _qa(mesh: HydroMesh, centers: np.ndarray, **kwargs):
    return compute_mesh_qa(
        mesh, centers, derive_geometry(mesh), declarations=DECLARATIONS, **kwargs
    )


def test_a_regular_grid_is_orthogonal_uniform_and_centred() -> None:
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
    assert qa.min_face_length_m == pytest.approx(1e-3 * DX)
    assert qa.n_degenerate_faces == 0
    assert qa.n_duplicate_vertices_in_cells == 0


def test_an_offset_centre_shows_in_offset_and_orthogonality() -> None:
    mesh, centers = _grid()
    centers[0, 0] += 0.25 * DX
    qa = _qa(mesh, centers)

    assert qa.center_offset["max"] == pytest.approx(0.25)
    assert qa.nonorthogonality_deg["max"] == pytest.approx(np.degrees(np.arctan(0.25)))


def test_neighbour_ratio_compares_the_square_root_of_areas() -> None:
    vertices = np.array([[0, 0], [1, 0], [3, 0], [3, 2], [1, 2], [0, 2]], dtype=float)
    quads = np.array([[0, 1, 4, 5], [1, 2, 3, 4]])
    mesh = HydroMesh(vertices=vertices, cell_blocks=(CellBlock(CellType.QUADRILATERAL, quads),))
    centers = np.array([[0.5, 1.0], [2.0, 1.0]])
    qa = _qa(mesh, centers)

    assert qa.neighbour_ratio["max"] == pytest.approx(np.sqrt(2.0))
    assert qa.neighbour_ratio["share_gt_1_5"] == 0.0


def test_short_faces_are_left_out_of_the_orthogonality() -> None:
    mesh, centers = _grid()
    centers[0, 0] += 0.25 * DX
    skipped = _qa(mesh, centers, min_face_length_m=DX + 1.0)

    assert np.isnan(skipped.nonorthogonality_deg["max"])
    assert skipped.min_face_length_m == DX + 1.0


def test_repeated_corners_are_counted() -> None:
    vertices = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])
    cells = (np.array([0, 1, 1, 2, 3, 3]),)
    mesh = HydroMesh(vertices=vertices, cell_blocks=(CellBlock(CellType.POLYGON, cells),))

    assert _qa(mesh, np.array([[0.5, 0.5]])).n_duplicate_vertices_in_cells == 2


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


def test_a_face_family_on_its_line_covers_it_exactly() -> None:
    mesh, centers = _grid()
    geometry = derive_geometry(mesh)
    # The vertical grid line x = X0 + 2 * DX, faces between columns 1 and 2.
    nodes = geometry.edge_nodes
    on_line = np.all(np.isclose(mesh.vertices[nodes][..., 0], X0 + 2 * DX), axis=1)
    rows = np.flatnonzero(on_line)
    table = FaceFamilyTable(
        names=("geology",),
        family=np.zeros(rows.size),
        cell_a=geometry.edge_cells[rows, 0],
        cell_b=geometry.edge_cells[rows, 1],
        node_a=nodes[rows, 0],
        node_b=nodes[rows, 1],
        zone_left=np.full(rows.size, -1),
        zone_right=np.full(rows.size, -1),
    )
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


def test_declarations_must_state_the_four_engine_statements() -> None:
    mesh, centers = _grid()

    with pytest.raises(ValueError, match="declarations"):
        compute_mesh_qa(mesh, centers, derive_geometry(mesh), declarations={"graded": True})


def test_centres_of_the_wrong_shape_raise() -> None:
    mesh, centers = _grid()

    with pytest.raises(ValueError, match="centers"):
        _qa(mesh, centers[:-1])


def test_as_dict_is_json_ready() -> None:
    mesh, centers = _grid()
    qa = _qa(mesh, centers, notes=("regular ignores river_cell_size",), extras={"x": 1})

    payload = json.loads(json.dumps(qa.as_dict()))
    assert payload["notes"] == ["regular ignores river_cell_size"]
    assert payload["extras"] == {"x": 1.0}
    assert payload["declarations"] == DECLARATIONS
