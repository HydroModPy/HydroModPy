"""The face flows of a MODFLOW 6 run: pairs, sign, period mean and refusal."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.core.exceptions import ExtractError
from hydromodpy.solver.modflow6.extractors import face_flow
from hydromodpy.solver.modflow6.extractors.cbc_reader import CbcRecord
from hydromodpy.solver.modflow6.extractors.face_flow import (
    connection_pairs,
    extract_face_flows,
)

# A 2x2x2 grid of flat index k * 4 + i * 2 + j, cell 3 inactive: its two
# connections, (2, 3) and (3, 7), are absent from both rows.
_IA = np.array([0, 4, 7, 10, 10, 14, 18, 22, 25])
_JA = np.array([0, 1, 2, 4, 1, 0, 5, 2, 0, 6, 4, 5, 6, 0, 5, 4, 7, 1, 6, 7, 4, 2, 7, 6, 5])
_CELLS = np.array(
    [[0, 1], [0, 2], [0, 4], [1, 5], [2, 6], [4, 5], [4, 6], [5, 7], [6, 7]],
    dtype=np.int32,
)
_POSITIONS = np.array([5, 8, 13, 17, 21, 15, 20, 24, 23])

# The 2x2x1 grid of the extraction test, with all four cells active.
_IA_FLAT = np.array([0, 3, 6, 9, 12])
_JA_FLAT = np.array([0, 1, 2, 1, 0, 3, 2, 3, 0, 3, 2, 1])


def test_connection_pairs_keep_the_connections_between_active_cells() -> None:
    cells, positions = connection_pairs(_IA, _JA)

    np.testing.assert_array_equal(cells, _CELLS)
    np.testing.assert_array_equal(positions, _POSITIONS)


def test_connection_pairs_point_at_the_connection_entering_the_greater_cell() -> None:
    """MODFLOW counts positive what enters the cell of the line, so the flow
    from the smaller cell is the value at the greater cell's connection back."""
    cells, positions = connection_pairs(_IA, _JA)

    for (first, second), position in zip(cells, positions, strict=True):
        assert _JA[position] == first
        assert _IA[second] <= position < _IA[second + 1]


class _FakeBudget:
    def __init__(self, records: list[CbcRecord], payloads: list[np.ndarray]) -> None:
        self.records = tuple(records)
        self._payloads = payloads
        self.closed = False

    def read_record(self, index: int) -> np.ndarray:
        return self._payloads[index]

    def close(self) -> None:
        self.closed = True


class _FakeHandle:
    def __init__(self, owner: _FakeStore) -> None:
        self._owner = owner

    def write_static_field(self, variable: str, values: np.ndarray) -> None:
        self._owner.static[variable] = np.asarray(values)

    def close(self) -> None:
        pass


class _FakeStore:
    def __init__(self) -> None:
        self.stacks: dict[str, np.ndarray] = {}
        self.static: dict[str, np.ndarray] = {}

    def write_field_stack(
        self, sim_id: str, variable: str, values: np.ndarray, **_: object
    ) -> None:
        self.stacks[variable] = np.asarray(values)

    def open_zarr(self, sim_id: str) -> _FakeHandle:
        return _FakeHandle(self)


def _record(kstp: int, kper: int, delt: float) -> CbcRecord:
    return CbcRecord(
        kstp=kstp,
        kper=kper,
        text="FLOW-JA-FACE",
        imeth=1,
        delt=delt,
        totim=0.0,
        ndim1=12,
        ndim2=1,
        ndim3=-1,
        nlist=0,
        aux_names=(),
        data_pos=0,
    )


def _prepare(monkeypatch: pytest.MonkeyPatch) -> _FakeBudget:
    budget = _FakeBudget(
        [_record(1, 1, 1.0), _record(2, 1, 3.0)],
        [np.ones(_JA_FLAT.size), np.full(_JA_FLAT.size, 5.0)],
    )
    monkeypatch.setattr(face_flow, "Mf6CellBudgetReader", lambda path: budget)
    monkeypatch.setattr(face_flow, "grid_connections", lambda solver_dir: (_IA_FLAT, _JA_FLAT, 4))
    return budget


def test_extract_face_flows_weights_the_steps_of_one_stamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    budget = _prepare(monkeypatch)
    store = _FakeStore()

    count = extract_face_flows(
        "sim",
        store,
        Path("sim.cbc"),
        Path("out"),
        stamps=[(2, 1)],
        seconds_per_time_unit=1.0,
        precision="exact",
    )

    assert count == 4
    assert budget.closed
    np.testing.assert_allclose(store.stacks["face_flow"], np.full((1, 4), 4.0))
    np.testing.assert_array_equal(
        store.static["connection_cells"],
        np.array([[0, 1], [0, 2], [1, 3], [2, 3]], dtype=np.int32),
    )


def test_extract_face_flows_reads_each_step_at_its_index_in_the_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dataclasses import replace

    storage = replace(_record(1, 1, 1.0), text="STO-SS", ndim1=4)
    budget = _FakeBudget(
        [storage, _record(1, 1, 1.0), storage, _record(2, 1, 3.0)],
        [np.zeros(4), np.ones(_JA_FLAT.size), np.zeros(4), np.full(_JA_FLAT.size, 5.0)],
    )
    monkeypatch.setattr(face_flow, "Mf6CellBudgetReader", lambda path: budget)
    monkeypatch.setattr(face_flow, "grid_connections", lambda solver_dir: (_IA_FLAT, _JA_FLAT, 4))
    store = _FakeStore()

    extract_face_flows(
        "sim",
        store,
        Path("sim.cbc"),
        Path("out"),
        stamps=[(2, 1)],
        seconds_per_time_unit=1.0,
        precision="exact",
    )

    np.testing.assert_allclose(store.stacks["face_flow"], np.full((1, 4), 4.0))


def test_extract_face_flows_refuses_a_record_that_does_not_match_the_grid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    budget = _FakeBudget(
        [_record(2, 1, 1.0)],
        [np.ones(_JA_FLAT.size - 1)],
    )
    monkeypatch.setattr(face_flow, "Mf6CellBudgetReader", lambda path: budget)
    monkeypatch.setattr(face_flow, "grid_connections", lambda solver_dir: (_IA_FLAT, _JA_FLAT, 4))

    with pytest.raises(ExtractError, match="FLOW-JA-FACE holds 11 values and the binary grid 12"):
        extract_face_flows(
            "sim",
            _FakeStore(),
            Path("sim.cbc"),
            Path("out"),
            stamps=[(2, 1)],
            seconds_per_time_unit=1.0,
            precision="exact",
        )
