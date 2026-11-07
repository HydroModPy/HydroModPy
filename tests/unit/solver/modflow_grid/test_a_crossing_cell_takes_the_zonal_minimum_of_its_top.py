"""A cell a river crosses off its center takes the lowest DEM pixel it holds, in centroid mode.

Two side-by-side cells on a DEM ramp with a notch (the river bed) in cell 0, off the
cell center. The centroid sample of cell 0 lands on the ramp, on a bank. A river chain
that publishes a lateral offset above zero marks the cell as a crossing cell, and only
that cell is lowered to the notch. A chain without offsets, or with a zero offset, leaves
the top byte for byte on the centroid sample.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.mesh.planar.planar_cell_mesh import CellChain, MeshIdentity, build_planar_cell_mesh
from hydromodpy.model.domain.layers_config import VerticalGridConfig
from hydromodpy.solver.modflow_grid.discretization_spatial import (
    _build_extruded_solver_mesh_from_runtime_planar,
)
from hydromodpy.solver.modflow_grid.sgrid_config import TopSamplingConfig
from hydromodpy.spatial.raster_support import RasterSupport
from hydromodpy.spatial.surface import Surface
from tests._helpers.cell_meshes import TEST_CRS_WKT

_EXTENT = 100.0
_N = 40
_THALWEG_M = 0.5


def _two_quads() -> HydroMesh:
    verts = np.array(
        [[0.0, 0.0], [50.0, 0.0], [100.0, 0.0], [0.0, 100.0], [50.0, 100.0], [100.0, 100.0]]
    )
    conn = np.array([[0, 1, 4, 3], [1, 2, 5, 4]], dtype=int)
    return HydroMesh(vertices=verts, cell_blocks=(CellBlock(CellType.QUADRILATERAL, conn),))


def _cell_mesh(chains: tuple[CellChain, ...]):
    hydro = _two_quads()
    x, y = hydro.cell_centroids()
    return build_planar_cell_mesh(
        hydro,
        np.column_stack([x, y]),
        center_kind="vertex_mean",
        crs_wkt=TEST_CRS_WKT,
        identity=MeshIdentity("test", "0", "", None),
        declarations={
            "graded": False,
            "exact_faces": False,
            "deterministic": True,
            "needs_cache": False,
        },
        cell_chains=chains,
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


def _dem_with_notch() -> np.ndarray:
    xs = (np.arange(_N) + 0.5) * (_EXTENT / _N)
    dem = np.tile(xs, (_N, 1))
    dem[:, (xs >= 10.0) & (xs <= 15.0)] = _THALWEG_M
    return dem


def _build(
    chains: tuple[CellChain, ...],
    *,
    top_sampling=None,
    bottom: float = -10.0,
    dem: np.ndarray | None = None,
    channel_mask: np.ndarray | None = None,
):
    return _build_extruded_solver_mesh_from_runtime_planar(
        cell_mesh=_cell_mesh(chains),
        top_surface=_surface(_dem_with_notch() if dem is None else dem, "top"),
        bottom_surface=_surface(np.full((_N, _N), bottom), "bot"),
        vertical_config=VerticalGridConfig(),
        nodata=-9999.0,
        top_sampling=top_sampling,
        channel_mask=channel_mask,
    )


def _chain(cells, offsets) -> CellChain:
    return CellChain(
        "rivers", 0, np.asarray(cells), None if offsets is None else np.asarray(offsets)
    )


def test_a_crossing_cell_is_lowered_to_the_lowest_pixel_it_holds():
    baseline = _build(())
    crossing = _build((_chain([0, 1], [8.0, 0.0]),))
    assert baseline.top[0] == pytest.approx(25.0, abs=1.0)
    assert crossing.top[0] == pytest.approx(_THALWEG_M, abs=1e-6)


def test_the_other_cells_keep_the_centroid_sample_byte_for_byte():
    baseline = _build(())
    crossing = _build((_chain([0, 1], [8.0, 0.0]),))
    assert crossing.top[1] == baseline.top[1]
    assert np.array_equal(crossing.botm[:, 1], baseline.botm[:, 1])


@pytest.mark.parametrize("offsets", [None, [0.0, 0.0]], ids=["no-offset", "zero-offset"])
def test_a_chain_without_lateral_offset_changes_nothing(offsets):
    baseline = _build(())
    held = _build((_chain([0, 1], offsets),))
    assert np.array_equal(held.top, baseline.top)


def test_the_centroid_mode_config_gives_the_same_result_as_no_config():
    chains = (_chain([0, 1], [8.0, 0.0]),)
    assert np.array_equal(
        _build(chains, top_sampling=TopSamplingConfig(mode="centroid")).top,
        _build(chains).top,
    )


def test_a_lowered_top_that_meets_the_bottom_drags_the_bottom_down_with_it():
    """The notch is far under the center sample: the column keeps its center-sample thickness."""
    config = TopSamplingConfig(mode="centroid", min_thickness_m=0.5)
    baseline = _build((), top_sampling=config, bottom=_THALWEG_M - 0.1)
    crossing = _build((_chain([0], [8.0]),), top_sampling=config, bottom=_THALWEG_M - 0.1)
    centre_column = baseline.top[0] - baseline.botm[-1, 0]

    assert crossing.top[0] == pytest.approx(_THALWEG_M, abs=1e-6)
    assert crossing.top[0] - crossing.botm[-1, 0] == pytest.approx(centre_column)
    assert crossing.botm[-1, 0] < _THALWEG_M - 0.1
    assert np.array_equal(crossing.botm[:, 1], baseline.botm[:, 1])


def test_a_lowered_top_that_clears_the_minimum_thickness_leaves_the_bottom_alone():
    config = TopSamplingConfig(mode="centroid", min_thickness_m=0.5)
    baseline = _build((), top_sampling=config)
    crossing = _build((_chain([0], [8.0]),), top_sampling=config)

    assert crossing.top[0] == pytest.approx(_THALWEG_M, abs=1e-6)
    assert np.array_equal(crossing.botm[-1], baseline.botm[-1])


def test_a_cell_that_was_not_lowered_keeps_a_thin_column_as_it_is():
    """A bottom within the minimum thickness of an unlowered top is not this guard's business."""
    config = TopSamplingConfig(mode="centroid", min_thickness_m=0.5)
    thin = _build((), top_sampling=config, bottom=24.9)
    assert thin.botm[-1, 0] == pytest.approx(24.9)


def test_a_pit_far_under_the_centre_sample_keeps_the_column_of_a_zonal_cell():
    """A channel pixel 60 m under the center sample must not leave a column of 0.1 m."""
    dem = np.tile((np.arange(_N) + 0.5) * (_EXTENT / _N), (_N, 1))
    dem[4:8, 2:6] = -60.0
    channel = dem < -50.0
    config = TopSamplingConfig(mode="zonal", channel_source="none", min_thickness_m=0.1)
    zonal = _build((), top_sampling=config, bottom=0.0, dem=dem, channel_mask=channel)
    centre = _build((), bottom=0.0, dem=dem)

    assert zonal.top[0] == pytest.approx(-60.0)
    assert zonal.top[0] - zonal.botm[-1, 0] == pytest.approx(centre.top[0] - 0.0)
    assert zonal.top[1] - zonal.botm[-1, 1] > 1.0


@pytest.mark.parametrize(
    ("lowering_share", "follows"),
    [(0.95, True), (0.80, False)],
    ids=["leaves-5-percent", "leaves-20-percent"],
)
def test_a_column_that_keeps_less_than_a_tenth_of_its_centre_thickness_is_restored(
    lowering_share, follows
):
    """The notch removes 95 % of the 25 m center column (0.5 m < 10 % of it) but not 80 %."""
    config = TopSamplingConfig(mode="centroid", min_thickness_m=0.1)
    baseline = _build((), top_sampling=config, bottom=0.0)
    centre_column = baseline.top[0]
    dem = _dem_with_notch()
    dem[:, (np.arange(_N) + 0.5) * (_EXTENT / _N) <= 15.0] = (1.0 - lowering_share) * centre_column
    crossing = _build((_chain([0], [8.0]),), top_sampling=config, bottom=0.0, dem=dem)

    column = crossing.top[0] - crossing.botm[-1, 0]
    assert column == pytest.approx(
        centre_column if follows else (1.0 - lowering_share) * centre_column
    )
