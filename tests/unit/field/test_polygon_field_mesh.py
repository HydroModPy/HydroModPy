"""A field samples by area on the ragged polygon cells of a Voronoi mesh."""

from __future__ import annotations

import numpy as np
from shapely.geometry import Polygon

from hydromodpy.spatial.domain.spatial_support import GeneratedBandsSupportField
from hydromodpy.spatial.field.meshes.polygon_field_mesh import PolygonFieldMesh
from hydromodpy.spatial.mesh.engines.voronoi.tessellation import voronoi_planar_mesh

_DOMAIN = Polygon([(0.0, 0.0), (1000.0, 0.0), (1000.0, 1000.0), (0.0, 1000.0)])


def _jittered_seeds(n_side: int = 12) -> np.ndarray:
    rng = np.random.default_rng(0)
    grid = np.linspace(50.0, 950.0, n_side)
    xx, yy = np.meshgrid(grid, grid)
    return np.c_[xx.ravel(), yy.ravel()] + rng.uniform(-25.0, 25.0, (n_side * n_side, 2))


def test_heterogeneous_field_samples_on_voronoi_polygon_cells() -> None:
    # A support field discretized through PolygonFieldMesh must not crash on the
    # ragged POLYGON cells and must produce valid area fractions.
    mesh = voronoi_planar_mesh(_jittered_seeds(), _DOMAIN)
    field_mesh = PolygonFieldMesh(mesh)
    support = GeneratedBandsSupportField(
        identifier="k", axis="x", breaks_abs=[500.0], labels=["west", "east"]
    )
    disc = support.on_mesh(field_mesh, cell_samples_per_axis=8)
    west = np.asarray(disc.fractions_by_zone["west"], dtype=float)
    east = np.asarray(disc.fractions_by_zone["east"], dtype=float)
    assert west.shape == (mesh.n_cells,)
    assert np.all(west >= -1e-9) and np.all(west <= 1.0 + 1e-9)
    assert np.allclose(west + east, 1.0, atol=1e-9)
    xs, _ = mesh.cell_centroids()
    deep_west = np.flatnonzero(xs < 300.0)
    assert deep_west.size > 0
    assert np.all(west[deep_west] > 0.99)
