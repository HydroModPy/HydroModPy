"""Face flows (m3/s) between connected cells of a MODFLOW 6 run, read from the .cbc file.

Each stamp (kper, kstp) takes the mean of its steps weighted by step length (delt),
the connection list gives each pair of cells once, and a record that does not
match the grid is refused.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from hydromodpy.core.exceptions import ExtractError
from hydromodpy.solver.modflow6.extractors import face_flow
from hydromodpy.solver.modflow6.extractors.cbc_reader import CbcRecord
from hydromodpy.solver.modflow6.extractors.face_flow import extract_face_flows

# A 2x2x1 grid with its four cells active.
IA = np.array([0, 3, 6, 9, 12])
JA = np.array([0, 1, 2, 1, 0, 3, 2, 3, 0, 3, 2, 1])


class FakeBudget:
    def __init__(self, records: list[CbcRecord], payloads: list[np.ndarray]) -> None:
        self.records = tuple(records)
        self._payloads = payloads
        self.closed = False

    def read_record(self, index: int) -> np.ndarray:
        return self._payloads[index]

    def close(self) -> None:
        self.closed = True


class FakeHandle:
    def __init__(self, owner: FakeStore) -> None:
        self._owner = owner

    def write_static_field(self, variable: str, values: np.ndarray) -> None:
        self._owner.static[variable] = np.asarray(values)

    def close(self) -> None:
        pass


class FakeStore:
    def __init__(self) -> None:
        self.stacks: dict[str, np.ndarray] = {}
        self.static: dict[str, np.ndarray] = {}

    def write_field_stack(
        self, sim_id: str, variable: str, values: np.ndarray, **_: object
    ) -> None:
        self.stacks[variable] = np.asarray(values)

    def open_zarr(self, sim_id: str) -> FakeHandle:
        return FakeHandle(self)


def step_record(kstp: int, kper: int, delt: float) -> CbcRecord:
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


STORAGE = replace(step_record(1, 1, 1.0), text="STO-SS", ndim1=4)

# Steps of stamp (2, 1): 1 m3/s for 1 s then 5 m3/s for 3 s, so (1 + 3 * 5) / 4 = 4.
FLOW_STEPS = [step_record(1, 1, 1.0), step_record(2, 1, 3.0)]
FLOW_PAYLOADS = [np.ones(JA.size), np.full(JA.size, 5.0)]

BUDGETS = [
    pytest.param(FLOW_STEPS, FLOW_PAYLOADS, id="flow records only"),
    pytest.param(
        [STORAGE, FLOW_STEPS[0], STORAGE, FLOW_STEPS[1]],
        [np.zeros(4), FLOW_PAYLOADS[0], np.zeros(4), FLOW_PAYLOADS[1]],
        id="storage records between",
    ),
]


def extract(monkeypatch: pytest.MonkeyPatch, budget: FakeBudget, store: FakeStore) -> int:
    monkeypatch.setattr(face_flow, "Mf6CellBudgetReader", lambda path: budget)
    monkeypatch.setattr(face_flow, "grid_connections", lambda solver_dir: (IA, JA, 4))
    return extract_face_flows(
        "sim",
        store,
        Path("sim.cbc"),
        Path("out"),
        stamps=[(2, 1)],
        seconds_per_time_unit=1.0,
        precision="exact",
    )


@pytest.mark.parametrize(("records", "payloads"), BUDGETS)
def test_stamp_weights_its_steps(monkeypatch, records, payloads) -> None:
    budget, store = FakeBudget(records, payloads), FakeStore()

    count = extract(monkeypatch, budget, store)

    assert count == 4
    assert budget.closed
    np.testing.assert_allclose(store.stacks["face_flow"], np.full((1, 4), 4.0))
    np.testing.assert_array_equal(
        store.static["connection_cells"],
        np.array([[0, 1], [0, 2], [1, 3], [2, 3]], dtype=np.int32),
    )


def test_refuses_record_off_the_grid(monkeypatch) -> None:
    budget = FakeBudget([step_record(2, 1, 1.0)], [np.ones(JA.size - 1)])

    with pytest.raises(ExtractError, match="FLOW-JA-FACE holds 11 values and the binary grid 12"):
        extract(monkeypatch, budget, FakeStore())
