"""What the MODFLOW-NWT budget extractor lets into the store.

The .cbc file of a MODFLOW-NWT run carries the stress and storage terms next
to the intercell face flows. The face flows are antisymmetric fluxes across
cell interfaces: they net to zero over the model, no field of the registry
names them, and a per-cell array of one direction is not a budget of anything.
They must not reach the store, the same way they do not on the MODFLOW 6 path.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from hydromodpy.core.budget_terms import POLICY_ALL, POLICY_CONSUMERS, BudgetKeep
from hydromodpy.solver.modflow_nwt.extractors import flow as nwt_flow
from hydromodpy.solver.modflow_nwt.extractors.flow import ModflowNwtOutputAdapter

NLAY, NROW, NCOL = 1, 1, 4
N_CELLS = NROW * NCOL


class _RecordingStore:
    """A store that keeps every write the extractor asks it for."""

    def __init__(self) -> None:
        self.budgets: list[dict] = []
        self.fields: list[tuple[str, str | None, np.ndarray]] = []
        self.policies: list[tuple[str, list[str]]] = []

    def write_budgets(self, sim_id: str, records: list[dict]) -> None:
        self.budgets.extend(records)

    def write_field_stack(
        self,
        sim_id: str,
        name: str,
        values: np.ndarray,
        *,
        n_timesteps: int | None = None,
        timestep_offset: int = 0,
        subgroup: str | None = None,
    ) -> None:
        self.fields.append((name, subgroup, np.asarray(values)))

    def field_names(self) -> set[str]:
        return {name for name, _subgroup, _values in self.fields}

    def open_zarr(self, sim_id: str) -> _RecordingStore:
        return self

    def write_budget_policy(self, keep: BudgetKeep, written: Any) -> None:
        self.policies.append((keep.policy, sorted(written)))

    def close(self) -> None:
        pass


def _fake_cbc(records: dict[str, np.ndarray]):
    """Return a CellBudgetFile stand-in serving ``records`` at one step."""
    names = list(records)

    class _FakeCellBudgetFile:
        def __init__(self, path: str, precision: str = "double") -> None:
            del path
            self.closed = False
            # The record index FloPy builds: one compact record per name.
            self.recordarray = np.array(
                [(1, 1, name.rjust(16).encode(), 1, 1.0, 1.0) for name in names],
                dtype=[
                    ("kstp", "<i4"),
                    ("kper", "<i4"),
                    ("text", "S16"),
                    ("imeth", "<i4"),
                    ("delt", "<f4"),
                    ("totim", "<f4"),
                ],
            )

        def get_unique_record_names(self) -> list[bytes]:
            return [name.encode() for name in records]

        def get_record(self, idx: int, full3D: bool = False) -> np.ndarray:
            assert full3D
            return records[names[idx]].reshape(NLAY, NROW, NCOL)

        def close(self) -> None:
            self.closed = True

    return _FakeCellBudgetFile


def _extract(monkeypatch, tmp_path: Path, records, *, budget_terms: BudgetKeep) -> _RecordingStore:
    monkeypatch.setattr("flopy.utils.binaryfile.CellBudgetFile", _fake_cbc(records), raising=True)
    store = _RecordingStore()
    ModflowNwtOutputAdapter()._extract_budget(
        "sim",
        store,
        tmp_path / "run.cbc",
        [1.0],
        [(0, 0)],
        NLAY,
        NROW,
        NCOL,
        budget_terms=budget_terms,
        flux_scale_to_m3_s=1.0,
    )
    return store


_ALL = BudgetKeep.everything()
_LUMPED = BudgetKeep.of_terms(())

_FACE_FLOWS = {
    "FLOW RIGHT FACE": np.array([8.0, -8.0, 3.0, -3.0]),
    "FLOW FRONT FACE": np.array([2.0, -2.0, 5.0, -5.0]),
}


def test_face_flows_never_become_a_budget_term(tmp_path, monkeypatch) -> None:
    records = {"DRAINS": np.array([-5.0, 0.0, 0.0, 0.0]), "RECHARGE": np.full(N_CELLS, 1.25)}
    store = _extract(monkeypatch, tmp_path, records | _FACE_FLOWS, budget_terms=_LUMPED)

    assert {row["component"] for row in store.budgets} == {"drain", "recharge"}


def test_face_flows_never_become_a_per_cell_field(tmp_path, monkeypatch) -> None:
    """The measured defect: two full arrays per run that nothing reads by name."""
    records = {"DRAINS": np.array([-5.0, 0.0, 0.0, 0.0])}
    store = _extract(monkeypatch, tmp_path, records | _FACE_FLOWS, budget_terms=_ALL)

    assert store.field_names() == {"drain"}
    assert all(subgroup == "budget" for _name, subgroup, _values in store.fields)


def test_the_stress_terms_keep_their_fluxes(tmp_path, monkeypatch) -> None:
    """Dropping the face flows must not touch what the real packages carry."""
    records = {"DRAINS": np.array([-5.0, 0.0, -1.5, 0.0]), "RECHARGE": np.full(N_CELLS, 1.25)}
    store = _extract(monkeypatch, tmp_path, records | _FACE_FLOWS, budget_terms=_ALL)

    by_component = {row["component"]: row for row in store.budgets}
    assert by_component["drain"]["flux_out"] == pytest.approx(6.5)
    assert by_component["drain"]["flux_in"] == pytest.approx(0.0)
    assert by_component["recharge"]["flux_in"] == pytest.approx(5.0)
    drain_field = next(values for name, _sub, values in store.fields if name == "drain")
    assert drain_field.shape == (1, NLAY, N_CELLS)
    assert drain_field[0, 0].tolist() == [-5.0, 0.0, -1.5, 0.0]


def test_a_run_carrying_only_face_flows_writes_nothing(tmp_path, monkeypatch) -> None:
    store = _extract(monkeypatch, tmp_path, dict(_FACE_FLOWS), budget_terms=_ALL)

    assert store.budgets == []
    assert store.fields == []


_EVERY_RECORD = {
    "STORAGE": np.array([0.5, -0.5, 0.25, 0.0]),
    "CONSTANT HEAD": np.array([0.0, 1.0, 0.0, -1.0]),
    "DRAINS": np.array([-5.0, 0.0, -1.5, 0.0]),
    "RECHARGE": np.full(N_CELLS, 1.25),
    "HEAD DEP BOUNDS": np.array([0.0, 0.0, 2.0, -2.0]),
}


def test_everything_writes_each_scalar_record_storage_included(tmp_path, monkeypatch) -> None:
    store = _extract(monkeypatch, tmp_path, _EVERY_RECORD | _FACE_FLOWS, budget_terms=_ALL)

    expected = {"storage", "constant_head", "drain", "recharge", "general_head"}
    assert store.field_names() == expected
    storage = next(values for name, _sub, values in store.fields if name == "storage")
    assert storage[0, 0].tolist() == [0.5, -0.5, 0.25, 0.0]
    assert store.policies == [(POLICY_ALL, sorted(expected))]


def test_an_unkept_term_never_gets_a_slab(tmp_path, monkeypatch) -> None:
    calls: list[int] = []
    real = nwt_flow.weighted_period_mean

    def spy(arrays, weights):
        calls.append(len(arrays))
        return real(arrays, weights)

    monkeypatch.setattr(nwt_flow, "weighted_period_mean", spy)
    keep = BudgetKeep.of_terms({"drain", "lake"})
    store = _extract(monkeypatch, tmp_path, _EVERY_RECORD, budget_terms=keep)

    assert store.field_names() == {"drain"}
    assert len(calls) == 1
    assert store.policies == [(POLICY_CONSUMERS, ["drain"])]


@pytest.mark.parametrize(
    "budget_terms",
    [_LUMPED, BudgetKeep.of_terms({"storage", "recharge"})],
    ids=["lumped", "two_terms"],
)
def test_the_budget_table_does_not_depend_on_the_kept_terms(
    tmp_path, monkeypatch, budget_terms
) -> None:
    reference = _extract(monkeypatch, tmp_path, _EVERY_RECORD, budget_terms=_ALL)
    filtered = _extract(monkeypatch, tmp_path, _EVERY_RECORD, budget_terms=budget_terms)

    assert filtered.budgets == reference.budgets
    assert len(reference.budgets) == len(_EVERY_RECORD)


def test_a_lumped_run_writes_no_field_but_records_its_policy(tmp_path, monkeypatch) -> None:
    store = _extract(monkeypatch, tmp_path, _EVERY_RECORD, budget_terms=_LUMPED)

    assert store.fields == []
    assert store.policies == [(POLICY_CONSUMERS, [])]
