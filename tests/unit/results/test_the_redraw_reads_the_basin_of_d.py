"""The redraw measures its catchment mismatch against the basin of D the run stores.

The trials of a run compared the catchment their graph closed with the basin of
D the build kept on the model. A redraw from the store reads that same basin, so
the number it prints is the one the trials scored. A run sealed before the basin
was stored keeps the delineated polygon and says so. The grid is the 5 x 3
valley of ``tests.unit.display._network_comparison_run``, whose graph catchment
is the whole grid.
"""

from __future__ import annotations

import logging
from dataclasses import replace

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import box

from hydromodpy.results.derive.stream_network import network_comparison_from_run
from hydromodpy.results.run.descent import RunDescent
from tests.unit.display._network_comparison_run import (
    CELL_M,
    NX,
    NY,
    comparison_run,
    stored_descent,
)

NO_BASIN_WARNING = "stores no basin of D"


def _run(*, basin: np.ndarray | None, rule: str = "near_point"):
    """A run whose delineated polygon spans columns 1 to 3 and whose graph closes on the grid."""
    run = comparison_run()
    narrow = gpd.GeoDataFrame(
        geometry=[box(1 * CELL_M, -0.1 * CELL_M, 4 * CELL_M, (NY + 0.1) * CELL_M)], crs=run.mesh.crs
    )
    run.geographic = lambda feature: narrow
    mesh = run.mesh
    attrs = {} if basin is None else {"basin_rule": rule}
    run.descent = RunDescent(
        lambda: replace(
            stored_descent(mesh.topography, mesh.face_node_connectivity, mesh.vertices),
            basin=basin,
            basin_attrs=attrs,
        )
    )
    return run


def _mismatch(run) -> float:
    return network_comparison_from_run(
        run, observed_rasterization="crossing"
    ).geometry.catchment_mismatch


def test_a_stored_basin_is_the_reference_of_the_mismatch(caplog) -> None:
    whole_grid = np.ones(NX * NY, dtype=bool)

    with caplog.at_level(logging.WARNING):
        mismatch = _mismatch(_run(basin=whole_grid))

    assert mismatch == pytest.approx(0.0)
    assert NO_BASIN_WARNING not in caplog.text


def test_a_stored_basin_replaces_the_polygon_without_reading_it() -> None:
    run = _run(basin=np.ones(NX * NY, dtype=bool))

    def refuse(feature):
        raise AssertionError("the polygon is not read when the run stores a basin")

    run.geographic = refuse

    assert _mismatch(run) == pytest.approx(0.0)


def test_a_run_without_a_stored_basin_keeps_the_polygon_and_says_so(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        mismatch = _mismatch(_run(basin=None))

    # The polygon spans 9 of the 15 cells the graph closes: 6 of them lie outside it.
    assert mismatch == pytest.approx(6 / 9)
    assert (
        "Stream comparison: run sim-network stores no basin of D, so the catchment mismatch "
        "is measured against the old reference 'polygon_centroid', as its trials were."
        in caplog.text
    )


def test_the_largest_basin_of_a_synthetic_domain_is_no_catchment(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        mismatch = _mismatch(_run(basin=np.ones(NX * NY, dtype=bool), rule="largest_basin"))

    assert mismatch == pytest.approx(6 / 9)
    assert NO_BASIN_WARNING not in caplog.text


def test_a_run_sealed_without_d_is_not_rebuilt_to_learn_it_has_no_basin(caplog) -> None:
    run = _run(basin=None)

    def refuse() -> None:
        raise AssertionError("D was loaded or rebuilt to read a basin that is not there")

    run.descent = RunDescent(refuse, load_basin=lambda: None)

    with caplog.at_level(logging.WARNING):
        mismatch = _mismatch(run)

    assert mismatch == pytest.approx(6 / 9)
    assert NO_BASIN_WARNING in caplog.text
