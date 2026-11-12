"""The voronoi engine: generated generators, or the dual of a triangulation read."""

from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path

import numpy as np
import pytest
from shapely.geometry import LineString

from hydromodpy.mesh.engines.voronoi.engine import VoronoiMeshEngine, _platform_note
from hydromodpy.mesh.engines.voronoi.from_triangulation import _FACES_NOTE
from hydromodpy.mesh.engines.voronoi.local_coords import local_frame
from hydromodpy.mesh.io.msh import read_msh
from hydromodpy.mesh.planning.input_triangulation import domain_polygon_from_mesh
from hydromodpy.mesh.planning.size_field import SizeTerm, build_size_field
from hydromodpy.mesh.request import InputTriangulation, LineFamilySpec, MeshRequest
from hydromodpy.mesh.resample import resample_families
from tests._helpers.mesh_cases import (
    L93_ORIGIN,
    bundle_msh,
    bundle_triangulation,
    grid_over,
    mesh_request,
    square_domain,
    uniform_size_field,
)

X0, Y0 = L93_ORIGIN
SQUARE = square_domain(1000.0, x0=X0, y0=Y0)
GOLDEN = Path(__file__).resolve().parent / "golden"

RIVER = LineString([(X0 + 100, Y0 + 150), (X0 + 450, Y0 + 420), (X0 + 900, Y0 + 880)])
CONTACT = LineString([(X0 + 400, Y0), (X0 + 600, Y0 + 1000)])


def _square(size: float = 40.0, **options: object) -> MeshRequest:
    """A 1 km square with a river and a contact, resampled on a constant size field."""
    grid = grid_over(SQUARE, 20.0)
    field = uniform_size_field(grid, size)
    families = (
        LineFamilySpec("rivers", "cell", (RIVER,)),
        LineFamilySpec("geology", "face", (CONTACT,), ("west_unit",), ("east_unit",)),
    )
    return mesh_request(
        grid,
        nominal_size_m=size,
        lines=resample_families(families, domain=SQUARE, size_field=field).families,
        size_field=field,
        options=options,
    )


def _graded_square(max_slope: float) -> MeshRequest:
    """A 1 km square whose size grows from 20 m on the river to 80 m at the slope asked."""
    grid = grid_over(SQUARE, 20.0)
    field = build_size_field(
        grid,
        h0=80.0,
        h_floor=20.0,
        terms=[SizeTerm("rivers", RIVER, 20.0, 0.0)],
        outside=None,
        max_slope=max_slope,
    )
    families = (LineFamilySpec("rivers", "cell", (RIVER,)),)
    return mesh_request(
        grid,
        nominal_size_m=80.0,
        lines=resample_families(families, domain=SQUARE, size_field=field).families,
        size_field=field,
    )


def _read(bundle: str, **options: object) -> MeshRequest:
    """The triangles of a committed bundle as a triangulation to read."""
    domain = domain_polygon_from_mesh(read_msh(bundle_msh(bundle)))
    return mesh_request(
        grid_over(domain),
        domain=domain,
        nominal_size_m=10.0,
        input_triangulation=bundle_triangulation(bundle),
        options=options,
    )


_LATTICE_X = np.array([0.0, 100.0, 200.0, 300.0, 400.0, 500.0, 620.0, 740.0, 860.0, 1000.0])
_LATTICE_Y = np.linspace(0.0, 1000.0, 11)


def _lattice(river: bool = True, contact: bool = True) -> MeshRequest:
    """A 1 km square triangulated on a 10 x 11 lattice, its river and contact on lattice edges.

    The columns are wider east of the contact, so the triangles around a vertex of the
    contact lie mostly on its west side: the vote that gives a cell its side has no tie.
    """
    vertices = np.array([(X0 + x, Y0 + y) for y in _LATTICE_Y for x in _LATTICE_X])
    width = len(_LATTICE_X)
    triangles = []
    for j in range(len(_LATTICE_Y) - 1):
        for i in range(width - 1):
            n00, n10 = j * width + i, j * width + i + 1
            n01, n11 = (j + 1) * width + i, (j + 1) * width + i + 1
            triangles += [(n00, n10, n11), (n00, n11, n01)]
    lines = []
    if river:
        lines.append(
            LineFamilySpec("rivers", "cell", (LineString([(X0, Y0 + 300), (X0 + 1000, Y0 + 300)]),))
        )
    if contact:
        lines.append(
            LineFamilySpec(
                "geology",
                "face",
                (LineString([(X0 + 500, Y0), (X0 + 500, Y0 + 1000)]),),
                ("west_unit",),
                ("east_unit",),
            )
        )
    return mesh_request(
        grid_over(SQUARE, 100.0),
        nominal_size_m=100.0,
        lines=tuple(lines),
        input_triangulation=InputTriangulation(vertices, np.array(triangles), {}),
    )


# --------------------------------------------------------------------------- #
# The dual of a triangulation read
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "bundle",
    [
        "dupuit_circular_island_ocean_irregular_tri_radial_48",
        "stream_depletion_glover_balmer_tri_refined_well",
    ],
)
def test_the_dual_of_a_triangulation_keeps_the_faces_of_the_old_dual(bundle: str) -> None:
    """The golden froze the dual of 7b940dc91 (Qhull, 1 mm rounding): same faces, areas to 1e-5."""
    golden = np.load(GOLDEN / f"old_dual_{bundle}.npz")
    cell_mesh = VoronoiMeshEngine().build(_read(bundle, seeds="triangulation"))

    geometry = cell_mesh.geometry
    faces = np.ascontiguousarray(geometry.edge_cells[geometry.edge_cells[:, 1] >= 0])
    faces = faces[np.lexsort((faces[:, 1], faces[:, 0]))].astype(np.int64)
    assert len(faces) == int(golden["n_faces"])
    assert hashlib.sha256(faces.tobytes()).hexdigest() == str(golden["faces_sha256"])
    assert np.allclose(geometry.areas, golden["areas"], rtol=1e-5, atol=0.0)
    assert cell_mesh.center_kind == "generator"
    assert cell_mesh.identity.seed is None


def test_a_lattice_river_is_a_chain_and_its_faces_are_the_dual_faces_it_crosses() -> None:
    request = _lattice(contact=False)
    cell_mesh = VoronoiMeshEngine().build(request)
    on_the_river = np.isclose(request.input_triangulation.vertices[:, 1], Y0 + 300.0)

    (chain,) = cell_mesh.chains("rivers")
    assert len(chain.cell_ids) == on_the_river.sum()
    assert np.allclose(cell_mesh.centers[chain.cell_ids, 1], Y0 + 300.0)
    rows = cell_mesh.face_rows("rivers")
    table = cell_mesh.face_families
    inside = rows & (table.cell_b >= 0)
    pairs = {tuple(sorted(p)) for p in zip(table.cell_a[inside], table.cell_b[inside], strict=True)}
    assert pairs == {
        tuple(sorted(p)) for p in zip(chain.cell_ids[:-1], chain.cell_ids[1:], strict=True)
    }
    # The two river ends lie on the west and east sides: the faces they touch there are rows too.
    ends = rows & (table.cell_b < 0)
    assert set(table.cell_a[ends].tolist()) == {int(chain.cell_ids[0]), int(chain.cell_ids[-1])}
    assert cell_mesh.qa.families["rivers"]["breaks"] == 0.0


def test_a_contact_of_a_triangulation_becomes_a_staircase_that_names_its_zones() -> None:
    cell_mesh = VoronoiMeshEngine().build(_lattice(river=False))
    table = cell_mesh.face_families
    rows = cell_mesh.face_rows("geology")
    names = np.asarray(cell_mesh.zone_names)

    assert rows.sum() > 0
    assert set(names[table.zone_left[rows]]) == {"west_unit"}
    assert set(names[table.zone_right[rows]]) == {"east_unit"}
    start = cell_mesh.mesh.vertices[table.node_a[rows]]
    face = cell_mesh.mesh.vertices[table.node_b[rows]] - start
    reach = cell_mesh.geometry.area_centroids[table.cell_a[rows]] - start
    assert np.all(face[:, 0] * reach[:, 1] - face[:, 1] * reach[:, 0] > 0.0)
    assert _FACES_NOTE in cell_mesh.qa.notes


def test_a_dual_gives_no_cell_zone_and_no_lake_staircase_to_the_readers_of_exact_faces() -> None:
    """The engine declares exact faces; a staircase is not, so the dual keeps what it published."""
    request = _lattice(river=False)
    shore = LineString([(X0 + 200, Y0 + 200), (X0 + 800, Y0 + 200), (X0 + 800, Y0 + 800)])
    lakes = LineFamilySpec("lakes", "face", (shore,))
    cell_mesh = VoronoiMeshEngine().build(
        dataclasses.replace(request, lines=(*request.lines, lakes))
    )

    assert cell_mesh.face_rows("geology").any()
    assert cell_mesh.cell_zone is None
    assert not cell_mesh.face_rows("lakes").any()


def test_the_sides_of_a_triangulation_keep_the_faces_of_the_cells_centred_on_them() -> None:
    request = _lattice(river=False, contact=False)
    cell_mesh = VoronoiMeshEngine().build(request)
    west = cell_mesh.face_rows("boundary:west")
    table = cell_mesh.face_families

    assert west.sum() == np.sum(request.input_triangulation.vertices[:, 0] == X0)
    assert np.allclose(cell_mesh.centers[table.cell_a[west], 0], X0)


# --------------------------------------------------------------------------- #
# Generated generators
# --------------------------------------------------------------------------- #


def test_the_qa_reports_the_relaxation_the_seeds_and_the_libraries() -> None:
    request = _square(size=60.0)
    cell_mesh = VoronoiMeshEngine().build(request)
    extras = cell_mesh.qa.extras

    for key in (
        "lloyd_iterations",
        "lloyd_cap",
        "lloyd_converged",
        "lloyd_move_rms",
        "lloyd_move_p50",
        "lloyd_move_max",
        "n_seeds_free",
        "n_seeds_chain",
        "n_seeds_mirror",
        "n_seeds_boundary",
        "boundary_seeds_added",
        "origin_x",
        "origin_y",
    ):
        assert key in extras, key
    assert (extras["origin_x"], extras["origin_y"]) == local_frame(request.domain).origin
    assert cell_mesh.qa.size_fidelity["p50"] == pytest.approx(1.0, abs=0.1)
    assert _platform_note() in cell_mesh.qa.notes
