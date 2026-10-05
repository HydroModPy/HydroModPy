"""The cells below the dams live in ``mesh/descent_dam_foot`` and ``run.descent`` reads them.

An eighth array beside the seven of D: int64 cell ids, possibly none, additive.
A store written before it (D without it) reads as having no dam foot and is not
rebuilt, and a foot outside the mesh is refused.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.results.run.contracts import Mesh
from hydromodpy.results.run.descent import RunDescent, load_descent
from hydromodpy.results.zarr_store import SimulationZarr
from hydromodpy.results.zarr_store.constants import ZARR_SCHEMA_VERSION
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


def _write(store: SimulationZarr, dam_foot) -> None:
    descent = grid_descent(TOP)
    kwargs = {} if dam_foot is None else {"dam_foot": dam_foot}
    store.write_descent(
        receiver=descent.receiver,
        surface=descent.surface,
        base_level=descent.base_level,
        constant_head=descent.constant_head,
        raised=descent.raised,
        channel=descent.channel,
        pinned=descent.pinned,
        attrs={"adjacency": "shared_nodes", "epsilon": 1.0e-4},
        **kwargs,
    )


def _run_over(store: SimulationZarr):
    vertices, connectivity = quad_mesh(3, 3)
    handle = SimpleNamespace(root=store.root, close=lambda: None)
    return SimpleNamespace(
        sim_id="sim-dam",
        _sim_id="sim-dam",
        _catalog=SimpleNamespace(open_zarr=lambda sim_id: handle),
        mesh=Mesh(
            vertices=vertices,
            face_node_connectivity=connectivity,
            z_interfaces=np.array([10.0, 0.0]),
            topography=TOP.ravel(),
        ),
    )


def test_the_feet_are_stored_as_sorted_int64_cell_ids(store) -> None:
    _write(store, [7, 2, 7])

    array = store.root["mesh"]["descent_dam_foot"]
    assert array.dtype == np.int64
    assert array[:].tolist() == [2, 7]


def test_a_run_without_a_lake_stores_an_empty_array(store) -> None:
    _write(store, None)

    assert store.root["mesh"]["descent_dam_foot"].shape == (0,)
    assert not load_descent(_run_over(store)).dam_foot.size


def test_the_view_reads_the_feet_back_read_only(store) -> None:
    _write(store, [2, 7])

    view = load_descent(_run_over(store))

    assert not view.rebuilt
    assert view.dam_foot.tolist() == [2, 7]
    assert not view.dam_foot.flags.writeable


def test_a_store_written_before_the_feet_has_none_and_is_not_rebuilt(store) -> None:
    _write(store, None)
    del store.root["mesh"]["descent_dam_foot"]

    view = load_descent(_run_over(store))

    assert not view.rebuilt
    assert view.dam_foot.size == 0


def test_a_foot_outside_the_mesh_is_refused(store) -> None:
    with pytest.raises(ValueError, match="not a cell of the mesh"):
        _write(store, [N_CELLS])


def test_storing_the_feet_does_not_move_the_schema_version(store) -> None:
    before = dict(store.root.attrs)["zarr_schema_version"]

    _write(store, [2])

    assert dict(store.root.attrs)["zarr_schema_version"] == before == ZARR_SCHEMA_VERSION


def test_the_extractor_copies_the_feet_of_the_sidecar(store, tmp_path) -> None:
    write_descent_sidecar(grid_descent(TOP), tmp_path, "model", dam_foot_cells={"lake": 5})

    written = write_descent_sidecar_to_store(store, tmp_path, sim_id="s", n_cells=N_CELLS)

    assert written
    assert load_descent(_run_over(store)).dam_foot.tolist() == [5]


def _forbid_loading_d(monkeypatch) -> None:
    from hydromodpy.results.run import descent as module

    def refuse(*args, **kwargs):
        raise AssertionError("D must be neither loaded nor rebuilt to read the dam foot")

    monkeypatch.setattr(module, "load_descent", refuse)
    monkeypatch.setattr(module, "_rebuild", refuse)
    monkeypatch.setattr(module, "_read_stored", refuse)


def test_the_redraw_reads_the_stored_feet_without_loading_d(store, monkeypatch) -> None:
    _write(store, [2, 7])
    _forbid_loading_d(monkeypatch)

    feet = RunDescent.of_run(_run_over(store)).dam_foot

    assert feet.tolist() == [2, 7]
    assert not feet.flags.writeable


def test_an_old_store_has_no_feet_and_the_redraw_does_not_rebuild_d(
    store, monkeypatch, caplog
) -> None:
    # No descent_* array at all: a run sealed before D was stored.
    _forbid_loading_d(monkeypatch)

    with caplog.at_level("INFO"):
        feet = RunDescent.of_run(_run_over(store)).dam_foot

    assert feet.size == 0
    assert "predates the stored descent" not in caplog.text
