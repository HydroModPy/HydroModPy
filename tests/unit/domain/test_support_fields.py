"""The support fields sample the cells of a planar cell mesh, :mod:`hydromodpy.spatial.domain.spatial_support`.

A raster, ring, band or aliased support gives each cell the share of each of
its zones, on regular cells and on the ragged polygons of a Voronoi mesh.
"""

from __future__ import annotations

import numpy as np
from shapely.geometry import Polygon

from hydromodpy.spatial.domain.spatial_support import (
    AliasedSpatialSupportField,
    GeneratedBandsSupportField,
    GeneratedRingsSupportField,
    RasterZonesSupportField,
)
from hydromodpy.spatial.mesh.engines.voronoi.tessellation import voronoi_planar_mesh
from hydromodpy.spatial.raster_support import RasterSupport
from tests._helpers.cell_meshes import cell_mesh_of
from tests._helpers.mesh_cases import regular_mesh

# ---- sampling on cell meshes (from tests/unit/field) ----------------------


def test_a_raster_support_gives_each_cell_the_zone_of_its_pixels():
    cell_mesh = regular_mesh(2, 2, dx=10.0)
    support = RasterSupport(
        crs="EPSG:2154",
        dx=10.0,
        dy=20.0,
        xmin=0.0,
        xmax=20.0,
        ymin=0.0,
        ymax=20.0,
        nrows=1,
        ncols=2,
    )
    raster = RasterZonesSupportField(
        identifier="geology",
        encoded_codes=np.array([[1, 2]], dtype=np.int32),
        encoded_to_zone={1: "west", 2: "east"},
        raster_support=support,
    )

    disc = AliasedSpatialSupportField(identifier="alias", delegate=raster).on_mesh(
        cell_mesh, cell_samples_per_axis=4
    )

    assert disc.mesh is cell_mesh
    np.testing.assert_array_equal(disc.fractions_by_zone["west"], [1.0, 0.0, 1.0, 0.0])
    np.testing.assert_array_equal(disc.fractions_by_zone["east"], [0.0, 1.0, 0.0, 1.0])


def test_a_ring_support_shares_a_cell_between_its_rings():
    cell_mesh = regular_mesh(1, 3, dx=10.0)
    rings = GeneratedRingsSupportField(
        identifier="rings", center_x=15.0, center_y=5.0, radii_abs=[5.0], labels=["in", "out"]
    )

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
    support = GeneratedBandsSupportField(
        identifier="k", axis="x", breaks_abs=[500.0], labels=["west", "east"]
    )

    disc = support.on_mesh(cell_mesh, cell_samples_per_axis=8)

    west = np.asarray(disc.fractions_by_zone["west"], dtype=float)
    east = np.asarray(disc.fractions_by_zone["east"], dtype=float)
    assert disc.mesh is cell_mesh
    assert west.shape == (cell_mesh.n_cells,)
    assert np.all(west >= -1e-9) and np.all(west <= 1.0 + 1e-9)
    np.testing.assert_allclose(west + east, 1.0, atol=1e-9)
    deep_west = np.flatnonzero(seeds[:, 0] < 300.0)
    assert deep_west.size > 0
    assert np.all(west[deep_west] > 0.99)
