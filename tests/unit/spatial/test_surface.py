"""A surface: elevations on a raster support, shifted, flattened, resampled, reprojected."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.spatial.raster_support import RasterSupport
from hydromodpy.spatial.surface import Surface
from hydromodpy.spatial.surface_sampling import PreparedSurfaceSampler
from tests._helpers.domain_cases import NODATA, raster_support, surface
from tests._helpers.geotiffs import write_geotiff

ROW = np.array([[10.0, 12.0]])


def test_surface_assert_same_geographic_domain_ok_and_raises_on_extent():
    top = surface([[1.0, 2.0], [3.0, 4.0]], name="top", cell=1.0, x0=0.0, y0=0.0)
    bottom = surface([[0.0, 1.0], [2.0, 3.0]], name="bottom", cell=1.0, x0=0.0, y0=0.0)
    moved = surface([[0.0, 1.0], [2.0, 3.0]], name="bottom", cell=1.0, x0=5.0, y0=0.0)

    assert top.assert_same_geographic_domain(bottom) is None
    with pytest.raises(ValueError, match="Domain extent mismatch"):
        top.assert_same_geographic_domain(moved)


def test_surface_resample_to_shape_keeps_domain_and_updates_shape():
    top = surface([[100.0, 101.0], [103.0, 104.0]], cell=10.0, x0=5.0, y0=7.0)

    resampled = top.resample_to_shape(4, 5, resampling="bilinear")

    top.assert_same_geographic_domain(resampled)
    assert resampled.as_array().shape == (4, 5)


def test_shifted_down_by_keeps_the_support_and_names_the_substratum():
    top = Surface(name="surface_topo", values=ROW, support=raster_support(1, 2))

    substratum = top.shifted_down_by(3.5)

    assert substratum.name == "substratum"
    assert substratum.support is top.support
    np.testing.assert_allclose(substratum.as_array(), [[6.5, 8.5]])


def test_flat_like_is_flat_below_the_top_and_refused_above_it():
    top = Surface(name="surface_topo", values=ROW, support=raster_support(1, 2))

    substratum = top.flat_like(2.0)

    assert substratum.support is top.support
    np.testing.assert_allclose(substratum.as_array(), [[2.0, 2.0]])
    with pytest.raises(ValueError, match="no aquifer would remain"):
        top.flat_like(11.0)


def test_flat_like_clamps_nodata_and_outcrop_cells_below_their_own_top():
    """A masked cell carries the sentinel; it is clamped instead of tripping the order guard."""
    top = Surface(
        name="surface_topo", values=np.array([[83.0, NODATA, 56.0]]), support=raster_support(1, 3)
    )

    substratum = top.flat_like(20.0, min_gap=1.0)

    np.testing.assert_allclose(substratum.as_array(), [[20.0, NODATA - 1.0, 20.0]])
    assert bool((substratum.as_array() < top.as_array()).all())


def test_surface_from_geographic_dem_uses_explicit_values_and_support():
    support = RasterSupport(crs="EPSG:2154", dx=25.0, dy=30.0, xmin=0.0, xmax=50.0, ymin=100.0, ymax=125.0, nrows=1, ncols=2)  # fmt: skip

    top = Surface.from_geographic_dem([[1.0, 2.0]], support=support, name="surface_topo")

    assert top.support is support
    np.testing.assert_allclose(top.as_array(), [[1.0, 2.0]])


def test_reprojected_onto_its_own_grid_copies_and_turns_the_sentinel_into_nan():
    values = np.arange(48, dtype=float).reshape(6, 8)
    values[2, 3] = NODATA
    raw = surface(values, name="raw")

    moved = raw.reprojected_onto(raster_support(6, 8)).as_array()

    assert np.isnan(moved[2, 3])
    moved[2, 3] = values[2, 3]
    np.testing.assert_array_equal(moved, values)


# --------------------------------------------------------------------------- #
# The nodata sentinel under a shift, and the refusals of a surface
# --------------------------------------------------------------------------- #

_THICKNESS = 35.0


def test_shifted_down_by_keeps_the_sentinel_in_place():
    """The sentinel must not move.

    The support is shared by reference, so it keeps advertising the same
    ``nodata`` value, and every consumer recognises a no-data cell by exact
    equality with it. Shifting the sentinel down turns it into an ordinary
    elevation: the sampler no longer masks it, bilinear interpolation blends it
    with real terrain, and a mesh cell whose stencil straddles the mask edge
    inherits an aquifer bottom kilometres deep with a clean top and an active
    idomain. The right column is outside the catchment mask.
    """
    top = surface([[100.0, 100.0, NODATA]] * 3, cell=1.0, x0=0.0, y0=0.0)
    bottom = top.shifted_down_by(_THICKNESS)
    values, mask = bottom.as_array(), top.as_array() == NODATA

    assert np.all(values[mask] == NODATA)
    assert not np.any(values == NODATA - _THICKNESS)
    assert np.all(values[~mask] == pytest.approx(100.0 - _THICKNESS))
    assert bottom.support.nodata == NODATA

    # A point whose 2x2 stencil straddles the mask edge is exactly where the bug
    # showed. Both surfaces mask the same pixels, so the thickness is the
    # configured one everywhere a sample is defined at all.
    top_sampler = PreparedSurfaceSampler.from_surface(top)
    bottom_sampler = PreparedSurfaceSampler.from_surface(bottom)
    assert np.isnan(top_sampler.values).sum() == np.isnan(bottom_sampler.values).sum()
    grid_x, grid_y = np.meshgrid(np.linspace(0.05, 2.95, 40), np.linspace(0.05, 2.95, 40))
    thickness = top_sampler.sample(grid_x, grid_y) - bottom_sampler.sample(grid_x, grid_y)
    defined = np.isfinite(thickness)
    assert defined.any()
    np.testing.assert_allclose(thickness[defined], _THICKNESS)


def test_shift_without_a_nodata_declaration_is_a_plain_subtraction():
    top = surface([[10.0, 20.0], [30.0, 40.0]], nodata=None)

    assert top.shifted_down_by(5.0).as_array().ravel().tolist() == [5.0, 15.0, 25.0, 35.0]


def test_a_raster_without_a_crs_is_read_on_the_default_one(tmp_path, caplog):
    path = write_geotiff(tmp_path / "dem.tif", np.ones((2, 3)), cell=5.0, crs=None, nodata=NODATA)

    with caplog.at_level("WARNING"):
        read = Surface.from_raster(path, name="topo", default_crs="EPSG:2154")

    assert "declares no CRS" in caplog.text
    assert read.support.crs == "EPSG:2154"
    assert (read.support.nrows, read.support.ncols, read.support.nodata) == (2, 3, NODATA)
    with pytest.raises(FileNotFoundError):
        Surface.from_raster(tmp_path / "missing.tif", name="topo")


def test_a_support_without_a_shape_matches_any_values():
    shapeless = RasterSupport(crs="EPSG:2154", xmin=0.0, xmax=1.0, ymin=0.0, ymax=1.0)

    assert Surface("topo", ROW, None).assert_support_matches_values() is None
    assert Surface("topo", ROW, shapeless).assert_support_matches_values() is None


_TOP = surface([[10.0, 12.0], [14.0, 16.0]])


@pytest.mark.parametrize(
    ("call", "error", "match"),
    [
        (lambda: _TOP.assert_same_geographic_domain(_TOP.support), TypeError, "Expected Surface"),
        (lambda: _TOP.assert_same_geographic_domain(Surface("b", ROW)), ValueError, "Both"),
        (lambda: Surface("t", ROW, _TOP.support).assert_support_matches_values(), ValueError,
         "does not match support shape"),
        (lambda: Surface("t", ROW).resample_to_shape(2, 2), ValueError, "no RasterSupport"),
        (lambda: _TOP.resample_to_shape(0, 2), ValueError, ">= 1"),
        (lambda: _TOP.resample_to_shape(4, 4, resampling="cubic"), ValueError, "Unsupported"),
        (lambda: Surface("t", ROW).reprojected_onto(_TOP.support), ValueError, "no RasterSupport"),
        (lambda: _TOP.assert_strictly_below(Surface("u", ROW)), ValueError, "different shapes"),
        (lambda: _TOP.assert_strictly_below(Surface("u", np.full((2, 2), np.nan))), ValueError,
         "no finite overlapping"),
        (lambda: _TOP.assert_strictly_below(_TOP), ValueError,
         "must be strictly below"),
    ],
    ids=["other_not_a_surface", "other_without_support", "shape_off_its_support",
         "resample_without_support", "resample_to_no_cell", "unknown_resampling",
         "reproject_without_support", "below_another_shape", "below_without_overlap",
         "below_but_above"],
)  # fmt: skip
def test_a_surface_operation_on_a_surface_that_cannot_hold_it_is_refused(call, error, match):
    with pytest.raises(error, match=match):
        call()


def test_strictly_below_checks_the_finite_cells_only():
    upper = surface([[10.0, np.nan], [14.0, 16.0]])

    assert _TOP.shifted_down_by(1.0).assert_strictly_below(upper) is None


def test_a_support_without_nodata_resamples_onto_the_default_sentinel():
    raw = surface([[1.0, 2.0], [3.0, 4.0]], nodata=None)
    resampled = raw.resample_to_shape(1, 1)

    assert resampled.support.nodata == -9999.0
    assert resampled.as_array().shape == (1, 1)
    assert raw.resample_to_shape(1, 1, nodata=-1.0).support.nodata == -1.0


def test_the_same_numbers_in_another_crs_are_warped_not_copied():
    """A grid of one shape at the same numbers in another CRS sits elsewhere on Earth."""
    raw = surface([[1.0, 2.0], [3.0, 4.0]], nodata=None)

    elsewhere = raw.reprojected_onto(raster_support(2, 2, crs="EPSG:3857"), resampling="nearest")

    assert np.all(np.isnan(elsewhere.as_array()))
