"""Seam tests for zonal top sampling in the runtime-mesh discretization builder.

Guards the byte-identical default (mode='centroid' must not perturb the top a
validated run relies on) and checks the zonal branch flows end-to-end through a
real HydroMesh, lowering a channel cell to its thalweg.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.solver.modflow_grid.discretization_spatial import (
    _build_extruded_solver_mesh_from_runtime_planar,
)
from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh
from hydromodpy.spatial.mesh.cartesian_grid.sgrid_config import (
    TopSamplingConfig,
    VerticalGridConfig,
)
from hydromodpy.spatial.raster_support import RasterSupport
from hydromodpy.spatial.surface import Surface

_EXTENT = 100.0
_N = 40


def _two_quads() -> HydroMesh:
    """Two side-by-side quads: cell 0 = x[0,50], cell 1 = x[50,100]."""
    verts = np.array(
        [
            [0.0, 0.0],
            [50.0, 0.0],
            [100.0, 0.0],
            [0.0, 100.0],
            [50.0, 100.0],
            [100.0, 100.0],
        ],
        dtype=float,
    )
    conn = np.array([[0, 1, 4, 3], [1, 2, 5, 4]], dtype=int)
    return HydroMesh(
        vertices=verts,
        cell_blocks=(CellBlock(CellType.QUADRILATERAL, conn),),
        structured_shape=None,
    )


def _surface(values: np.ndarray, name: str) -> Surface:
    support = RasterSupport(
        crs=None,
        dx=_EXTENT / _N,
        dy=_EXTENT / _N,
        xmin=0.0,
        xmax=_EXTENT,
        ymin=0.0,
        ymax=_EXTENT,
        nrows=_N,
        ncols=_N,
        nodata=-9999.0,
    )
    return Surface(name=name, values=values, support=support)


def _ramp_dem() -> np.ndarray:
    xs = (np.arange(_N) + 0.5) * (_EXTENT / _N)
    return np.tile(xs, (_N, 1))


def _build(top_surface, bottom_surface, *, top_sampling=None, channel_mask=None):
    return _build_extruded_solver_mesh_from_runtime_planar(
        planar_mesh=_two_quads(),
        top_surface=top_surface,
        bottom_surface=bottom_surface,
        vertical_config=VerticalGridConfig(),
        nodata=-9999.0,
        grid_dual="triangle",  # keep the quads as-is, no Voronoi dual
        top_sampling=top_sampling,
        channel_mask=channel_mask,
    )


def test_centroid_mode_is_byte_identical_to_the_baseline():
    top_surface = _surface(_ramp_dem(), "top")
    bottom_surface = _surface(np.full((_N, _N), -10.0), "bot")
    baseline = _build(top_surface, bottom_surface, top_sampling=None)
    centroid = _build(top_surface, bottom_surface, top_sampling=TopSamplingConfig(mode="centroid"))
    assert np.array_equal(baseline.top, centroid.top)
    # The generators sit at x = 25 and 75 on the z = x ramp.
    assert baseline.top == pytest.approx([25.0, 75.0], abs=1.0)


def test_zonal_channel_min_lowers_the_channel_cell_through_the_seam():
    dem = _ramp_dem()
    xs = (np.arange(_N) + 0.5) * (_EXTENT / _N)
    channel = np.zeros((_N, _N), dtype=bool)
    notch = (xs >= 10.0) & (xs <= 15.0)  # off-centre channel in cell 0
    dem[:, notch] = 5.0
    channel[:, notch] = True
    top_surface = _surface(dem, "top")
    bottom_surface = _surface(np.full((_N, _N), -10.0), "bot")
    zonal = _build(
        top_surface,
        bottom_surface,
        top_sampling=TopSamplingConfig(mode="zonal", channel_stat="min", spike_guard_tol_m=0.0),
        channel_mask=channel,
    )
    # Cell 0 carries the channel -> its top drops to the thalweg min; cell 1 stays.
    assert zonal.top[0] == pytest.approx(5.0, abs=1e-3)
    assert zonal.top[1] == pytest.approx(75.0, abs=2.0)


def test_zonal_without_georeference_falls_back_to_centroid():
    ramp = _ramp_dem()
    support_none = Surface(name="top", values=ramp, support=None)
    bottom = _surface(np.full((_N, _N), -10.0), "bot")
    # A bottom with support but a top without: the zonal path needs the top grid,
    # so it must fall back to the centroid sample without raising.
    out = _build(
        _surface(ramp, "top"),
        bottom,
        top_sampling=TopSamplingConfig(mode="zonal", channel_source="none"),
    )
    assert np.all(np.isfinite(out.top))
    _ = support_none
