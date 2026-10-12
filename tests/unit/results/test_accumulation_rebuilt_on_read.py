"""``accumulation_flux`` and ``release_accumulation_flux`` are rebuilt on read.

Both route a local flux down the descent D of the run. D is the one stored
under ``mesh/``; a run stored before D was gets one rebuilt from its stored
top, once per store, and a run with neither serves no accumulation at all.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.core.descent import descent_from_stored_mesh
from hydromodpy.core.field_routing import accumulate_on_downhill_graph
from hydromodpy.results.derive import accumulation
from hydromodpy.results.derive.accumulation import (
    accumulation_flux_available,
    accumulation_flux_rows,
    release_accumulation_flux_available,
    release_accumulation_flux_rows,
)
from hydromodpy.results.zarr_store import SimulationZarr
from tests._helpers.ugrid_meshes import quad_mesh
from tests.unit.core._descent_meshes import grid_descent

NROW = NCOL = 4
N_CELLS = NROW * NCOL
N_STEPS = 5
TOP = np.array(
    [
        [9.0, 8.0, 7.0, 8.0],
        [8.0, 5.0, 4.0, 7.0],
        [7.0, 4.0, 1.0, 6.0],
        [6.0, 5.0, 4.0, 5.0],
    ]
)


@pytest.fixture(autouse=True)
def _empty_graph_cache():
    accumulation._graphs.clear()
    yield
    accumulation._graphs.clear()


def _budget() -> dict[str, np.ndarray]:
    rng = np.random.default_rng(3)
    return {
        "drain": -rng.uniform(0.0, 2e-3, (N_STEPS, 1, N_CELLS)),
        "stream": rng.uniform(-3e-3, 1e-3, (N_STEPS, 1, N_CELLS)),
    }


def _store(
    tmp_path: Path,
    budget: dict[str, np.ndarray] | None = None,
    *,
    descent: bool = False,
    mesh: bool = True,
) -> SimulationZarr:
    store = SimulationZarr.create(tmp_path / "run.zarr", n_cells=N_CELLS, n_layers=1)
    if mesh:
        vertices, connectivity = quad_mesh(NROW, NCOL)
        store.write_mesh(vertices, connectivity, np.array([10.0, 0.0]), topography=TOP.ravel())
    if descent:
        built = grid_descent(TOP)
        store.write_descent(
            receiver=built.receiver,
            surface=built.surface,
            base_level=built.base_level,
            constant_head=built.constant_head,
            raised=built.raised,
            channel=built.channel,
            pinned=built.pinned,
            attrs={},
        )
    store.write_field_stack("head", np.full((N_STEPS, 1, N_CELLS), 5.0))
    for name, values in (budget if budget is not None else _budget()).items():
        store.write_field_stack(name, values, subgroup="budget")
    return store


def _stored(store: SimulationZarr, name: str) -> np.ndarray:
    """A budget term as the store holds it (single precision), as ``(time, cell)``."""
    return np.asarray(store.root["budget"][name][:], dtype="float64")[:, 0, :]


def test_with_d_stored_the_drain_is_routed_on_d(tmp_path: Path) -> None:
    store = _store(tmp_path, descent=True)
    graph = grid_descent(TOP).metric.graph

    rows = accumulation_flux_rows(store.root, 0, N_STEPS)

    assert rows.shape == (N_STEPS, N_CELLS)
    local = np.maximum(-_stored(store, "drain"), 0.0)
    np.testing.assert_array_equal(rows, accumulate_on_downhill_graph(graph, local))
    store.close()


def test_a_stored_d_is_used_even_when_the_mesh_would_rebuild_another(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _store(tmp_path, descent=True)

    def refuse(*args, **kwargs):
        raise AssertionError("D is stored, nothing should be rebuilt")

    monkeypatch.setattr(accumulation, "descent_from_stored_mesh", refuse)

    accumulation_flux_rows(store.root, 0, 2)
    store.close()


def test_without_d_the_graph_is_rebuilt_once_for_a_range_and_for_single_steps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    budget = _budget()
    store = _store(tmp_path, budget)
    path = store.root.store.root
    builds: list[int] = []

    def counted(*args, **kwargs):
        builds.append(1)
        return descent_from_stored_mesh(*args, **kwargs)

    monkeypatch.setattr(accumulation, "descent_from_stored_mesh", counted)

    accumulation_flux_rows(store.root, 0, N_STEPS)
    assert len(builds) == 1
    store.close()

    import zarr

    for step in range(N_STEPS):
        handle = zarr.open_group(path, mode="r")
        accumulation_flux_rows(handle, step, step + 1)
        release_accumulation_flux_rows(handle, step, step + 1)
    assert len(builds) == 1


def test_the_rebuild_logs_one_debug_line_per_build(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = _store(tmp_path)

    with caplog.at_level("DEBUG"):
        for step in range(3):
            accumulation_flux_rows(store.root, step, step + 1)

    lines = [r for r in caplog.records if "stores no descent" in r.getMessage()]
    assert len(lines) == 1
    store.close()


def test_a_rewritten_top_does_not_reuse_the_old_graph(tmp_path: Path) -> None:
    store = _store(tmp_path)
    first = accumulation_flux_rows(store.root, 0, 1)
    store.root["mesh"]["topography"][:] = TOP.ravel()[::-1]

    second = accumulation_flux_rows(store.root, 0, 1)

    assert not np.array_equal(first, second, equal_nan=True)
    store.close()


def test_without_d_and_without_topology_the_field_is_unavailable(tmp_path: Path) -> None:
    store = _store(tmp_path, mesh=False)

    assert not accumulation_flux_available(store.root)
    assert not release_accumulation_flux_available(store.root)
    with pytest.raises(KeyError):
        accumulation_flux_rows(store.root, 0, 1)
    with pytest.raises(KeyError):
        release_accumulation_flux_rows(store.root, 0, 1)
    store.close()


def test_a_run_without_head_or_drain_is_unavailable(tmp_path: Path) -> None:
    store = _store(tmp_path, {"recharge": np.zeros((N_STEPS, 1, N_CELLS))})

    assert not accumulation_flux_available(store.root)
    assert not release_accumulation_flux_available(store.root)
    with pytest.raises(KeyError):
        accumulation_flux_rows(store.root, 0, 1)
    store.close()


def test_a_stream_only_run_serves_the_release_accumulation_only(tmp_path: Path) -> None:
    store = _store(tmp_path, {"stream": _budget()["stream"]})

    assert not accumulation_flux_available(store.root)
    assert release_accumulation_flux_available(store.root)
    store.close()


def test_a_single_step_equals_the_matching_row_of_a_range(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for rows_of in (accumulation_flux_rows, release_accumulation_flux_rows):
        whole = rows_of(store.root, 0, N_STEPS)
        for step in range(N_STEPS):
            np.testing.assert_array_equal(rows_of(store.root, step, step + 1)[0], whole[step])
        np.testing.assert_array_equal(rows_of(store.root, 1, 4), whole[1:4])
    store.close()


def test_an_empty_range_has_no_row(tmp_path: Path) -> None:
    store = _store(tmp_path)

    assert accumulation_flux_rows(store.root, 2, 2).shape == (0, N_CELLS)
    assert release_accumulation_flux_rows(store.root, 3, 1).shape == (0, N_CELLS)
    store.close()


def test_the_release_accumulation_routes_every_release_path(tmp_path: Path) -> None:
    store = _store(tmp_path, descent=True)
    graph = grid_descent(TOP).metric.graph
    local = np.maximum(-_stored(store, "drain"), 0.0) + np.maximum(-_stored(store, "stream"), 0.0)

    rows = release_accumulation_flux_rows(store.root, 0, N_STEPS)

    np.testing.assert_allclose(rows, accumulate_on_downhill_graph(graph, local), rtol=0, atol=1e-15)
    store.close()


def test_the_drain_to_mover_record_is_added_to_the_drain(tmp_path: Path) -> None:
    budget = _budget()
    mover = -np.random.default_rng(5).uniform(0.0, 1e-3, (N_STEPS, 1, N_CELLS))
    store = _store(tmp_path, {**budget, "drain_to_mover": mover}, descent=True)
    graph = grid_descent(TOP).metric.graph
    local = np.maximum(-(_stored(store, "drain") + _stored(store, "drain_to_mover")), 0.0)

    rows = accumulation_flux_rows(store.root, 0, N_STEPS)

    np.testing.assert_array_equal(rows, accumulate_on_downhill_graph(graph, local))
    store.close()


def test_a_run_with_only_the_mover_still_serves_the_accumulation(tmp_path: Path) -> None:
    mover = -np.random.default_rng(5).uniform(0.0, 1e-3, (N_STEPS, 1, N_CELLS))
    store = _store(tmp_path, {"drain_to_mover": mover}, descent=True)

    assert accumulation_flux_available(store.root)
    assert accumulation_flux_rows(store.root, 0, 1).shape == (1, N_CELLS)
    store.close()


def test_negative_and_nan_cells_are_clamped_before_routing(tmp_path: Path) -> None:
    drain = -np.ones((2, 1, N_CELLS)) * 1e-3
    drain[0, 0, 0] = 5e-3
    drain[0, 0, 1] = np.nan
    drain[1, 0, 2] = np.nan
    store = _store(tmp_path, {"drain": drain}, descent=True)
    graph = grid_descent(TOP).metric.graph
    local = np.maximum(-np.nan_to_num(_stored(store, "drain"), nan=0.0), 0.0)

    rows = accumulation_flux_rows(store.root, 0, 2)

    np.testing.assert_array_equal(rows, accumulate_on_downhill_graph(graph, local))
    assert np.isfinite(rows[:, graph.active]).all()
    assert (rows[:, graph.active] >= 0.0).all()
    store.close()


@pytest.mark.parametrize("descent", [True, False])
def test_a_tiny_pass_size_gives_the_one_pass_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, descent: bool
) -> None:
    from hydromodpy.results.derive import virtual_fields

    store = _store(tmp_path, descent=descent)
    one_pass = {
        rows_of: rows_of(store.root, 0, N_STEPS)
        for rows_of in (accumulation_flux_rows, release_accumulation_flux_rows)
    }
    builds: list[int] = []
    real_graph = accumulation._graph

    def counted(*args, **kwargs):
        builds.append(1)
        return real_graph(*args, **kwargs)

    monkeypatch.setattr(accumulation, "_graph", counted)
    monkeypatch.setattr(virtual_fields, "ROWS_PER_PASS_ELEMENTS", N_CELLS)

    for rows_of, expected in one_pass.items():
        builds.clear()
        np.testing.assert_array_equal(rows_of(store.root, 0, N_STEPS), expected)
        np.testing.assert_array_equal(rows_of(store.root, 1, 4), expected[1:4])
        assert len(builds) == 2
    store.close()


@pytest.mark.parametrize("array", ["vertices", "face_node_connectivity"])
def test_a_rewritten_mesh_does_not_reuse_the_old_graph(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, array: str
) -> None:
    store = _store(tmp_path)
    builds: list[int] = []

    def counted(*args, **kwargs):
        builds.append(1)
        return descent_from_stored_mesh(*args, **kwargs)

    monkeypatch.setattr(accumulation, "descent_from_stored_mesh", counted)
    accumulation_flux_rows(store.root, 0, 1)
    accumulation_flux_rows(store.root, 0, 1)
    assert len(builds) == 1

    mesh = store.root["mesh"]
    mesh[array][:] = (
        mesh[array][:][..., ::-1] if array == "face_node_connectivity" else (mesh[array][:] * 2.0)
    )

    accumulation_flux_rows(store.root, 0, 1)
    assert len(builds) == 2
    store.close()


def test_a_stored_d_of_another_size_is_unavailable(tmp_path: Path) -> None:
    store = _store(tmp_path)
    mesh = store.root["mesh"]
    mesh.create_array("descent_receiver", data=np.full(N_CELLS + 3, -1, dtype="int64"))
    mesh.create_array("descent_surface", data=np.zeros(N_CELLS + 3))

    assert not accumulation_flux_available(store.root)
    assert not release_accumulation_flux_available(store.root)
    with pytest.raises(KeyError):
        accumulation_flux_rows(store.root, 0, 1)
    with pytest.raises(KeyError):
        release_accumulation_flux_rows(store.root, 0, 1)
    store.close()
