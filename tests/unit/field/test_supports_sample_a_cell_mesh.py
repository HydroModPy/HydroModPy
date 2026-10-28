"""The raster, ring and aliased supports sample the cells of a planar cell mesh."""

from __future__ import annotations

import numpy as np

from hydromodpy.spatial.domain.spatial_support import (
    AliasedSpatialSupportField,
    GeneratedRingsSupportField,
    RasterZonesSupportField,
)
from hydromodpy.spatial.raster_support import RasterSupport
from tests._helpers.mesh_cases import regular_mesh


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
