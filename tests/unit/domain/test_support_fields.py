"""A raster, ring, band or aliased support gives each cell of a planar mesh the share of each zone."""

from __future__ import annotations

import numpy as np
from shapely.geometry import Polygon

from hydromodpy.spatial.domain.support_fields import (
    AliasedSpatialSupportField,
    GeneratedBandsSupportField,
    GeneratedRingsSupportField,
    RasterZonesSupportField,
)
from hydromodpy.spatial.field.field_param import FieldParam
from hydromodpy.spatial.mesh.engines.voronoi.tessellation import voronoi_planar_mesh
from hydromodpy.spatial.raster_support import RasterSupport
from tests._helpers.cell_meshes import cell_mesh_of
from tests._helpers.mesh_cases import regular_mesh


def test_a_raster_support_gives_each_cell_its_pixels_and_a_ring_support_shares_a_cell():
    cell_mesh = regular_mesh(2, 2, dx=10.0)
    support = RasterSupport(crs="EPSG:2154", dx=10.0, dy=20.0, xmin=0.0, xmax=20.0, ymin=0.0, ymax=20.0, nrows=1, ncols=2)  # fmt: skip
    raster = RasterZonesSupportField(identifier="geology", encoded_codes=np.array([[1, 2]], dtype=np.int32), encoded_to_zone={1: "west", 2: "east"}, raster_support=support)  # fmt: skip

    disc = AliasedSpatialSupportField(identifier="alias", delegate=raster).on_mesh(cell_mesh, cell_samples_per_axis=4)  # fmt: skip

    assert disc.mesh is cell_mesh
    np.testing.assert_array_equal(disc.fractions_by_zone["west"], [1.0, 0.0, 1.0, 0.0])
    np.testing.assert_array_equal(disc.fractions_by_zone["east"], [0.0, 1.0, 0.0, 1.0])
    # A ring support shares a cell between its rings.
    cell_mesh = regular_mesh(1, 3, dx=10.0)
    rings = GeneratedRingsSupportField(identifier="rings", center_x=15.0, center_y=5.0, radii_abs=[5.0], labels=["in", "out"])  # fmt: skip

    disc = rings.on_mesh(cell_mesh, cell_samples_per_axis=8)

    inner = np.asarray(disc.fractions_by_zone["in"])
    np.testing.assert_allclose(inner + disc.fractions_by_zone["out"], 1.0)
    assert inner[0] == inner[2] == 0.0
    assert 0.5 < inner[1] < 1.0


def test_a_band_support_samples_the_ragged_polygons_of_a_voronoi_mesh():
    grid = np.linspace(50.0, 950.0, 12)
    xx, yy = np.meshgrid(grid, grid)
    seeds = np.c_[xx.ravel(), yy.ravel()] + np.random.default_rng(0).uniform(-25.0, 25.0, (144, 2))
    domain = Polygon([(0.0, 0.0), (1000.0, 0.0), (1000.0, 1000.0), (0.0, 1000.0)])
    cell_mesh = cell_mesh_of(voronoi_planar_mesh(seeds, domain))
    support = GeneratedBandsSupportField(identifier="k", axis="x", breaks_abs=[500.0], labels=["west", "east"])  # fmt: skip

    disc = support.on_mesh(cell_mesh, cell_samples_per_axis=8)

    west = np.asarray(disc.fractions_by_zone["west"], dtype=float)
    east = np.asarray(disc.fractions_by_zone["east"], dtype=float)
    assert disc.mesh is cell_mesh and west.shape == (cell_mesh.n_cells,)
    assert np.all(west >= -1e-9) and np.all(west <= 1.0 + 1e-9)
    np.testing.assert_allclose(west + east, 1.0, atol=1e-9)
    deep_west = np.flatnonzero(seeds[:, 0] < 300.0)
    assert deep_west.size > 0
    assert np.all(west[deep_west] > 0.99)


def test_two_raster_codes_with_one_label_are_one_zone_and_its_value_counts_once():
    cell_mesh = regular_mesh(2, 2, dx=10.0)
    support = RasterSupport(crs="EPSG:2154", dx=10.0, dy=20.0, xmin=0.0, xmax=20.0, ymin=0.0, ymax=20.0, nrows=1, ncols=2)  # fmt: skip
    raster = RasterZonesSupportField(identifier="geology", encoded_codes=np.array([[1, 2]], dtype=np.int32), encoded_to_zone={1: "granite", 2: " granite"}, raster_support=support)  # fmt: skip
    param = FieldParam(identifier="K", kind="heterogeneous", values_by_key={"granite": 1e-5}, field_spatial_id="geology")  # fmt: skip

    disc = raster.on_mesh(cell_mesh, cell_samples_per_axis=4)

    assert raster.zone_keys == disc.zone_keys == ("granite",)
    np.testing.assert_array_equal(disc.fractions_by_zone["granite"], 1.0)
    np.testing.assert_allclose(param.to_mesh_field(disc).cell_values, 1e-5)
