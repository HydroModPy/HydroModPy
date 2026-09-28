"""The snap floor F is averaged the way the scored Doptim is.

F is the Doptim a model reproducing the snapped map exactly would reach. So a
simulated network equal to the snapped map, scored against the raw map, must
give back F, under the cell weighting and under the area weighting alike. On a
mesh whose cells do not share one area, the two weightings part, and F must
follow the one the output declares.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.calibration.metrics.downslope_network import score_on_geometry
from hydromodpy.core.stream_geometry import build_network_geometry
from hydromodpy.core.stream_network import build_simulated_network
from hydromodpy.core.stream_snap import SnapStreamsConfig
from tests._helpers.ugrid_meshes import quad_mesh
from tests._helpers.v_valley import (
    CELL_SIZE,
    N_CELLS,
    N_COLS,
    N_ROWS,
    build_bench,
    observed_network,
)


@pytest.fixture(scope="module")
def mesh():
    return quad_mesh(N_ROWS, N_COLS, cell_size=CELL_SIZE)


@pytest.fixture(scope="module")
def bench():
    return build_bench()


def _areas(uniform: bool) -> np.ndarray:
    if uniform:
        return np.full(N_CELLS, CELL_SIZE * CELL_SIZE)
    # Cells grow downstream, as on a mesh coarsened away from the springs.
    rows = np.repeat(np.arange(N_ROWS, dtype=float), N_COLS)
    return CELL_SIZE * CELL_SIZE * (1.0 + 3.0 * rows / (N_ROWS - 1))


def _geometry(bench, mesh, *, weighting: str, uniform: bool):
    vertices, connectivity = mesh
    return build_network_geometry(
        topography=bench.elevation,
        face_node_connectivity=connectivity,
        vertices=vertices,
        observed=observed_network("shifted"),
        cell_area_m2=_areas(uniform),
        mean_recharge_m_s=1e-8,
        tau_specific_ratio=0.0,
        snap=SnapStreamsConfig(mode="diagnose"),
        weighting=weighting,
    )


def _doptim_of_the_snapped_map(geometry, weighting: str) -> float:
    release = np.where(geometry.snap.snapped & geometry.metric.graph.active, 1.0, 0.0)
    simulated = build_simulated_network(
        release, threshold_m3_s=geometry.threshold_m3_s, metric=geometry.metric
    )
    assert np.array_equal(simulated.network, geometry.snap.snapped)
    result = score_on_geometry(simulated, geometry, weighting=weighting)
    return float(result.components["Doptim"])


@pytest.mark.parametrize("weighting", ["cell", "area"])
@pytest.mark.parametrize("uniform", [True, False])
def test_the_floor_is_the_doptim_of_the_snapped_map(bench, mesh, weighting, uniform) -> None:
    geometry = _geometry(bench, mesh, weighting=weighting, uniform=uniform)

    assert geometry.snap.floor_m == pytest.approx(
        _doptim_of_the_snapped_map(geometry, weighting), rel=1e-12
    )


def test_the_floor_follows_the_weighting_when_the_areas_differ(bench, mesh) -> None:
    by_cell = _geometry(bench, mesh, weighting="cell", uniform=False).snap
    by_area = _geometry(bench, mesh, weighting="area", uniform=False).snap

    # The cell floor is the measured one of the one-column shift; the area
    # floor leans on the large downstream cells, whose descent is short.
    assert by_cell.floor_m == pytest.approx(127.0, abs=0.1)
    assert by_area.floor_m < by_cell.floor_m - 1.0
    assert by_area.indices["snap_floor_m"] == pytest.approx(by_area.floor_m)


def test_uniform_areas_give_one_floor_whatever_the_weighting(bench, mesh) -> None:
    by_cell = _geometry(bench, mesh, weighting="cell", uniform=True).snap
    by_area = _geometry(bench, mesh, weighting="area", uniform=True).snap

    assert by_area.floor_m == pytest.approx(by_cell.floor_m, rel=1e-12)
