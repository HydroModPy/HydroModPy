"""The earlier run a ``restart_from`` names is read once, on the mesh of this run.

``read_prior_state`` checks ``mesh/face_node_connectivity`` exactly and
``mesh/vertices`` to half the rounding step flopy writes, names both mesh
identities when the two differ, and only then reads the last head and the final
lake stages. A store without a mesh keeps the cell-count rule and a warning.
A run that wrote ``final_state/`` is read from it, exact in float64, whether it
is named by its folder, its ``fields.zarr`` or its ``final_state/``; a run of
HydroModPy 2.0 is read from the last step of its field store.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pytest
import zarr

from hydromodpy.core.exceptions import IncompatibleMeshError
from hydromodpy.mesh.planar.planar_cell_mesh import PlanarCellMesh
from hydromodpy.model.initial.heads import restart_start_heads
from hydromodpy.model.initial.state import PriorState
from hydromodpy.results.storage.final_state import FinalState, write_final_state
from hydromodpy.results.storage.prior_state import (
    prior_state_at,
    read_final_head,
    read_prior_state,
    read_restart_lake_stages,
    verify_restart_mesh,
)
from tests._helpers.regular_cell_meshes import regular_cell_mesh

# Lambert-93 magnitudes: flopy keeps 1e-3 m in x (3.5e5) and 1e-2 m in y (6.8e6).
_XMIN, _YMIN = 350_000.0, 6_800_000.0


def _mesh() -> PlanarCellMesh:
    return regular_cell_mesh(xmin=_XMIN, ymin=_YMIN, dx=100.0, dy=100.0, nrow=2, ncol=3)


def _store(
    path: Path,
    cell_mesh: PlanarCellMesh,
    *,
    vertices: np.ndarray | None = None,
    rows: np.ndarray | None = None,
) -> str:
    """Write the ``head`` and ``mesh/`` groups a prior run leaves, from ``cell_mesh``."""
    root = zarr.open(str(path), mode="w")
    root["head"] = np.arange(cell_mesh.n_cells, dtype=float).reshape(1, 1, -1)
    xy = cell_mesh.mesh.vertices[:, :2] if vertices is None else vertices
    group = root.create_group("mesh")
    group["vertices"] = np.column_stack([xy, np.zeros(len(xy))])
    group["face_node_connectivity"] = (
        cell_mesh.geometry.padded_connectivity if rows is None else rows
    ).astype("int32")
    group.attrs["engine"] = "triangle"
    group.attrs["engine_version"] = "7"
    group.attrs["mesh_request_hash"] = "abcdef0123456789"
    return str(path)


def test_the_same_mesh_restarts(tmp_path: Path) -> None:
    mesh = _mesh()
    verify_restart_mesh(_store(tmp_path / "prior.zarr", mesh), mesh)


def test_a_vertex_moved_by_a_centimetre_is_refused_with_both_identities(tmp_path: Path) -> None:
    mesh = _mesh()
    moved = mesh.mesh.vertices[:, :2].copy()
    moved[4, 0] += 0.01
    prior = _store(tmp_path / "prior.zarr", mesh, vertices=moved)

    with pytest.raises(IncompatibleMeshError) as caught:
        verify_restart_mesh(prior, mesh)

    message = str(caught.value)
    assert "1 vertices moved (first: 4" in message
    assert "engine triangle 7, request abcdef012345" in message
    assert f"engine {mesh.identity.engine_id} {mesh.identity.engine_version}" in message


def test_a_shift_below_half_the_written_step_is_the_same_mesh(tmp_path: Path) -> None:
    """A millimeter in y at 6.8e6 m is under half of flopy's 1e-2 m step there."""
    mesh = _mesh()
    nudged = mesh.mesh.vertices[:, :2].copy()
    nudged[:, 1] += 0.001
    verify_restart_mesh(_store(tmp_path / "prior.zarr", mesh, vertices=nudged), mesh)


def test_the_same_shift_in_x_is_not(tmp_path: Path) -> None:
    """The step at 3.5e5 m is 1e-3 m, so a millimeter in x is a vertex that moved."""
    mesh = _mesh()
    nudged = mesh.mesh.vertices[:, :2].copy()
    nudged[:, 0] += 0.001
    with pytest.raises(IncompatibleMeshError, match="vertices moved"):
        verify_restart_mesh(_store(tmp_path / "prior.zarr", mesh, vertices=nudged), mesh)


def test_two_cells_swapped_are_refused(tmp_path: Path) -> None:
    mesh = _mesh()
    rows = mesh.geometry.padded_connectivity.copy()
    rows[[1, 2]] = rows[[2, 1]]
    prior = _store(tmp_path / "prior.zarr", mesh, rows=rows)

    with pytest.raises(IncompatibleMeshError, match="connectivity differs from cell 1"):
        verify_restart_mesh(prior, mesh)


def test_a_ring_walked_the_other_way_is_the_same_cell(tmp_path: Path) -> None:
    """MODFLOW 6 stores its DISV clockwise: the cell is the same, the ring is reversed."""
    mesh = _mesh()
    rows = mesh.geometry.padded_connectivity.copy()
    rows[:, 1:] = rows[:, :0:-1]
    verify_restart_mesh(_store(tmp_path / "prior.zarr", mesh, rows=rows), mesh)


def test_another_cell_count_is_refused(tmp_path: Path) -> None:
    prior = _store(tmp_path / "prior.zarr", _mesh())
    other = regular_cell_mesh(xmin=_XMIN, ymin=_YMIN, dx=100.0, dy=100.0, nrow=2, ncol=4)

    with pytest.raises(IncompatibleMeshError, match="6 cells .* 8 and"):
        verify_restart_mesh(prior, other)


def test_a_store_without_a_mesh_keeps_the_cell_count_rule_and_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    prior = tmp_path / "prior.zarr"
    zarr.open(str(prior), mode="w")["head"] = np.zeros((1, 1, 6))
    with caplog.at_level(logging.WARNING):
        verify_restart_mesh(str(prior), _mesh())

    assert any("stores no mesh" in record.getMessage() for record in caplog.records)


def test_the_prior_state_is_not_read_from_another_mesh(tmp_path: Path) -> None:
    mesh = _mesh()
    moved = mesh.mesh.vertices[:, :2].copy()
    moved[0, 0] += 0.5
    prior = _store(tmp_path / "prior.zarr", mesh, vertices=moved)

    with pytest.raises(IncompatibleMeshError, match="another mesh"):
        read_prior_state(prior, mesh)


def test_the_start_heads_of_the_same_mesh_are_the_prior_heads(tmp_path: Path) -> None:
    mesh = _mesh()
    prior = _store(tmp_path / "prior.zarr", mesh)

    state = read_prior_state(prior, mesh)
    strt = restart_start_heads(state.head, nlay=1, ncpl=6, top=np.full(6, 10.0))

    assert np.array_equal(strt, np.arange(6, dtype=float).reshape(1, 6))


def _write_heads(path: Path, head: np.ndarray) -> str:
    zarr.open(str(path), mode="w")["head"] = head
    return str(path)


def test_a_prior_state_carries_what_the_store_holds(tmp_path: Path) -> None:
    mesh = _mesh()
    path = _store(tmp_path / "prior.zarr", mesh)
    root = zarr.open(path, mode="r+")
    group = root.require_group("lake_state_final")
    group["stage"] = np.array([86.9])
    group.attrs["lake_ids"] = ["forebay"]

    state = read_prior_state(path, mesh, sim_id="abc123")

    assert isinstance(state, PriorState)
    assert (state.path, state.sim_id) == (path, "abc123")
    assert dict(state.lake_stages) == {"forebay": pytest.approx(86.9)}
    assert state.head.shape == (1, 6)
    assert not state.head.flags.writeable


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        pytest.param(
            np.array([[[1.0, 2.0, 3.0]], [[4.0, 5.0, 6.0]]]),
            [[4.0, 5.0, 6.0]],
            id="the last time step is read",
        ),
        pytest.param(
            np.array([[[1.0, 1.0e30, np.nan], [4.0, 5.0, 6.0]]]),
            [[1.0, np.nan, np.nan], [4.0, 5.0, 6.0]],
            id="sentinel and NaN cells come back NaN",
        ),
        pytest.param(np.array([[7.0, 8.0, 9.0]]), [[7.0, 8.0, 9.0]], id="one layer, flat steps"),
    ],
)
def test_the_heads_read_are_the_last_step_with_nan_on_inactive_cells(
    tmp_path: Path, stored: np.ndarray, expected: list[list[float]]
) -> None:
    path = _write_heads(tmp_path / "prior.zarr", stored)

    np.testing.assert_array_equal(read_final_head(path), np.array(expected))


@pytest.mark.parametrize(
    ("reader", "label"),
    [
        pytest.param(read_final_head, "read_final_head", id="the spin-up read"),
        pytest.param(lambda path: read_prior_state(path, _mesh()), "restart_from", id="a restart"),
    ],
)
def test_a_store_without_heads_is_refused_by_name(tmp_path: Path, reader, label: str) -> None:
    path = tmp_path / "prior.zarr"
    zarr.open(str(path), mode="w")["other"] = np.zeros(3)

    with pytest.raises(ValueError, match=f"{label}: no 'head' field"):
        reader(str(path))


def test_read_restart_lake_stages_roundtrip_raw_zarr(tmp_path: Path) -> None:
    """The reader parses the ``lake_state_final`` group written by the store."""
    path = tmp_path / "prior.zarr"
    root = zarr.open(str(path), mode="w")
    grp = root.require_group("lake_state_final")
    grp["stage"] = np.array([86.9, 74.2])
    grp.attrs["lake_ids"] = ["forebay", "sill"]

    stages = read_restart_lake_stages(str(path))
    assert stages == {"forebay": pytest.approx(86.9), "sill": pytest.approx(74.2)}


def test_read_restart_lake_stages_absent_group_returns_empty(tmp_path: Path) -> None:
    """A prior run with no lake (no group) yields {} so initial_stage is kept."""
    path = tmp_path / "prior.zarr"
    zarr.open(str(path), mode="w")["head"] = np.zeros((1, 1, 3))
    assert read_restart_lake_stages(str(path)) == {}


def test_read_restart_lake_stages_length_mismatch_returns_empty(tmp_path: Path) -> None:
    """A corrupt group (ids vs stages length mismatch) is refused, not guessed."""
    path = tmp_path / "prior.zarr"
    root = zarr.open(str(path), mode="w")
    grp = root.require_group("lake_state_final")
    grp["stage"] = np.array([1.0, 2.0, 3.0])
    grp.attrs["lake_ids"] = ["a", "b"]
    assert read_restart_lake_stages(str(path)) == {}


# A run that wrote final_state/ -----------------------------------------------

EXACT = np.array([[100.0 + 1e-9, 101.0 + 2e-9, np.nan, 103.0, 104.0, 105.0]])
"""Heads that the compact precision would round, NaN on one inactive cell."""


def _compact(values: np.ndarray) -> np.ndarray:
    """The head as fields.zarr keeps it under the compact precision, 2^-17 apart."""
    step = 2.0**-17
    return np.round(values / step) * step


def _run(tmp_path: Path, *, final: bool = True, fields: bool = True) -> Path:
    """A run folder with its field store, rounded, and its exact final state."""
    run = tmp_path / "runs" / "island_w1"
    run.mkdir(parents=True)
    if fields:
        _store(run / "fields.zarr", _mesh())
        root = zarr.open(str(run / "fields.zarr"), mode="r+")
        root["head"] = _compact(EXACT).reshape(1, 1, -1)
        group = root.require_group("lake_state_final")
        group["stage"] = np.array([13.95991695])
        group.attrs["lake_ids"] = ["forebay"]
    if final:
        write_final_state(
            run,
            FinalState(
                head=EXACT,
                lake_stages={"forebay": 13.95991694769827},
                sfr_stages={0: 12.25, 1: 11.75},
                at="2020-07-01",
            ),
        )
    return run


@pytest.mark.parametrize(
    "named", ["run folder", "fields.zarr", "final_state"], ids=["run", "fields", "final"]
)
def test_a_run_with_a_final_state_is_read_from_it_exactly(tmp_path: Path, named: str) -> None:
    run = _run(tmp_path)
    path = {
        "run folder": run,
        "fields.zarr": run / "fields.zarr",
        "final_state": run / "final_state",
    }[named]

    state = read_prior_state(str(path), _mesh(), sim_id="w1")

    np.testing.assert_array_equal(state.head, EXACT)
    assert dict(state.lake_stages) == {"forebay": 13.95991694769827}
    assert dict(state.sfr_stages) == {0: 12.25, 1: 11.75}
    assert (state.path, state.sim_id) == (str(run / "final_state"), "w1")


def test_a_compact_run_gives_back_its_exact_head_only_through_final_state(tmp_path: Path) -> None:
    run = _run(tmp_path)
    rounded = _compact(EXACT)

    assert not np.array_equal(rounded, EXACT, equal_nan=True)
    np.testing.assert_array_equal(read_final_head(str(run / "fields.zarr")), EXACT)
    np.testing.assert_array_equal(read_final_head(str(run)), EXACT)


def test_a_run_of_2_0_is_read_from_the_last_step_of_its_field_store(tmp_path: Path) -> None:
    run = _run(tmp_path, final=False)

    state = read_prior_state(str(run), _mesh())

    np.testing.assert_array_equal(state.head, _compact(EXACT))
    assert dict(state.lake_stages) == {"forebay": 13.95991695}
    assert dict(state.sfr_stages) == {}
    assert state.path == str(run / "fields.zarr")


def test_the_lake_stages_of_a_run_come_from_its_final_state(tmp_path: Path) -> None:
    run = _run(tmp_path)

    assert read_restart_lake_stages(str(run / "fields.zarr")) == {"forebay": 13.95991694769827}
    assert read_restart_lake_stages(str(_run(tmp_path / "old", final=False))) == {
        "forebay": 13.95991695
    }


def test_a_final_state_is_not_read_from_another_mesh(tmp_path: Path) -> None:
    run = _run(tmp_path)
    other = regular_cell_mesh(xmin=_XMIN, ymin=_YMIN, dx=100.0, dy=100.0, nrow=3, ncol=2)

    with pytest.raises(IncompatibleMeshError):
        read_prior_state(str(run / "final_state"), other)


def test_a_final_state_alone_keeps_the_cell_count_rule_and_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    run = _run(tmp_path, fields=False)

    with caplog.at_level(logging.WARNING):
        state = read_prior_state(str(run / "final_state"), _mesh())

    assert "no fields.zarr beside its final state" in caplog.text
    np.testing.assert_array_equal(state.head, EXACT)


def test_the_state_read_for_an_identity_skips_the_mesh_and_matches_the_restart(
    tmp_path: Path,
) -> None:
    run = _run(tmp_path)

    unchecked = prior_state_at(str(run), sim_id="w1")
    checked = read_prior_state(str(run), _mesh(), sim_id="w1")

    np.testing.assert_array_equal(unchecked.head, checked.head)
    assert dict(unchecked.sfr_stages) == dict(checked.sfr_stages)
    assert unchecked.path == checked.path


def test_a_run_with_nothing_to_read_is_refused(tmp_path: Path) -> None:
    run = tmp_path / "runs" / "empty"
    run.mkdir(parents=True)

    with pytest.raises(ValueError, match="neither a final_state/ nor a fields.zarr"):
        prior_state_at(str(run / "final_state"))
