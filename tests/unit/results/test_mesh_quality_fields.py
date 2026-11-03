"""The mesh quality fields are rebuilt on read from the stored mesh, never stored.

A hand-built grid of 2 rows and 3 columns of widths 10, 20 and 80 m (rows 10 m high)
gives the values by arithmetic, and an L-shaped cell beside a square gives a reflex
corner. A Voronoi dual of a committed bundle checks the per-cell values against the
quantile QA the engine measured on the same mesh.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from flopy.discretization import StructuredGrid

from hydromodpy.results.derive.mesh_quality import (
    MESH_QUALITY_DESCRIPTORS,
    mesh_quality_unavailable_reason,
    mesh_quality_values,
)
from hydromodpy.results.derive.virtual_fields import (
    available_virtual_fields,
    derive_field_slice,
    derive_field_stack,
    field_descriptor,
)
from hydromodpy.results.zarr_store import SimulationZarr
from hydromodpy.results.zarr_store.mesh_layout import mesh_layout_from_cell_mesh
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.spatial.mesh.model.planar_cell_mesh import (
    MeshIdentity,
    PlanarCellMesh,
    build_planar_cell_mesh,
)
from tests._helpers.bundle_cell_meshes import bundle_dual
from tests._helpers.cell_meshes import TEST_CRS_WKT
from tests._helpers.regular_cell_meshes import from_flopy_structured

WIDTHS = (10.0, 20.0, 80.0)
HEIGHT = 10.0
NAMES = tuple(MESH_QUALITY_DESCRIPTORS)
DECLARATIONS = {"graded": False, "exact_faces": False, "deterministic": True, "needs_cache": False}


def _grid(shift_first_centre: tuple[float, float] = (0.0, 0.0)) -> PlanarCellMesh:
    """The 2 x 3 grid, origin (0, 0), centres at the middle of each cell but the first."""
    grid = StructuredGrid(delc=np.full(2, HEIGHT), delr=np.array(WIDTHS), xoff=0.0, yoff=0.0)
    edges = np.concatenate([[0.0], np.cumsum(WIDTHS)])
    xs = 0.5 * (edges[:-1] + edges[1:])
    ys = np.array([15.0, 5.0])
    xx, yy = np.meshgrid(xs, ys, indexing="xy")
    centres = np.column_stack([xx.ravel(), yy.ravel()])
    centres[0] += shift_first_centre
    return build_planar_cell_mesh(
        from_flopy_structured(grid),
        centres,
        center_kind="cell_center",
        crs_wkt=TEST_CRS_WKT,
        identity=MeshIdentity("regular", "0", "", None),
        declarations=DECLARATIONS,
        structured_shape=(2, 3),
    )


def _store(
    path: Path, cell_mesh: PlanarCellMesh, *, layout: bool = True, qa: dict | None = None
) -> SimulationZarr:
    xy = np.asarray(cell_mesh.mesh.vertices, dtype=float)
    store = SimulationZarr.create(path, n_cells=cell_mesh.n_cells, n_layers=1)
    store.write_mesh(
        np.column_stack([xy, np.zeros(xy.shape[0])]),
        cell_mesh.connectivity_rows,
        np.array([0.0, -10.0]),
        layout=mesh_layout_from_cell_mesh(cell_mesh, qa=qa) if layout else None,
    )
    return store


def test_the_area_and_the_neighbour_ratio_follow_the_widths(tmp_path):
    store = _store(tmp_path / "fields.zarr", _grid())

    area = mesh_quality_values(store.root, "mesh_cell_area")
    ratio = mesh_quality_values(store.root, "mesh_neighbour_ratio")

    np.testing.assert_allclose(area, [100.0, 200.0, 800.0, 100.0, 200.0, 800.0], rtol=1e-12)
    # sqrt(200/100), sqrt(800/200) = 2, and 1 between the two rows.
    np.testing.assert_allclose(ratio, [math.sqrt(2), 2.0, 2.0] * 2, rtol=1e-12)
    store.close()


def test_a_centre_off_its_centroid_shows_in_the_offset_and_the_angles(tmp_path):
    store = _store(tmp_path / "fields.zarr", _grid(shift_first_centre=(3.0, 4.0)))

    offset = mesh_quality_values(store.root, "mesh_center_offset")
    angle = mesh_quality_values(store.root, "mesh_nonorthogonality")

    # The first centre moved by (3, 4) m in a cell of side 10 m.
    np.testing.assert_allclose(offset, [0.5, 0, 0, 0, 0, 0], atol=1e-12)
    # Cell 0 sits at (8, 19): the joint to cell 1 is (12, -4) across a vertical face,
    # the joint to cell 3 is (-3, -14) across a horizontal one.
    across_columns = math.degrees(math.atan2(4.0, 12.0))
    across_rows = math.degrees(math.atan2(3.0, 14.0))
    np.testing.assert_allclose(
        angle, [across_columns, across_columns, 0.0, across_rows, 0.0, 0.0], atol=1e-9
    )
    store.close()


def test_a_centre_off_its_centroid_moves_the_crossing_off_the_face_middle(tmp_path):
    store = _store(tmp_path / "fields.zarr", _grid(shift_first_centre=(3.0, 4.0)))

    offset = mesh_quality_values(store.root, "mesh_bisection_offset")

    # From (8, 19) to (20, 15) the line meets x = 10 at y = 19 - 4/6, on a face
    # centred on y = 15: (4 - 4/6) / 10 = 1/3. From (8, 19) to (5, 5) it meets
    # y = 10 at x = 8 - 3 * 9/14, on a face centred on x = 5: 3/28.
    np.testing.assert_allclose(offset, [1 / 3, 1 / 3, 0.0, 3 / 28, 0.0, 0.0], atol=1e-12)
    store.close()


def test_the_cells_of_a_grid_have_right_angles_and_no_concavity(tmp_path):
    store = _store(tmp_path / "fields.zarr", _grid())

    np.testing.assert_allclose(mesh_quality_values(store.root, "mesh_min_angle"), 90.0)
    np.testing.assert_allclose(mesh_quality_values(store.root, "mesh_max_angle"), 90.0)
    np.testing.assert_array_equal(mesh_quality_values(store.root, "mesh_concavity"), 0.0)
    store.close()


def test_an_l_shaped_cell_has_a_reflex_corner_of_270_degrees(tmp_path):
    corners = np.array(
        [[0, 0], [2, 0], [2, 1], [1, 1], [1, 2], [0, 2], [2, 2]], dtype=float
    ) * 10.0 + [350_000.0, 6_780_000.0]
    cells = (np.array([0, 1, 2, 3, 4, 5]), np.array([3, 2, 6, 4]))
    mesh = HydroMesh(vertices=corners, cell_blocks=(CellBlock(CellType.POLYGON, cells),))
    l_and_square = build_planar_cell_mesh(
        mesh,
        np.array([[350_005.0, 6_780_005.0], [350_015.0, 6_780_015.0]]),
        center_kind="cell_center",
        crs_wkt=TEST_CRS_WKT,
        identity=MeshIdentity("voronoi", "0", "", None),
        declarations=DECLARATIONS,
    )
    store = _store(tmp_path / "fields.zarr", l_and_square)

    np.testing.assert_allclose(mesh_quality_values(store.root, "mesh_concavity"), [90.0, 0.0])
    np.testing.assert_allclose(mesh_quality_values(store.root, "mesh_min_angle"), [90.0, 90.0])
    np.testing.assert_allclose(mesh_quality_values(store.root, "mesh_max_angle"), [270.0, 90.0])
    store.close()


def test_a_face_shorter_than_the_qa_threshold_is_left_out_of_the_angles(tmp_path):
    cell_mesh = _grid(shift_first_centre=(3.0, 4.0))
    store = _store(tmp_path / "fields.zarr", cell_mesh, qa={"min_face_length_m": 15.0})

    angle = mesh_quality_values(store.root, "mesh_nonorthogonality")

    # Only the faces of 20 and 80 m remain: the two between rows, in columns 1 and 2.
    np.testing.assert_allclose(angle, [np.nan, 0.0, 0.0, np.nan, 0.0, 0.0], atol=1e-12)
    store.close()


def test_a_cell_with_no_neighbour_has_no_ratio_and_no_angle(tmp_path):
    grid = StructuredGrid(delc=np.array([10.0]), delr=np.array([10.0]), xoff=0.0, yoff=0.0)
    single = build_planar_cell_mesh(
        from_flopy_structured(grid),
        np.array([[5.0, 5.0]]),
        center_kind="cell_center",
        crs_wkt=TEST_CRS_WKT,
        identity=MeshIdentity("regular", "0", "", None),
        declarations=DECLARATIONS,
    )
    store = _store(tmp_path / "fields.zarr", single)

    assert np.isnan(mesh_quality_values(store.root, "mesh_neighbour_ratio")).all()
    assert np.isnan(mesh_quality_values(store.root, "mesh_nonorthogonality")).all()
    assert mesh_quality_values(store.root, "mesh_cell_area").tolist() == [100.0]
    store.close()


def test_a_store_without_cell_centres_serves_the_geometry_fields_only(tmp_path):
    store = _store(tmp_path / "fields.zarr", _grid(), layout=False)

    assert available_virtual_fields(store.root) == [
        "mesh_cell_area",
        "mesh_concavity",
        "mesh_max_angle",
        "mesh_min_angle",
        "mesh_neighbour_ratio",
    ]
    assert mesh_quality_unavailable_reason(store.root, "mesh_cell_area") is None
    assert mesh_quality_unavailable_reason(store.root, "mesh_bisection_offset") is not None
    reason = mesh_quality_unavailable_reason(store.root, "mesh_center_offset")
    assert reason is not None
    assert "no cell centres" in reason
    with pytest.raises(KeyError, match="mesh_nonorthogonality is not available.*cell centres"):
        mesh_quality_values(store.root, "mesh_nonorthogonality")
    store.close()


def test_a_store_without_a_mesh_serves_none_of_them(tmp_path):
    store = SimulationZarr.create(tmp_path / "fields.zarr", n_cells=6, n_layers=1)

    assert available_virtual_fields(store.root) == []
    assert mesh_quality_unavailable_reason(store.root, "mesh_cell_area") == (
        "the run stored no mesh geometry"
    )
    store.close()


def test_the_fields_are_static_and_read_whatever_the_step(tmp_path):
    store = _store(tmp_path / "fields.zarr", _grid(shift_first_centre=(3.0, 4.0)))

    once = derive_field_slice(store, "sim", "mesh_center_offset", 0)
    later = derive_field_slice(store, "sim", "mesh_center_offset", 7)
    stack = derive_field_stack(store, "sim", "mesh_center_offset", [0, 3, 5])

    np.testing.assert_array_equal(once, later)
    assert stack.shape == (3, 6)
    np.testing.assert_array_equal(stack[2], once)
    descriptor = field_descriptor("mesh_nonorthogonality")
    assert (descriptor.shape, descriptor.units) == ("face", "degree")
    store.close()


def test_the_per_cell_extremes_of_a_voronoi_dual_are_the_qa_extremes(tmp_path):
    cell_mesh = bundle_dual("stream_depletion_glover_balmer_tri_refined_well")
    qa = cell_mesh.qa
    store = _store(tmp_path / "fields.zarr", cell_mesh, qa=qa.as_dict())

    area = mesh_quality_values(store.root, "mesh_cell_area")
    ratio = mesh_quality_values(store.root, "mesh_neighbour_ratio")
    offset = mesh_quality_values(store.root, "mesh_center_offset")
    angle = mesh_quality_values(store.root, "mesh_nonorthogonality")
    bisection = mesh_quality_values(store.root, "mesh_bisection_offset")
    smallest = mesh_quality_values(store.root, "mesh_min_angle")
    largest = mesh_quality_values(store.root, "mesh_max_angle")
    concavity = mesh_quality_values(store.root, "mesh_concavity")

    assert area.shape == ratio.shape == offset.shape == angle.shape == (cell_mesh.n_cells,)
    assert bisection.shape == smallest.shape == concavity.shape == (cell_mesh.n_cells,)
    assert np.nanmin(bisection) >= 0.0
    assert ((smallest > 0.0) & (smallest < 180.0)).all()
    assert (concavity >= 0.0).all()
    assert (largest >= smallest).all()
    np.testing.assert_allclose(area, cell_mesh.geometry.areas, rtol=1e-12)
    assert np.nanmax(ratio) == pytest.approx(qa.neighbour_ratio["max"], rel=1e-12)
    assert np.nanmax(offset) == pytest.approx(qa.center_offset["max"], rel=1e-12)
    assert np.nanmax(angle) == pytest.approx(qa.nonorthogonality_deg["max"], rel=1e-9)
    assert area.min() == pytest.approx(qa.area_quantiles_m2["min"], rel=1e-12)
    assert np.nanmax(bisection) == pytest.approx(qa.bisection_offset["max"], rel=1e-12)
    assert smallest.min() == pytest.approx(qa.min_angle_deg["min"], rel=1e-12)
    assert largest.max() == pytest.approx(qa.max_angle_deg["max"], rel=1e-12)
    assert np.count_nonzero(concavity > 0.0) == qa.n_concave_cells
    store.close()
