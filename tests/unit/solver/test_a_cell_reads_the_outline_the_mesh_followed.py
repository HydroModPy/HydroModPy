"""A cell is read against the catchment outline its mesh followed.

The planner smooths the pixel staircase of the delineated catchment before it
meshes (``catchment_outline.py``), and the faces of the mesh follow that smooth
outline. The fallback support ``polygon_covers`` of a discharge objective, the
catchment fraction of the build and the network criterion used to read the
staircase of ``watershed.shp``: a cell of the band between the two outlines
counted on the wrong side of the catchment its faces bound. They all go through
``catchment_outline``, which now answers with the outline the mesh followed
when the mesh carries one, and with the delineated polygon otherwise.
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pytest
import shapely
from pyproj import CRS
from rasterio.features import shapes
from rasterio.transform import Affine
from shapely.geometry import Polygon, shape

from hydromodpy.calibration.observations.observed_network import delineated_catchment_mask
from hydromodpy.solver.modflow_common.catchment_basin import (
    catchment_cell_mask,
    polygon_cell_fraction,
    polygon_cell_mask,
)
from hydromodpy.spatial.geographic.delineated_catchment import catchment_outline
from hydromodpy.spatial.geographic.synthetic_config import SYNTHETIC_CATCH_DEF
from hydromodpy.spatial.mesh.model.geometry import cell_polygons
from hydromodpy.spatial.mesh.planning.catchment_outline import smooth_polygon
from tests._helpers.mesh_cases import LAMBERT93_WKT
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

PIXEL = 10.0
NPIX = 20
CELL = 2.0


def _staircase() -> Polygon:
    """An elliptic catchment as a delineation draws it: the polygon of a pixel mask."""
    rows, cols = np.mgrid[0:NPIX, 0:NPIX]
    x = (cols + 0.5) * PIXEL - 0.5 * NPIX * PIXEL
    y = (NPIX - rows - 0.5) * PIXEL - 0.5 * NPIX * PIXEL
    mask = np.hypot(x, 0.8 * y) < 0.35 * NPIX * PIXEL
    transform = Affine(PIXEL, 0.0, 0.0, 0.0, -PIXEL, NPIX * PIXEL)
    parts = [
        shape(geometry)
        for geometry, value in shapes(
            mask.astype("uint8"), mask=mask, transform=transform, connectivity=4
        )
        if value == 1
    ]
    return max(parts, key=lambda part: part.area)


STAIR = _staircase()
SMOOTH = smooth_polygon(STAIR, PIXEL)


def _mesh(*, followed: bool):
    """The cells of 2 m over the 200 m square, carrying the smooth outline or not.

    The grid is shifted off the meter so that no cell center lies on a diagonal of the smooth outline.
    """
    n = int(NPIX * PIXEL / CELL)
    mesh = solver_mesh_from_structured_arrays(
        nrow=n,
        ncol=n,
        top=np.full((n, n), 10.0),
        botm=np.zeros((1, n, n)),
        dx=CELL,
        dy=CELL,
        xoff=0.37,
        yoff=0.21,
    )
    cell_mesh = replace(mesh.cell_mesh, crs_wkt=LAMBERT93_WKT)
    if followed:
        cell_mesh = cell_mesh.with_smoothed_catchment(SMOOTH)
    return replace(mesh, cell_mesh=cell_mesh)


def _geographic(tmp_path):
    shp = tmp_path / "watershed.gpkg"
    gpd.GeoDataFrame(geometry=[STAIR], crs=LAMBERT93_WKT).to_file(shp)
    return SimpleNamespace(watershed_shp=str(shp), crs_project=LAMBERT93_WKT)


def _inside(polygon, mesh) -> np.ndarray:
    return shapely.covers(polygon, shapely.points(mesh.cell_centers()))


def _share(polygon, mesh) -> np.ndarray:
    cells = cell_polygons(
        np.asarray(mesh.planar_mesh.vertices, dtype=float),
        mesh.cell_mesh.geometry.padded_connectivity,
    )
    return shapely.area(shapely.intersection(cells, polygon)) / shapely.area(cells)


def test_the_two_outlines_put_some_cells_on_different_sides() -> None:
    mesh = _mesh(followed=False)

    assert (_inside(STAIR, mesh) != _inside(SMOOTH, mesh)).sum() > 20


def test_the_outline_answered_is_the_smooth_one_when_the_mesh_followed_it(tmp_path) -> None:
    geographic = _geographic(tmp_path)

    frame = catchment_outline(geographic, _mesh(followed=True).cell_mesh)

    assert frame.geometry.iloc[0].equals(SMOOTH)
    assert CRS.from_user_input(frame.crs).equals(CRS.from_user_input(LAMBERT93_WKT))


def test_the_outline_answered_is_the_delineated_one_otherwise(tmp_path) -> None:
    geographic = _geographic(tmp_path)

    for cell_mesh in (None, _mesh(followed=False).cell_mesh):
        frame = catchment_outline(geographic, cell_mesh)
        assert frame.geometry.iloc[0].equals(STAIR)
    assert catchment_outline(geographic).geometry.iloc[0].equals(STAIR)


def test_a_synthetic_geographic_has_no_outline_even_beside_a_mesh_that_carries_one() -> None:
    geographic = SimpleNamespace(catch_def=SYNTHETIC_CATCH_DEF, watershed_shp="box.shp")

    assert catchment_outline(geographic, _mesh(followed=True).cell_mesh) is None


def test_the_fallback_support_sums_the_cells_inside_the_smooth_outline(tmp_path) -> None:
    mesh = _mesh(followed=True)
    model = SimpleNamespace(
        model_name="m", descent_basin=None, geographic=_geographic(tmp_path), solver_mesh=mesh
    )

    mask = catchment_cell_mask(model)

    np.testing.assert_array_equal(mask, _inside(SMOOTH, mesh))
    assert (mask != _inside(STAIR, mesh)).any()


def test_the_fallback_support_keeps_the_staircase_for_a_mesh_that_did_not_follow_it(
    tmp_path,
) -> None:
    mesh = _mesh(followed=False)
    model = SimpleNamespace(
        model_name="m", descent_basin=None, geographic=_geographic(tmp_path), solver_mesh=mesh
    )

    np.testing.assert_array_equal(catchment_cell_mask(model), _inside(STAIR, mesh))


def test_the_polygon_mask_of_the_build_reads_the_same_outline(tmp_path) -> None:
    mesh = _mesh(followed=True)

    mask = polygon_cell_mask(_geographic(tmp_path), mesh)

    np.testing.assert_array_equal(mask, _inside(SMOOTH, mesh))


def test_the_catchment_fraction_is_taken_on_the_smooth_outline(tmp_path) -> None:
    mesh = _mesh(followed=True)

    fraction = polygon_cell_fraction(_geographic(tmp_path), mesh)

    np.testing.assert_allclose(fraction, _share(SMOOTH, mesh), atol=1.0e-9)
    assert np.abs(fraction - _share(STAIR, mesh)).max() > 0.2


def test_the_catchment_fraction_of_an_unsmoothed_mesh_is_the_staircase_share(tmp_path) -> None:
    mesh = _mesh(followed=False)

    fraction = polygon_cell_fraction(_geographic(tmp_path), mesh)

    np.testing.assert_allclose(fraction, _share(STAIR, mesh), atol=1.0e-9)


@pytest.mark.parametrize("followed", [True, False])
def test_the_network_criterion_reads_the_outline_the_mesh_followed(tmp_path, followed) -> None:
    mesh = _mesh(followed=followed)
    setup = SimpleNamespace(geographic=_geographic(tmp_path), cell_mesh=mesh.cell_mesh)
    run_ctx = SimpleNamespace(
        model=SimpleNamespace(descent_basin=None), state=SimpleNamespace(setup=setup)
    )

    mask = delineated_catchment_mask(
        run_ctx, mesh.planar_mesh, mesh.cell_mesh.geometry.padded_connectivity
    )

    np.testing.assert_array_equal(mask, _inside(SMOOTH if followed else STAIR, mesh))
