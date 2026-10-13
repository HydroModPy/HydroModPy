"""The regular engine reproduces the flopy grid bit for bit and rasterizes its lines."""

from __future__ import annotations

import flopy
import numpy as np
import pytest
import shapely
from pyproj import CRS
from shapely.geometry import LineString, box

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.spatial.mesh.adapters.flopy_adapter import from_flopy_structured
from hydromodpy.spatial.mesh.engines.regular.engine import RegularMeshEngine
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.grid_wrappers import RegularGrid
from hydromodpy.spatial.mesh.request import (
    InputTriangulation,
    LineFamilySpec,
    MeshRequest,
    RasterGridSpec,
    SizeField,
)
from hydromodpy.spatial.raster_support import RasterSupport
from hydromodpy.spatial.surface import Surface

WKT = CRS.from_epsg(2154).to_wkt()


def _request(
    xmin: float,
    xmax: float,
    ymin: float,
    ymax: float,
    nrow: int,
    ncol: int,
    *,
    size: float | None = None,
    lines: tuple[LineFamilySpec, ...] = (),
    options: dict | None = None,
    native_pitch: bool = True,
) -> MeshRequest:
    dx = (xmax - xmin) / ncol
    dy = (ymax - ymin) / nrow
    grid = RasterGridSpec(
        xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax, dx=dx, dy=dy, nrow=nrow, ncol=ncol, crs_wkt=WKT
    )
    return MeshRequest(
        domain=box(xmin, ymin, xmax, ymax),
        crs_wkt=WKT,
        grid=grid,
        nominal_size_m=dx if size is None else size,
        lines=lines,
        options=options or {},
    )


GRIDS = {
    "lambert_75m": (346512.5, 349887.5, 6789012.25, 6791987.25, 119, 135),
    "odd_pitch_negative_origin": (
        -123.456,
        -123.456 + 41 * 24.4,
        -987.321,
        -987.321 + 37 * 24.4,
        37,
        41,
    ),
    "band_1x40": (0.0, 4000.0, 0.0, 100.0, 1, 40),
    "square": (0.0, 1000.0, 0.0, 1000.0, 40, 40),
}


@pytest.mark.parametrize("name", sorted(GRIDS))
def test_the_vertices_equal_the_flopy_structured_grid_to_the_bit(name) -> None:
    xmin, xmax, ymin, ymax, nrow, ncol = GRIDS[name]
    cell_mesh = RegularMeshEngine().build(_request(xmin, xmax, ymin, ymax, nrow, ncol))
    dx = (xmax - xmin) / ncol
    dy = (ymax - ymin) / nrow
    reference = flopy.discretization.StructuredGrid(
        delc=np.full(nrow, dy), delr=np.full(ncol, dx), xoff=xmin, yoff=ymin
    )
    legacy = from_flopy_structured(reference)

    np.testing.assert_array_equal(cell_mesh.mesh.vertices[:, 0], reference.xvertices.reshape(-1))
    np.testing.assert_array_equal(cell_mesh.mesh.vertices[:, 1], reference.yvertices.reshape(-1))
    np.testing.assert_array_equal(cell_mesh.mesh.flat_connectivity, legacy.flat_connectivity)
    assert cell_mesh.structured_shape == (nrow, ncol)


@pytest.mark.parametrize("name", sorted(GRIDS))
def test_the_centers_equal_the_vertex_mean_the_solvers_read(name) -> None:
    xmin, xmax, ymin, ymax, nrow, ncol = GRIDS[name]
    cell_mesh = RegularMeshEngine().build(_request(xmin, xmax, ymin, ymax, nrow, ncol))
    x, y = cell_mesh.mesh.cell_centroids()

    np.testing.assert_array_equal(cell_mesh.centers[:, 0], x)
    np.testing.assert_array_equal(cell_mesh.centers[:, 1], y)
    assert cell_mesh.center_kind == "cell_center"


def test_the_quads_are_the_ones_of_the_regular_grid_wrapper() -> None:
    cell_mesh = RegularMeshEngine().build(_request(0.0, 1000.0, 0.0, 500.0, 5, 10))
    wrapper = RegularGrid(shape=(5, 10), dx=100.0, dy=100.0, origin=(0.0, 500.0)).to_hydro_mesh()

    np.testing.assert_array_equal(cell_mesh.mesh.vertices, wrapper.vertices)
    np.testing.assert_array_equal(cell_mesh.mesh.flat_connectivity, wrapper.flat_connectivity)
    assert cell_mesh.mesh.cell_types == (CellType.QUADRILATERAL,)


# --------------------------------------------------------------------------- #
# Shape and pitch
# --------------------------------------------------------------------------- #


def test_the_native_pitch_is_the_dem_pitch() -> None:
    request = _request(0.0, 1000.0, 0.0, 600.0, 12, 20)
    cell_mesh = RegularMeshEngine().build(request)

    assert cell_mesh.structured_shape == (12, 20)
    # The side heads sit half a cell inside, and the only note is the one that says so.
    assert cell_mesh.qa.extras == {"dx_m": 50.0, "dy_m": 50.0, "side_center_offset_m_p50": 25.0}
    assert len(cell_mesh.qa.notes) == 1
    assert "half a cell inside the domain" in cell_mesh.qa.notes[0]


def test_a_coarser_size_rounds_the_shape_and_spans_the_dem_bounds() -> None:
    request = _request(0.0, 1000.0, 0.0, 600.0, 12, 20, size=130.0)
    cell_mesh = RegularMeshEngine().build(request)

    assert cell_mesh.structured_shape == (5, 8)
    assert cell_mesh.qa.extras["dx_m"] == 1000.0 / 8
    assert cell_mesh.qa.extras["dy_m"] == 600.0 / 5
    assert cell_mesh.mesh.bounds() == (0.0, 0.0, 1000.0, 600.0)
    assert any("resamples" in note for note in cell_mesh.qa.notes)


def test_the_shape_option_fixes_the_shape() -> None:
    request = _request(0.0, 1000.0, 0.0, 600.0, 12, 20, options={"shape": [3, 7]})
    cell_mesh = RegularMeshEngine().build(request)

    assert cell_mesh.structured_shape == (3, 7)
    assert cell_mesh.qa.extras["dx_m"] == 1000.0 / 7


@pytest.mark.parametrize("options", [{}, {"shape": [37, 41]}])
def test_the_dem_shape_keeps_the_dem_pitch_of_pixels_that_are_not_square(options) -> None:
    nrow, ncol, dx, dy = 37, 41, 25.00000003, 24.994117
    xmin, ymin = 346512.5, 6789012.25
    grid = RasterGridSpec(
        xmin=xmin,
        xmax=xmin + ncol * dx,
        ymin=ymin,
        ymax=ymin + nrow * dy,
        dx=dx,
        dy=dy,
        nrow=nrow,
        ncol=ncol,
        crs_wkt=WKT,
    )
    request = MeshRequest(
        domain=box(grid.xmin, grid.ymin, grid.xmax, grid.ymax),
        crs_wkt=WKT,
        grid=grid,
        nominal_size_m=max(dx, dy),
        options=options,
    )
    cell_mesh = RegularMeshEngine().build(request)
    reference = flopy.discretization.StructuredGrid(
        delc=np.full(nrow, dy), delr=np.full(ncol, dx), xoff=xmin, yoff=ymin
    )

    assert cell_mesh.structured_shape == (nrow, ncol)
    np.testing.assert_array_equal(cell_mesh.mesh.vertices[:, 0], reference.xvertices.reshape(-1))
    np.testing.assert_array_equal(cell_mesh.mesh.vertices[:, 1], reference.yvertices.reshape(-1))
    assert not any("resamples" in note for note in cell_mesh.qa.notes)


def test_the_resampled_pitch_is_the_one_of_surface_resample_to_shape() -> None:
    xmin, xmax, ymin, ymax, nrow, ncol = GRIDS["odd_pitch_negative_origin"]
    support = RasterSupport(
        crs="EPSG:2154",
        dx=(xmax - xmin) / ncol,
        dy=(ymax - ymin) / nrow,
        xmin=xmin,
        xmax=xmax,
        ymin=ymin,
        ymax=ymax,
        nrows=nrow,
        ncols=ncol,
        nodata=-9999.0,
    )
    surface = Surface("top", np.zeros((nrow, ncol)), support)
    resampled = surface.resample_to_shape(10, 12, resampling="bilinear")
    grid = RasterGridSpec.from_raster_support(support, crs_wkt=WKT)
    request = MeshRequest(
        domain=box(xmin, ymin, xmax, ymax),
        crs_wkt=WKT,
        grid=grid,
        nominal_size_m=grid.dx,
        options={"shape": [10, 12]},
    )
    cell_mesh = RegularMeshEngine().build(request)

    assert cell_mesh.qa.extras["dx_m"] == resampled.support.dx
    assert cell_mesh.qa.extras["dy_m"] == resampled.support.dy


def test_a_size_finer_than_the_dem_is_refused() -> None:
    request = _request(0.0, 1000.0, 0.0, 600.0, 12, 20, size=25.0)

    with pytest.raises(MeshRequestError, match="finer than the DEM"):
        RegularMeshEngine().build(request)


@pytest.mark.parametrize("shape", [[3], [3, 0], [3.5, 4], "33", [True, 4]])
def test_a_malformed_shape_is_refused(shape) -> None:
    request = _request(0.0, 1000.0, 0.0, 600.0, 12, 20, options={"shape": shape})

    with pytest.raises(MeshRequestError, match="shape"):
        RegularMeshEngine().build(request)


def test_an_option_the_engine_does_not_read_is_refused() -> None:
    request = _request(0.0, 1000.0, 0.0, 600.0, 12, 20, options={"algorithm": "frontal"})

    with pytest.raises(MeshRequestError, match="algorithm"):
        RegularMeshEngine().build(request)


def test_an_input_triangulation_is_refused() -> None:
    request = _request(0.0, 1000.0, 0.0, 600.0, 12, 20)
    triangulation = InputTriangulation(
        np.array([[0.0, 0.0], [1000.0, 0.0], [0.0, 600.0]]), np.array([[0, 1, 2]]), {}
    )
    with_mesh = MeshRequest(
        domain=request.domain,
        crs_wkt=WKT,
        grid=request.grid,
        nominal_size_m=50.0,
        input_triangulation=triangulation,
    )

    with pytest.raises(MeshRequestError, match="triangulation"):
        RegularMeshEngine().build(with_mesh)


def test_the_size_field_is_ignored_and_the_quality_report_says_so() -> None:
    request = _request(0.0, 1000.0, 0.0, 600.0, 12, 20)
    field = SizeField(np.full((12, 20), 80.0), request.grid)
    with_field = MeshRequest(
        domain=request.domain,
        crs_wkt=WKT,
        grid=request.grid,
        nominal_size_m=50.0,
        size_field=field,
    )

    plain = RegularMeshEngine().build(request)
    graded = RegularMeshEngine().build(with_field)

    np.testing.assert_array_equal(plain.mesh.vertices, graded.mesh.vertices)
    assert "regular ignores the size field" in graded.qa.notes


def test_the_identity_names_the_engine_and_the_request() -> None:
    request = _request(0.0, 1000.0, 0.0, 600.0, 12, 20)
    identity = RegularMeshEngine().build(request).identity

    assert (identity.engine_id, identity.engine_version) == ("regular", "1.0.0")
    assert identity.request_hash == request.canonical_hash()
    assert identity.seed is None


# --------------------------------------------------------------------------- #
# Families
# --------------------------------------------------------------------------- #


def test_the_sides_are_boundary_families_with_the_faces_of_the_edge_cells() -> None:
    cell_mesh = RegularMeshEngine().build(_request(0.0, 1000.0, 0.0, 600.0, 3, 5))
    table = cell_mesh.face_families
    ncol = 5

    west = cell_mesh.face_rows("boundary:west")
    east = cell_mesh.face_rows("boundary:east")
    north = cell_mesh.face_rows("boundary:north")
    south = cell_mesh.face_rows("boundary:south")
    assert sorted(table.cell_a[west]) == [0, ncol, 2 * ncol]
    assert sorted(table.cell_a[east]) == [ncol - 1, 2 * ncol - 1, 3 * ncol - 1]
    assert sorted(table.cell_a[north]) == list(range(ncol))
    assert sorted(table.cell_a[south]) == list(range(2 * ncol, 3 * ncol))
    assert np.all(table.cell_b[west | east | north | south] == -1)


def test_a_band_of_one_row_has_both_long_sides() -> None:
    cell_mesh = RegularMeshEngine().build(_request(*GRIDS["band_1x40"]))

    assert cell_mesh.face_rows("boundary:north").sum() == 40
    assert cell_mesh.face_rows("boundary:south").sum() == 40
    assert cell_mesh.face_rows("boundary:west").sum() == 1
    assert cell_mesh.face_rows("boundary:east").sum() == 1


def _river(*points: tuple[float, float]) -> LineFamilySpec:
    return LineFamilySpec("rivers", "cell", (LineString(points),))


def test_a_river_along_a_row_is_the_chain_of_that_row_in_line_order() -> None:
    request = _request(
        0.0, 1000.0, 0.0, 1000.0, 10, 10, lines=(_river((5.0, 450.0), (995.0, 450.0)),)
    )
    cell_mesh = RegularMeshEngine().build(request)
    (chain,) = cell_mesh.chains("rivers")

    assert chain.cell_ids.tolist() == list(range(50, 60))


def test_the_chain_follows_the_orientation_of_the_line() -> None:
    forward = _river((5.0, 450.0), (995.0, 450.0))
    backward = _river((995.0, 450.0), (5.0, 450.0))
    first = RegularMeshEngine().build(_request(0.0, 1000.0, 0.0, 1000.0, 10, 10, lines=(forward,)))
    second = RegularMeshEngine().build(
        _request(0.0, 1000.0, 0.0, 1000.0, 10, 10, lines=(backward,))
    )

    assert (
        second.chains("rivers")[0].cell_ids.tolist()
        == first.chains("rivers")[0].cell_ids.tolist()[::-1]
    )


def test_a_diagonal_river_is_a_continuous_chain_without_break() -> None:
    request = _request(
        0.0, 1000.0, 0.0, 1000.0, 20, 20, lines=(_river((10.0, 990.0), (990.0, 10.0)),)
    )
    cell_mesh = RegularMeshEngine().build(request)
    (chain,) = cell_mesh.chains("rivers")

    assert cell_mesh.qa.families["rivers"]["breaks"] == 0.0
    assert chain.cell_ids[0] == 0
    assert chain.cell_ids[-1] == 399


def test_each_line_of_a_river_family_is_one_chain_and_a_line_off_the_grid_gives_none() -> None:
    lines = LineFamilySpec(
        "rivers",
        "cell",
        (
            LineString([(5.0, 450.0), (500.0, 450.0)]),
            LineString([(500.0, 450.0), (995.0, 450.0)]),
            LineString([(5000.0, 5000.0), (6000.0, 5000.0)]),
        ),
    )
    cell_mesh = RegularMeshEngine().build(
        _request(0.0, 1000.0, 0.0, 1000.0, 10, 10, lines=(lines,))
    )

    assert [chain.chain_id for chain in cell_mesh.chains("rivers")] == [0, 1]


def test_a_river_far_from_the_grid_origin_is_found_in_its_window() -> None:
    request = _request(
        346512.5,
        349887.5,
        6789012.25,
        6791987.25,
        119,
        135,
        lines=(_river((347000.0, 6790000.0), (348500.0, 6790900.0)),),
    )
    cell_mesh = RegularMeshEngine().build(request)
    (chain,) = cell_mesh.chains("rivers")
    inside = shapely.points(cell_mesh.centers[chain.cell_ids])

    line = request.lines[0].lines[0]
    assert shapely.distance(inside, line).max() <= 75.0
    assert cell_mesh.qa.families["rivers"]["breaks"] == 0.0


def _contact(zones: bool = True, *, reverse: bool = False) -> LineFamilySpec:
    points = [(500.0, 0.0), (500.0, 1000.0)]
    if reverse:
        points.reverse()
    left, right = ("east_unit", "west_unit") if reverse else ("west_unit", "east_unit")
    return LineFamilySpec(
        "geology",
        "face",
        (LineString(points),),
        zone_left=(left,) if zones else (),
        zone_right=(right,) if zones else (),
    )


def test_a_contact_on_cell_faces_is_followed_exactly() -> None:
    request = _request(0.0, 1000.0, 0.0, 1000.0, 10, 10, lines=(_contact(),))
    cell_mesh = RegularMeshEngine().build(request)
    quality = cell_mesh.qa.families["geology"]

    assert cell_mesh.face_rows("geology").sum() == 10
    assert quality["hausdorff_m"] == pytest.approx(0.0, abs=1e-9)
    assert quality["covered_length_rel"] == pytest.approx(1.0)


def test_a_face_row_puts_the_cell_on_the_left_of_the_line_first() -> None:
    request = _request(0.0, 1000.0, 0.0, 1000.0, 10, 10, lines=(_contact(),))
    cell_mesh = RegularMeshEngine().build(request)
    table = cell_mesh.face_families
    rows = cell_mesh.face_rows("geology")

    assert np.all(cell_mesh.centers[table.cell_a[rows], 0] < 500.0)
    assert np.all(cell_mesh.centers[table.cell_b[rows], 0] > 500.0)


def test_reversing_the_line_swaps_the_sides_and_the_zones_follow() -> None:
    request = _request(0.0, 1000.0, 0.0, 1000.0, 10, 10, lines=(_contact(reverse=True),))
    cell_mesh = RegularMeshEngine().build(request)
    table = cell_mesh.face_families
    rows = cell_mesh.face_rows("geology")

    assert np.all(cell_mesh.centers[table.cell_a[rows], 0] > 500.0)
    left = {cell_mesh.zone_names[z] for z in table.zone_left[rows]}
    right = {cell_mesh.zone_names[z] for z in table.zone_right[rows]}
    assert (left, right) == ({"east_unit"}, {"west_unit"})


def test_the_cells_take_the_zone_of_their_side_of_the_contact() -> None:
    request = _request(0.0, 1000.0, 0.0, 1000.0, 10, 10, lines=(_contact(),))
    cell_mesh = RegularMeshEngine().build(request)
    west = cell_mesh.centers[:, 0] < 500.0
    names = np.array(cell_mesh.zone_names)

    assert set(names[cell_mesh.cell_zone[west]]) == {"west_unit"}
    assert set(names[cell_mesh.cell_zone[~west]]) == {"east_unit"}


def test_a_contact_between_faces_becomes_a_staircase_the_report_measures() -> None:
    slanted = LineFamilySpec("geology", "face", (LineString([(0.0, 0.0), (1000.0, 1000.0)]),))
    request = _request(0.0, 1000.0, 0.0, 1000.0, 10, 10, lines=(slanted,))
    cell_mesh = RegularMeshEngine().build(request)
    quality = cell_mesh.qa.families["geology"]

    assert cell_mesh.cell_zone is None
    assert quality["hausdorff_m"] > 0.0
    assert quality["hausdorff_m"] <= 100.0 * np.sqrt(2.0)


def test_a_closed_ring_labels_the_cells_it_holds() -> None:
    ring = shapely.Polygon([(300, 300), (700, 300), (700, 700), (300, 700)]).exterior
    lake = LineFamilySpec("lakes", "face", (LineString(ring.coords),), closed=True)
    request = _request(0.0, 1000.0, 0.0, 1000.0, 10, 10, lines=(lake,))
    cell_mesh = RegularMeshEngine().build(request)

    assert cell_mesh.face_rows("lakes").sum() == 16
    assert cell_mesh.qa.families["lakes"]["hausdorff_m"] == pytest.approx(0.0, abs=1e-9)
