"""The MODFLOW 6 budget zone ``catchment`` is the basin of D the build kept.

The budget is computed before the Zarr store is written, so the extractor reads
the basin from the descent sidecar, never from a second computation. A build
that left none (no sidecar, a sidecar written before the basin was stored, an
unreadable one) keeps the old support ``polygon_centroid`` and says so.
"""

from __future__ import annotations

import logging

import numpy as np
import pytest

from hydromodpy.core import descent as core_descent
from hydromodpy.core.descent import DescentBasin
from hydromodpy.solver.modflow6.extractors.flow import Modflow6OutputAdapter
from hydromodpy.solver.modflow_common import catchment_basin
from hydromodpy.solver.modflow_common.descent_store import write_descent_sidecar
from tests._helpers.descent_cases import grid_descent

TOP = np.array([[5.0, 4.0, 3.0], [4.0, 1.0, 2.0], [6.0, 5.0, 4.0]])
N_CELLS = TOP.size


class _NoStore:
    """A store that holds no watershed, so the old support finds nothing to place."""

    def read_geographic_feature(self, sim_id, name):
        del sim_id, name
        return None


def _basin(rule: str = "within_polygon") -> DescentBasin:
    mask = np.zeros(N_CELLS, dtype=bool)
    mask[[1, 2, 4, 5]] = True
    return DescentBasin(mask=mask, outlet=4, rule=rule, area_m2=4.0e6, seeded_at_outlet=False)


def _zone(folder, store=None) -> np.ndarray | None:
    return Modflow6OutputAdapter()._catchment_cell_mask(
        "sim", store if store is not None else _NoStore(), folder, n_cells=N_CELLS
    )


def test_the_zone_is_the_basin_in_the_sidecar(tmp_path, caplog) -> None:
    basin = _basin()
    write_descent_sidecar(grid_descent(TOP), tmp_path, "model", basin=basin)

    with caplog.at_level(logging.INFO):
        zone = _zone(tmp_path)

    np.testing.assert_array_equal(zone, basin.mask)
    assert "the basin of D, 4 of 9 cells (4.000 km2)" in caplog.text
    assert "polygon_centroid" not in caplog.text


def test_the_zone_does_not_compute_the_basin_again(tmp_path, monkeypatch) -> None:
    def refuse(*_args, **_kwargs):
        raise AssertionError("the budget zone computed the basin of D again")

    write_descent_sidecar(grid_descent(TOP), tmp_path, "model", basin=_basin())
    monkeypatch.setattr(core_descent, "descent_basin", refuse)
    monkeypatch.setattr(catchment_basin, "descent_basin", refuse)

    np.testing.assert_array_equal(_zone(tmp_path), _basin().mask)


def test_the_largest_basin_of_a_synthetic_domain_is_no_zone(tmp_path, caplog) -> None:
    write_descent_sidecar(grid_descent(TOP), tmp_path, "model", basin=_basin("largest_basin"))

    with caplog.at_level(logging.INFO):
        zone = _zone(tmp_path)

    assert zone is None
    assert "polygon_centroid" not in caplog.text


@pytest.mark.parametrize(
    ("make_sidecar", "reason"),
    [
        pytest.param(lambda folder: None, "no descent sidecar", id="no_sidecar"),
        pytest.param(
            lambda folder: write_descent_sidecar(grid_descent(TOP), folder, "model"),
            "a sidecar written before the basin was stored",
            id="before_the_basin",
        ),
    ],
)
def test_a_build_without_a_basin_keeps_the_old_support_and_says_so(
    tmp_path, caplog, make_sidecar, reason
) -> None:
    make_sidecar(tmp_path)

    with caplog.at_level(logging.INFO):
        zone = _zone(tmp_path)

    assert zone is None
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings == [
        f"Budget zone 'catchment' for sim sim: the build left no basin of D ({reason}), so the "
        "zone keeps the old support 'polygon_centroid'."
    ]


def test_a_basin_of_another_size_than_the_mesh_is_not_used(tmp_path, caplog) -> None:
    write_descent_sidecar(grid_descent(TOP), tmp_path, "model", basin=_basin())

    with caplog.at_level(logging.INFO):
        zone = Modflow6OutputAdapter()._catchment_cell_mask(
            "sim", _NoStore(), tmp_path, n_cells=N_CELLS + 1
        )

    assert zone is None
    assert "a basin of 9 cells on a mesh of 10" in caplog.text
