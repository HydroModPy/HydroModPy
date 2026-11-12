"""The extractors hand the build's descent sidecar to the run store, or say they could not.

Both backends call one helper right after the mesh. A missing sidecar is an INFO
line and no array; a sidecar that does not fit the mesh is a warning that names
what reads D. Neither may cost the mesh that was already written. The basin of D
travels in the sidecar and is stored beside D with its outlet; a sidecar written
before the basin stores D alone.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.catchment.drainage.descent import BASIN_VERSION, DescentBasin
from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr
from hydromodpy.solver.modflow_common.descent_store import (
    write_descent_sidecar,
    write_descent_sidecar_to_store,
)
from hydromodpy.solver.modflow_nwt.extractors.flow import ModflowNwtOutputAdapter
from tests._helpers.descent_cases import grid_descent
from tests._helpers.ugrid_meshes import quad_mesh

TOP = np.array([[5.0, 4.0, 3.0], [4.0, 1.0, 2.0], [6.0, 5.0, 4.0]])
N_CELLS = TOP.size


@pytest.fixture
def store(tmp_path: Path):
    handle = SimulationZarr.create(tmp_path / "run.zarr", n_cells=N_CELLS, n_layers=1)
    vertices, connectivity = quad_mesh(3, 3)
    handle.write_mesh(
        vertices, connectivity, np.tile([[10.0], [0.0]], (1, N_CELLS)), topography=TOP.ravel()
    )
    yield handle
    handle.close()


def basin_of_four_cells() -> DescentBasin:
    mask = np.zeros(N_CELLS, dtype=bool)
    mask[[3, 4, 5, 7]] = True
    return DescentBasin(
        mask=mask, outlet=4, rule="near_point", area_m2=4.0e4, seeded_at_outlet=True
    )


def test_basin_is_stored_beside_d_with_its_outlet(store, tmp_path) -> None:
    basin = basin_of_four_cells()
    write_descent_sidecar(grid_descent(TOP), tmp_path, "model", basin=basin)

    written = write_descent_sidecar_to_store(store, tmp_path, sim_id="s", n_cells=N_CELLS)

    assert written
    array = store.root["mesh"]["descent_basin"]
    np.testing.assert_array_equal(array[:], basin.mask)
    attrs = dict(array.attrs)
    assert attrs["descent_outlet"] == 4
    assert attrs["basin_rule"] == "near_point"
    assert attrs["basin_area_m2"] == pytest.approx(4.0e4)
    assert attrs["basin_seeded_at_outlet"] is True
    assert attrs["basin_version"] == BASIN_VERSION


def test_sidecar_of_another_mesh_warns_and_keeps_the_mesh(store, tmp_path, caplog) -> None:
    write_descent_sidecar(grid_descent(np.arange(16.0).reshape(4, 4)[::-1]), tmp_path, "model")

    with caplog.at_level(logging.WARNING):
        written = write_descent_sidecar_to_store(store, tmp_path, sim_id="s", n_cells=N_CELLS)

    assert not written
    assert "descent_receiver" not in store.root["mesh"]
    np.testing.assert_array_equal(store.root["mesh"]["topography"][:], TOP.ravel())
    warning = next(r for r in caplog.records if r.levelno == logging.WARNING)
    assert "flow direction map" in warning.getMessage()


def test_unreadable_sidecar_warns(store, tmp_path, caplog) -> None:
    (tmp_path / "model.descent.npz").write_bytes(b"not an archive")

    with caplog.at_level(logging.WARNING):
        written = write_descent_sidecar_to_store(store, tmp_path, sim_id="s", n_cells=N_CELLS)

    assert not written
    assert any(r.levelno == logging.WARNING for r in caplog.records)


class Handle:
    """Hands out ``store`` to an extractor that closes what it opens."""

    def __init__(self, store: SimulationZarr) -> None:
        self._store = store

    def __getattr__(self, name: str):
        return getattr(self._store, name)

    def close(self) -> None:
        return None


def test_nwt_extractor_stores_the_descent_after_the_mesh(tmp_path) -> None:
    flopy = pytest.importorskip("flopy")
    model = flopy.modflow.Modflow("nwt", model_ws=str(tmp_path), version="mfnwt")
    flopy.modflow.ModflowDis(
        model, nlay=1, nrow=3, ncol=3, delr=1.0, delc=1.0, top=TOP, botm=TOP.min() - 10.0
    )
    flopy.modflow.ModflowBas(model, ibound=1, strt=TOP)
    model.write_input()
    descent = grid_descent(TOP)
    write_descent_sidecar(descent, tmp_path, "nwt")
    store = SimulationZarr.create(tmp_path / "run.zarr", n_cells=N_CELLS, n_layers=1)
    try:
        ModflowNwtOutputAdapter()._write_surface_elevation(
            "sim",
            SimpleNamespace(open_zarr=lambda sim_id: Handle(store)),
            tmp_path,
            "nwt",
            1,
            3,
            3,
        )

        mesh = store.root["mesh"]
        np.testing.assert_array_equal(mesh["topography"][:], TOP.ravel())
        np.testing.assert_array_equal(mesh["descent_receiver"][:], descent.receiver)
    finally:
        store.close()
