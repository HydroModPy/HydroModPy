"""The MODFLOW 6 budget zone `catchment`, read from the basin of D stored beside the run.

The budget is computed before the Zarr store is written, so the extractor reads the basin of
D (a mask of cells, area in m2) from the descent sidecar and never computes it again. A build
with no basin keeps the old support `polygon_centroid` and says so.
"""

from __future__ import annotations

import logging

import numpy as np
import pytest

from hydromodpy.catchment.drainage import descent as core_descent
from hydromodpy.catchment.drainage.descent import DescentBasin
from hydromodpy.solver.modflow6.extractors.flow import Modflow6OutputAdapter
from hydromodpy.solver.modflow_common import catchment_basin
from hydromodpy.solver.modflow_common.descent_store import write_descent_sidecar
from tests._helpers.descent_cases import grid_descent

TOP_M = np.array([[5.0, 4.0, 3.0], [4.0, 1.0, 2.0], [6.0, 5.0, 4.0]])
N_CELLS = TOP_M.size


class NoWatershedStore:
    """A store that holds no watershed, so the old support finds nothing to place."""

    def read_geographic_feature(self, sim_id, name):
        return None


def basin_of_four(rule: str = "within_polygon") -> DescentBasin:
    mask = np.zeros(N_CELLS, dtype=bool)
    mask[[1, 2, 4, 5]] = True
    return DescentBasin(mask=mask, outlet=4, rule=rule, area_m2=4.0e6, seeded_at_outlet=False)


def zone(folder, n_cells=N_CELLS):
    return Modflow6OutputAdapter()._catchment_cell_mask(
        "sim", NoWatershedStore(), folder, n_cells=n_cells
    )


# One row per sidecar left by an old build, and the reason the warning gives.
NO_BASIN = [
    pytest.param(lambda folder: None, "no descent sidecar", id="no sidecar"),
    pytest.param(
        lambda folder: write_descent_sidecar(grid_descent(TOP_M), folder, "model"),
        "a sidecar written before the basin was stored",
        id="sidecar before the basin",
    ),
]


def test_zone_is_the_basin_in_the_sidecar(tmp_path, caplog) -> None:
    write_descent_sidecar(grid_descent(TOP_M), tmp_path, "model", basin=basin_of_four())

    with caplog.at_level(logging.INFO):
        mask = zone(tmp_path)

    np.testing.assert_array_equal(mask, basin_of_four().mask)
    assert "the basin of D, 4 of 9 cells (4.000 km2)" in caplog.text
    assert "polygon_centroid" not in caplog.text


def test_zone_does_not_recompute_the_basin(tmp_path, monkeypatch) -> None:
    def refuse(*_args, **_kwargs):
        raise AssertionError("the budget zone computed the basin of D again")

    write_descent_sidecar(grid_descent(TOP_M), tmp_path, "model", basin=basin_of_four())
    monkeypatch.setattr(core_descent, "descent_basin", refuse)
    monkeypatch.setattr(catchment_basin, "descent_basin", refuse)

    np.testing.assert_array_equal(zone(tmp_path), basin_of_four().mask)


def test_largest_basin_is_no_zone(tmp_path, caplog) -> None:
    basin = basin_of_four("largest_basin")
    write_descent_sidecar(grid_descent(TOP_M), tmp_path, "model", basin=basin)

    with caplog.at_level(logging.INFO):
        mask = zone(tmp_path)

    assert mask is None
    assert "polygon_centroid" not in caplog.text


@pytest.mark.parametrize(("make_sidecar", "reason"), NO_BASIN)
def test_no_basin_keeps_the_old_support(tmp_path, caplog, make_sidecar, reason) -> None:
    make_sidecar(tmp_path)

    with caplog.at_level(logging.INFO):
        mask = zone(tmp_path)

    assert mask is None
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings == [
        f"Budget zone 'catchment' for sim sim: the build left no basin of D ({reason}), so the "
        "zone keeps the old support 'polygon_centroid'."
    ]


def test_basin_of_another_mesh_size_is_not_used(tmp_path, caplog) -> None:
    write_descent_sidecar(grid_descent(TOP_M), tmp_path, "model", basin=basin_of_four())

    with caplog.at_level(logging.INFO):
        mask = zone(tmp_path, n_cells=N_CELLS + 1)

    assert mask is None
    assert "a basin of 9 cells on a mesh of 10" in caplog.text
