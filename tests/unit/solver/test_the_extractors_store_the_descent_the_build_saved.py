"""The extractors hand the build's descent sidecar to the run store, or say they could not.

Both backends call one helper right after the mesh. A missing sidecar is an INFO
line and no array; a sidecar that does not fit the mesh is a warning that names
what reads D. Neither may cost the mesh that was already written.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.results.zarr_store import SimulationZarr
from hydromodpy.solver.modflow6.support.computational_top import GROUND_SIDECAR_SUFFIX
from hydromodpy.solver.modflow_common.descent_store import write_descent_sidecar_to_store
from hydromodpy.solver.modflow_common.mesh_descent import write_descent_sidecar
from tests._helpers.ugrid_meshes import quad_mesh
from tests.unit.core._descent_meshes import grid_descent

TOP = np.array([[5.0, 4.0, 3.0], [4.0, 1.0, 2.0], [6.0, 5.0, 4.0]])
N_CELLS = TOP.size


@pytest.fixture
def store(tmp_path: Path):
    handle = SimulationZarr.create(tmp_path / "run.zarr", n_cells=N_CELLS, n_layers=1)
    vertices, connectivity = quad_mesh(3, 3)
    handle.write_mesh(vertices, connectivity, np.array([10.0, 0.0]), topography=TOP.ravel())
    yield handle
    handle.close()


def test_the_sidecar_the_build_left_lands_under_mesh(store, tmp_path) -> None:
    descent = grid_descent(TOP)
    write_descent_sidecar(descent, tmp_path, "model")

    written = write_descent_sidecar_to_store(store, tmp_path, sim_id="s", n_cells=N_CELLS)

    assert written
    mesh = store.root["mesh"]
    np.testing.assert_array_equal(mesh["descent_receiver"][:], descent.receiver)
    np.testing.assert_array_equal(mesh["descent_surface"][:], descent.surface)
    attrs = dict(mesh["descent_receiver"].attrs)
    assert attrs["adjacency"] == "shared_nodes"
    assert attrs["n_raised"] == descent.n_raised
    assert attrs["n_channel"] == 0
    assert attrs["n_pinned"] == 0
    assert "n_lake_flooded" in attrs
    assert attrs["epsilon"] > 0.0


def test_without_a_sidecar_nothing_is_written_and_info_says_so(store, tmp_path, caplog) -> None:
    with caplog.at_level(logging.INFO):
        written = write_descent_sidecar_to_store(store, tmp_path, sim_id="old", n_cells=N_CELLS)

    assert not written
    assert "descent_receiver" not in store.root["mesh"]
    assert any(
        r.levelno == logging.INFO and "no descent sidecar" in r.getMessage() for r in caplog.records
    )
    assert not any(r.levelno >= logging.WARNING for r in caplog.records)


def test_a_sidecar_for_another_mesh_is_a_warning_and_leaves_the_mesh_alone(
    store, tmp_path, caplog
) -> None:
    write_descent_sidecar(grid_descent(np.arange(16.0).reshape(4, 4)[::-1]), tmp_path, "model")

    with caplog.at_level(logging.WARNING):
        written = write_descent_sidecar_to_store(store, tmp_path, sim_id="s", n_cells=N_CELLS)

    assert not written
    assert "descent_receiver" not in store.root["mesh"]
    np.testing.assert_array_equal(store.root["mesh"]["topography"][:], TOP.ravel())
    warning = next(r for r in caplog.records if r.levelno == logging.WARNING)
    assert "flow direction map" in warning.getMessage()


def test_an_unreadable_sidecar_is_a_warning_not_a_crash(store, tmp_path, caplog) -> None:
    (tmp_path / "model.descent.npz").write_bytes(b"not an archive")

    with caplog.at_level(logging.WARNING):
        written = write_descent_sidecar_to_store(store, tmp_path, sim_id="s", n_cells=N_CELLS)

    assert not written
    assert any(r.levelno == logging.WARNING for r in caplog.records)


class _Handle:
    """Hands out ``store`` to an extractor that closes what it opens."""

    def __init__(self, store: SimulationZarr) -> None:
        self._store = store

    def __getattr__(self, name: str):
        return getattr(self._store, name)

    def close(self) -> None:
        return None


def test_the_nwt_extractor_stores_the_descent_right_after_the_mesh(tmp_path) -> None:
    flopy = pytest.importorskip("flopy")
    from types import SimpleNamespace

    from hydromodpy.solver.modflow_nwt.extractors.flow import ModflowNwtOutputAdapter

    model = flopy.modflow.Modflow("nwt", model_ws=str(tmp_path), version="mfnwt")
    flopy.modflow.ModflowDis(
        model, nlay=1, nrow=3, ncol=3, delr=1.0, delc=1.0, top=TOP, botm=TOP.min() - 10.0
    )
    model.write_input()
    descent = grid_descent(TOP)
    write_descent_sidecar(descent, tmp_path, "nwt")
    store = SimulationZarr.create(tmp_path / "run.zarr", n_cells=N_CELLS, n_layers=1)
    try:
        ModflowNwtOutputAdapter()._write_surface_elevation(
            "sim",
            SimpleNamespace(open_zarr=lambda sim_id: _Handle(store)),
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


def test_the_mf6_extractor_stores_the_descent_right_after_the_mesh(tmp_path, monkeypatch) -> None:
    pytest.importorskip("flopy")
    from types import SimpleNamespace

    import flopy.mf6.utils

    from hydromodpy.solver.modflow6.extractors.flow import Modflow6OutputAdapter

    xs, ys = np.meshgrid(np.arange(4.0), np.arange(4.0))

    class _FakeGrid:
        grid_type = "dis"
        top1d = TOP.ravel()
        bot1d = TOP.ravel() - 10.0
        modelgrid = SimpleNamespace(xvertices=xs, yvertices=ys)

        def __init__(self, path: str) -> None:
            del path

    monkeypatch.setattr(flopy.mf6.utils, "MfGrdFile", _FakeGrid)
    (tmp_path / "m.dis.grb").write_bytes(b"")
    np.savez(tmp_path / f"m{GROUND_SIDECAR_SUFFIX}", ground=TOP.ravel())
    descent = grid_descent(TOP)
    write_descent_sidecar(descent, tmp_path, "m")
    store = SimulationZarr.create(tmp_path / "run.zarr", n_cells=N_CELLS, n_layers=1)
    try:
        Modflow6OutputAdapter()._write_surface_elevation(
            "sim",
            SimpleNamespace(open_zarr=lambda sim_id: _Handle(store)),
            tmp_path,
            "m",
            1,
            N_CELLS,
            grid_shape=(3, 3),
        )

        mesh = store.root["mesh"]
        np.testing.assert_array_equal(mesh["topography"][:], TOP.ravel())
        np.testing.assert_array_equal(mesh["descent_receiver"][:], descent.receiver)
    finally:
        store.close()
