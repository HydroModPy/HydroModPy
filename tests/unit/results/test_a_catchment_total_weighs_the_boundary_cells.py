"""A catchment total of a spatial quantity weighs each cell by its share in the polygon (D08).

``views.catchment_total`` sums a per-cell budget term over the catchment, each
face counted by ``mesh/catchment_fraction``. A run that stores the basin of D
but no fraction counts the basin whole and says so. A run with no catchment
(no basin, or only the largest basin of a synthetic domain) has no catchment
total. The outlet discharge is not one of these totals: it stays the
``catchment`` row of the budget, whole cells.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.results.derive import views
from hydromodpy.results.run.descent import read_catchment_fraction
from hydromodpy.results.zarr_store import SimulationZarr
from tests._helpers.ugrid_meshes import quad_mesh

NROW, NCOL = 2, 3
N_CELLS = NROW * NCOL
BASIN = np.array([True, True, False, True, True, False])
FRACTION = np.array([1.0, 0.5, 0.25, 1.0, 0.75, 0.0])
# m3/s per cell, two steps; exact in the compact float precision of the store.
RECHARGE = np.array(
    [
        [0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
        [0.25, 1.0, 2.0, 0.125, 0.5, 4.0],
    ]
)
DRAIN = -np.array(
    [
        [0.0, 1.0, 0.0, 0.0, 2.0, 0.0],
        [0.5, 0.0, 1.0, 0.25, 0.0, 8.0],
    ]
)


def _store(tmp_path, *, rule: str = "near_point", fraction: np.ndarray | None = FRACTION):
    path = tmp_path / "run.zarr"
    store = SimulationZarr.create(path, n_cells=N_CELLS, n_layers=1)
    try:
        vertices, connectivity = quad_mesh(NROW, NCOL, cell_size=10.0)
        store.write_mesh(vertices, connectivity, np.array([0.0, -10.0]))
        store.write_time(np.array([86400.0, 2 * 86400.0]))
        for name, values in (("recharge", RECHARGE), ("drain", DRAIN)):
            store.write_field_stack(
                name, values[:, None, :], n_timesteps=2, timestep_offset=0, subgroup="budget"
            )
        if rule is not None:
            store.write_descent(
                receiver=np.full(N_CELLS, -1, dtype=np.int64),
                surface=np.zeros(N_CELLS),
                base_level=np.zeros(N_CELLS, dtype=bool),
                constant_head=np.zeros(N_CELLS, dtype=bool),
                raised=np.zeros(N_CELLS, dtype=bool),
                channel=np.zeros(N_CELLS, dtype=bool),
                pinned=np.zeros(N_CELLS, dtype=bool),
                attrs={"adjacency": "shared_nodes"},
                basin=BASIN,
                basin_attrs={"descent_outlet": 0, "basin_rule": rule},
                catchment_fraction=fraction,
            )
    finally:
        store.close()
    return SimpleNamespace(
        sim_id="sim-total",
        _sim_id="sim-total",
        n_timesteps=2,
        _catalog=SimpleNamespace(open_zarr=lambda sim_id: SimulationZarr(path)),
    )


def test_a_boundary_cell_counts_by_its_share_in_the_polygon(tmp_path) -> None:
    run = _store(tmp_path)

    recharge = views.catchment_total(run, "recharge")
    seepage = -views.catchment_total(run, "drain", name="seepage")

    np.testing.assert_allclose(recharge.to_numpy(), RECHARGE @ FRACTION)
    np.testing.assert_allclose(seepage.to_numpy(), -DRAIN @ FRACTION)
    assert seepage.name == "seepage"
    assert list(recharge.index) == list(pd.to_datetime(["1970-01-02", "1970-01-03"]))


def test_the_fraction_reads_back_as_it_was_written(tmp_path) -> None:
    run = _store(tmp_path)

    fraction = read_catchment_fraction(run)

    np.testing.assert_array_equal(fraction, FRACTION)
    np.testing.assert_array_equal(views.catchment_weights(run), FRACTION)


def test_a_run_without_a_fraction_counts_the_basin_whole(tmp_path, caplog) -> None:
    run = _store(tmp_path, fraction=None)

    with caplog.at_level(logging.INFO):
        recharge = views.catchment_total(run, "recharge")

    assert read_catchment_fraction(run) is None
    np.testing.assert_allclose(recharge.to_numpy(), RECHARGE @ BASIN.astype(float))
    assert "count the cells of the basin of D whole" in caplog.text


@pytest.mark.parametrize(
    ("rule", "message"),
    [("largest_basin", "only the largest one of its domain"), (None, "is missing")],
    ids=["synthetic_domain", "no_basin"],
)
def test_a_run_with_no_catchment_has_no_catchment_total(tmp_path, rule, message) -> None:
    run = _store(tmp_path, rule=rule, fraction=None)

    with pytest.raises(ValueError, match=message):
        views.catchment_total(run, "recharge")
