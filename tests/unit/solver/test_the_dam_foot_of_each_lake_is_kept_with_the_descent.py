"""The build keeps the cell below each declared spillway, with D, for the heads of the criterion.

Only a lake whose spillway is declared (an outlet releasing downstream, which
the production path resolves to a toe cell) has a dam foot. A lake without one
has none, and a foot that is a cell of a lake is dropped. The cells travel in
the descent sidecar, and a sidecar written before they were kept reads as having
none.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from hydromodpy.solver.modflow6 import build
from hydromodpy.solver.modflow_common.mesh_descent import (
    read_descent_sidecar,
    resolve_dam_foot_cells,
    write_descent_sidecar,
)
from tests.unit.core._descent_meshes import grid_descent
from tests.unit.core.test_a_lake_is_traversed_by_the_descent import (
    _valley,
)


def _descent():
    top, lake_of = _valley()
    return grid_descent(top, lake_of=lake_of)


def test_a_lake_without_a_declared_spillway_has_no_foot() -> None:
    assert resolve_dam_foot_cells(_descent(), {}) == {}


def test_the_toe_of_a_declared_spillway_is_the_foot() -> None:
    feet = resolve_dam_foot_cells(_descent(), {"reservoir": 3})

    assert feet == {"reservoir": 3}


def test_a_foot_that_is_a_cell_of_a_lake_is_dropped() -> None:
    descent = _descent()
    in_lake = int(np.flatnonzero(descent.lake_of >= 0)[0])

    feet = resolve_dam_foot_cells(descent, {"forebay": in_lake, "main": 3})

    assert feet == {"main": 3}


def test_a_foot_off_the_mesh_is_dropped() -> None:
    descent = _descent()

    assert resolve_dam_foot_cells(descent, {"a": -1, "b": int(descent.lake_of.size)}) == {}


def test_the_build_keeps_the_feet_on_the_model_and_in_the_sidecar(tmp_path) -> None:
    model = SimpleNamespace(full_path=str(tmp_path), model_output_name="model")

    build._keep_dam_feet_and_leave_descent(model, _descent(), {"reservoir": 3})

    assert model.dam_foot_cells == {"reservoir": 3}
    record = read_descent_sidecar(tmp_path / "model.descent.npz")
    assert record is not None
    assert record.dam_foot.tolist() == [3]


def test_a_lake_without_a_declared_spillway_leaves_an_empty_foot(tmp_path) -> None:
    model = SimpleNamespace(full_path=str(tmp_path), model_output_name="model")

    build._keep_dam_feet_and_leave_descent(model, _descent(), {})

    assert model.dam_foot_cells == {}
    record = read_descent_sidecar(tmp_path / "model.descent.npz")
    assert record is not None
    assert record.dam_foot.size == 0


def test_an_auxiliary_model_keeps_no_foot_and_leaves_no_sidecar(tmp_path) -> None:
    model = SimpleNamespace(full_path=str(tmp_path), model_output_name="model", auxiliary=True)

    build._keep_dam_feet_and_leave_descent(model, _descent(), {"reservoir": 3})

    assert model.dam_foot_cells == {}
    assert not list(tmp_path.glob("*.descent.npz"))


def test_the_sidecar_carries_the_feet_sorted_once(tmp_path) -> None:
    path = write_descent_sidecar(
        _descent(), tmp_path, "model", dam_foot_cells={"a": 40, "b": 12, "c": 40}
    )

    record = read_descent_sidecar(path)

    assert record is not None
    assert record.dam_foot.tolist() == [12, 40]
    assert record.dam_foot.dtype == np.int64


def test_a_run_without_a_lake_writes_an_empty_foot(tmp_path) -> None:
    record = read_descent_sidecar(write_descent_sidecar(_descent(), tmp_path, "model"))

    assert record is not None
    assert record.dam_foot.size == 0


def test_a_sidecar_written_before_the_feet_were_kept_reads_as_having_none(tmp_path) -> None:
    path = write_descent_sidecar(_descent(), tmp_path, "model", dam_foot_cells={"a": 12})
    with np.load(path) as payload:
        kept = {name: payload[name] for name in payload.files if name != "dam_foot"}
    np.savez(path, **kept)

    record = read_descent_sidecar(path)

    assert record is not None
    assert record.dam_foot.size == 0
