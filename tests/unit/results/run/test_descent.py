"""The descent D of a run, stored under ``mesh/`` and read back without a rebuild.

Seven static arrays are never rounded, with the build report on the receiver array. A run may
also store the basin of D with its outlet, and the dam feet (int64 cell ids, possibly none).
The layout is additive. A run sealed before D was stored gets one rebuilt from its stored top
(m), announced once.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.catchment.drainage.descent import Descent
from hydromodpy.catchment.drainage.graph import accumulate_on_downhill_graph
from hydromodpy.results.run import descent as run_descent_module
from hydromodpy.results.run.contracts import Mesh
from hydromodpy.results.run.descent import RunDescent, load_descent
from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr
from hydromodpy.solver.modflow_common.descent_store import (
    write_descent_sidecar,
    write_descent_sidecar_to_store,
)
from tests._helpers.descent_cases import grid_descent
from tests._helpers.ugrid_meshes import quad_mesh

N_ROW = N_COL = 4
N_CELLS = N_ROW * N_COL
TOP = np.array(  # m
    [
        [9.0, 8.0, 7.0, 8.0],
        [8.0, 5.0, 4.0, 7.0],
        [7.0, 4.0, 1.0, 6.0],
        [6.0, 5.0, 4.0, 5.0],
    ]
)
PIT = 10  # the lowest cell, with a constant head

BASIN_CELLS = [5, 6, 9, 10]
BASIN_OUTLET = PIT

# A 3 x 3 grid for the dam feet.
TOP_3X3 = np.array([[5.0, 4.0, 3.0], [4.0, 1.0, 2.0], [6.0, 5.0, 4.0]])
N_CELLS_3X3 = TOP_3X3.size


def built_descent():
    """D as a build makes it, with a constant head in the pit: no rebuild from the top can."""
    base_level = np.zeros(N_CELLS, dtype=bool)
    base_level[PIT] = True
    return grid_descent(TOP, base_level=base_level)


def attrs_of(descent):
    return {
        "adjacency": "shared_nodes",
        "epsilon": 1.0e-4,
        "n_raised": descent.n_raised,
        "max_raise_m": descent.max_raise_m,
        "n_lake_flooded": descent.n_lake_flooded,
        "max_lake_flood_m": descent.max_lake_flood_m,
        "n_pinned_raised": descent.n_pinned_raised,
        "max_pinned_raise_m": descent.max_pinned_raise_m,
    }


def write_arrays(store, descent: Descent, **extra):
    """Write the seven arrays of D, with any of ``attrs``, ``basin``, ``basin_attrs``, ``dam_foot``."""
    kwargs = {"attrs": attrs_of(descent)} | extra
    store.write_descent(
        receiver=descent.receiver,
        surface=descent.surface,
        base_level=descent.base_level,
        constant_head=descent.constant_head,
        raised=descent.raised,
        channel=descent.channel,
        pinned=descent.pinned,
        **kwargs,
    )


def basin_mask():
    mask = np.zeros(N_CELLS, dtype=bool)
    mask[BASIN_CELLS] = True
    return mask


def basin_attrs(**changes):
    attrs = {
        "descent_outlet": BASIN_OUTLET,
        "basin_rule": "within_polygon",
        "basin_area_m2": 4.0,
        "basin_seeded_at_outlet": True,
        "basin_version": 1,
    }
    return attrs | changes


def write_mesh(store):
    vertices, connectivity = quad_mesh(N_ROW, N_COL)
    store.write_mesh(vertices, connectivity, np.array([10.0, 0.0]), topography=TOP.ravel())
    return vertices, connectivity


def run_over(store, vertices, connectivity, top, sim_id="sim-descent"):
    """A run whose catalog hands out ``store`` and whose mesh is the one written."""
    handle = SimpleNamespace(root=store.root, close=lambda: None)
    return SimpleNamespace(
        sim_id=sim_id,
        _sim_id=sim_id,
        _catalog=SimpleNamespace(open_zarr=lambda sim_id: handle),
        mesh=Mesh(
            vertices=vertices,
            face_node_connectivity=connectivity,
            z_interfaces=np.array([10.0, 0.0]),
            topography=top.ravel(),
        ),
    )


@pytest.fixture
def store(tmp_path):
    handle = SimulationZarr.create(tmp_path / "run.zarr", n_cells=N_CELLS, n_layers=1)
    yield handle
    handle.close()


@pytest.fixture
def store_3x3(tmp_path):
    handle = SimulationZarr.create(tmp_path / "run.zarr", n_cells=N_CELLS_3X3, n_layers=1)
    vertices, connectivity = quad_mesh(3, 3)
    handle.write_mesh(vertices, connectivity, np.array([10.0, 0.0]), topography=TOP_3X3.ravel())
    yield handle
    handle.close()


def write_dam_feet(store_3x3, dam_foot):
    descent = grid_descent(TOP_3X3)
    extra = {} if dam_foot is None else {"dam_foot": dam_foot}
    write_arrays(
        store_3x3, descent, attrs={"adjacency": "shared_nodes", "epsilon": 1.0e-4}, **extra
    )


def run_over_3x3(store_3x3):
    vertices, connectivity = quad_mesh(3, 3)
    return run_over(store_3x3, vertices, connectivity, TOP_3X3, sim_id="sim-dam")


def forbid_loading_d(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("D must be neither loaded nor rebuilt to read it")

    for name in ("load_descent", "_rebuild", "_read_stored"):
        monkeypatch.setattr(run_descent_module, name, refuse)


def test_arrays_written_under_mesh(store):
    descent = built_descent()
    write_mesh(store)

    write_arrays(store, descent)

    mesh = store.root["mesh"]
    expected = {
        "descent_receiver": np.int64,
        "descent_surface": np.float64,
        "descent_base_level": np.bool_,
        "descent_constant_head": np.bool_,
        "descent_raised": np.bool_,
        "descent_channel": np.bool_,
        "descent_pinned": np.bool_,
    }
    for name, dtype in expected.items():
        assert mesh[name].dtype == dtype, name
        assert mesh[name].shape == (N_CELLS,), name
    attrs = dict(mesh["descent_receiver"].attrs)
    assert attrs["adjacency"] == "shared_nodes"
    assert attrs["n_raised"] == descent.n_raised
    assert attrs["max_raise_m"] == pytest.approx(descent.max_raise_m)


def test_stored_descent_reads_back(store):
    descent = built_descent()
    vertices, connectivity = write_mesh(store)
    write_arrays(store, descent)

    view = load_descent(run_over(store, vertices, connectivity, TOP))

    assert not view.rebuilt
    assert view.adjacency == "shared_nodes"
    assert view.diagonal_neighbors
    assert view.epsilon == pytest.approx(1.0e-4)
    assert view.report["n_raised"] == descent.n_raised
    np.testing.assert_array_equal(view.receiver, descent.receiver)
    np.testing.assert_array_equal(view.surface, descent.surface)
    np.testing.assert_array_equal(view.base_level, descent.base_level)
    np.testing.assert_array_equal(view.constant_head, descent.constant_head)
    np.testing.assert_array_equal(view.raised, descent.raised)
    assert view.constant_head[PIT] and view.receiver[PIT] == -1
    flux = np.arange(1.0, N_CELLS + 1.0)
    np.testing.assert_array_equal(
        accumulate_on_downhill_graph(view.graph, flux),
        accumulate_on_downhill_graph(descent.metric.graph, flux),
    )


def test_old_run_announces_rebuild_once(store, caplog):
    vertices, connectivity = write_mesh(store)
    holder = RunDescent.of_run(run_over(store, vertices, connectivity, TOP))

    with caplog.at_level(logging.INFO):
        for name in ("receiver", "surface", "graph"):
            assert getattr(holder, name) is not None

    lines = [r for r in caplog.records if "predates the stored descent" in r.getMessage()]
    assert len(lines) == 1
    assert lines[0].levelno == logging.INFO


def test_loaded_lazily_and_once(store):
    descent = built_descent()
    vertices, connectivity = write_mesh(store)
    write_arrays(store, descent)
    opened = []
    run = run_over(store, vertices, connectivity, TOP)
    handle = run._catalog.open_zarr("x")
    run._catalog.open_zarr = lambda sim_id: opened.append(sim_id) or handle
    holder = RunDescent.of_run(run)
    assert opened == []

    for name in ("receiver", "graph"):
        assert getattr(holder, name) is not None

    assert opened == ["sim-descent"]


def test_unknown_attribute():
    holder = RunDescent(lambda: pytest.fail("loading must not happen for an unknown name"))

    with pytest.raises(AttributeError):
        getattr(holder, "nothing_of_the_kind")  # noqa: B009


def test_basin_array_and_outlet(store):
    write_mesh(store)

    write_arrays(store, built_descent(), basin=basin_mask(), basin_attrs=basin_attrs())

    array = store.root["mesh"]["descent_basin"]
    assert array.dtype == np.bool_
    assert array.shape == (N_CELLS,)
    assert np.flatnonzero(array[:]).tolist() == BASIN_CELLS
    attrs = dict(array.attrs)
    assert attrs["descent_outlet"] == BASIN_OUTLET
    assert attrs["basin_rule"] == "within_polygon"
    assert attrs["basin_area_m2"] == pytest.approx(4.0)
    assert attrs["basin_seeded_at_outlet"] is True
    assert attrs["basin_version"] == 1


def test_basin_read_without_loading_d(store, monkeypatch):
    vertices, connectivity = write_mesh(store)
    run = run_over(store, vertices, connectivity, TOP)
    forbid_loading_d(monkeypatch)
    holder = RunDescent.of_run(run)

    assert holder.stored_basin() is None

    write_arrays(store, built_descent(), basin=basin_mask(), basin_attrs=basin_attrs())
    holder = RunDescent.of_run(run)
    basin = holder.stored_basin()
    np.testing.assert_array_equal(basin.mask, basin_mask())
    assert basin.attrs["descent_outlet"] == BASIN_OUTLET


def test_rebuilt_descent_has_no_basin(store):
    vertices, connectivity = write_mesh(store)

    view = load_descent(run_over(store, vertices, connectivity, TOP))

    assert view.rebuilt
    assert view.basin is None


def test_store_without_feet(store_3x3):
    write_dam_feet(store_3x3, None)
    del store_3x3.root["mesh"]["descent_dam_foot"]

    view = load_descent(run_over_3x3(store_3x3))

    assert not view.rebuilt
    assert view.dam_foot.size == 0


def test_sidecar_feet_copied(store_3x3, tmp_path):
    write_descent_sidecar(grid_descent(TOP_3X3), tmp_path, "model", dam_foot_cells={"lake": 5})

    written = write_descent_sidecar_to_store(store_3x3, tmp_path, sim_id="s", n_cells=N_CELLS_3X3)

    assert written
    assert load_descent(run_over_3x3(store_3x3)).dam_foot.tolist() == [5]


def test_stored_feet_without_loading_d(store_3x3, monkeypatch):
    write_dam_feet(store_3x3, [2, 7])
    forbid_loading_d(monkeypatch)

    feet = RunDescent.of_run(run_over_3x3(store_3x3)).dam_foot

    assert feet.tolist() == [2, 7]
    assert not feet.flags.writeable


def test_old_store_feet_no_rebuild(store_3x3, monkeypatch, caplog):
    # No descent_* array at all: a run sealed before D was stored.
    store_3x3_run = run_over_3x3(store_3x3)
    forbid_loading_d(monkeypatch)

    with caplog.at_level("INFO"):
        feet = RunDescent.of_run(store_3x3_run).dam_foot

    assert feet.size == 0
    assert "predates the stored descent" not in caplog.text


def test_array_size_mismatch_refused(store):
    descent = built_descent()
    write_mesh(store)

    with pytest.raises(ValueError, match="share one size"):
        store.write_descent(
            receiver=descent.receiver[:-1],
            surface=descent.surface,
            base_level=descent.base_level,
            constant_head=descent.constant_head,
            raised=descent.raised,
            channel=descent.channel,
            pinned=descent.pinned,
            attrs={},
        )


def test_attrs_without_basin_refused(store):
    with pytest.raises(ValueError, match="without a basin"):
        write_arrays(store, built_descent(), attrs={}, basin_attrs=basin_attrs())


def test_foot_outside_mesh_refused(store_3x3):
    with pytest.raises(ValueError, match="not a cell of the mesh"):
        write_dam_feet(store_3x3, [N_CELLS_3X3])


# (basin mask, attributes, message)
BASIN_REFUSALS = [
    pytest.param(basin_mask()[:-1], basin_attrs(), "one value per cell", id="wrong size"),
    pytest.param(basin_mask(), {}, "descent_outlet", id="no outlet"),
    pytest.param(
        basin_mask(),
        basin_attrs(descent_outlet=0),
        "not a cell of the basin",
        id="outlet off basin",
    ),
    pytest.param(
        basin_mask(),
        basin_attrs(descent_outlet=N_CELLS),
        "not a cell of the basin",
        id="outlet off mesh",
    ),
]


@pytest.mark.parametrize(("mask", "attrs", "message"), BASIN_REFUSALS)
def test_basin_refusals(store, mask, attrs, message):
    write_mesh(store)

    with pytest.raises(ValueError, match=message):
        write_arrays(store, built_descent(), basin=mask, basin_attrs=attrs)

    assert "descent_basin" not in store.root["mesh"]
