"""What the MODFLOW-NWT budget extractor lets into the store.

The .cbc file of a MODFLOW-NWT run carries the stress and storage terms next
to the intercell face flows. The face flows are antisymmetric fluxes across
cell interfaces: they net to zero over the model, no field of the registry
names them, and a per-cell array of one direction is not a budget of anything.
They must not reach the store, the same way they do not on the MODFLOW 6 path.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.solver.modflow_nwt.extractors.flow import ModflowNwtOutputAdapter

NLAY, NROW, NCOL = 1, 1, 4
N_CELLS = NROW * NCOL


class _RecordingStore:
    """A store that keeps every write the extractor asks it for."""

    def __init__(self) -> None:
        self.budgets: list[dict] = []
        self.fields: list[tuple[str, str | None, np.ndarray]] = []

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


def _fake_cbc(records: dict[str, np.ndarray]):
    """Return a CellBudgetFile stand-in serving ``records`` at every step."""

    class _FakeCellBudgetFile:
        def __init__(self, path: str, precision: str = "double") -> None:
            del path
            self.closed = False

        def get_unique_record_names(self) -> list[bytes]:
            return [name.encode() for name in records]

        def get_data(self, *, text: str, kstpkper, totim, full3D: bool) -> list[np.ndarray]:
            del kstpkper, totim, full3D
            return [records[text].reshape(NLAY, NROW, NCOL)]

        def close(self) -> None:
            self.closed = True

    return _FakeCellBudgetFile


def _extract(monkeypatch, tmp_path: Path, records, *, spatial_fields: bool) -> _RecordingStore:
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
        spatial_fields=spatial_fields,
        flux_scale_to_m3_s=1.0,
    )
    return store


_FACE_FLOWS = {
    "FLOW RIGHT FACE": np.array([8.0, -8.0, 3.0, -3.0]),
    "FLOW FRONT FACE": np.array([2.0, -2.0, 5.0, -5.0]),
}


def test_face_flows_never_become_a_budget_term(tmp_path, monkeypatch) -> None:
    records = {"DRAINS": np.array([-5.0, 0.0, 0.0, 0.0]), "RECHARGE": np.full(N_CELLS, 1.25)}
    store = _extract(monkeypatch, tmp_path, records | _FACE_FLOWS, spatial_fields=False)

    assert {row["component"] for row in store.budgets} == {"drain", "recharge"}


def test_face_flows_never_become_a_per_cell_field(tmp_path, monkeypatch) -> None:
    """The measured defect: two full arrays per run that nothing reads by name."""
    records = {"DRAINS": np.array([-5.0, 0.0, 0.0, 0.0])}
    store = _extract(monkeypatch, tmp_path, records | _FACE_FLOWS, spatial_fields=True)

    assert store.field_names() == {"drain"}
    assert all(subgroup == "budget" for _name, subgroup, _values in store.fields)


def test_the_stress_terms_keep_their_fluxes(tmp_path, monkeypatch) -> None:
    """Dropping the face flows must not touch what the real packages carry."""
    records = {"DRAINS": np.array([-5.0, 0.0, -1.5, 0.0]), "RECHARGE": np.full(N_CELLS, 1.25)}
    store = _extract(monkeypatch, tmp_path, records | _FACE_FLOWS, spatial_fields=True)

    by_component = {row["component"]: row for row in store.budgets}
    assert by_component["drain"]["flux_out"] == pytest.approx(6.5)
    assert by_component["drain"]["flux_in"] == pytest.approx(0.0)
    assert by_component["recharge"]["flux_in"] == pytest.approx(5.0)
    drain_field = next(values for name, _sub, values in store.fields if name == "drain")
    assert drain_field.shape == (1, NLAY, N_CELLS)
    assert drain_field[0, 0].tolist() == [-5.0, 0.0, -1.5, 0.0]


def test_a_run_carrying_only_face_flows_writes_nothing(tmp_path, monkeypatch) -> None:
    store = _extract(monkeypatch, tmp_path, dict(_FACE_FLOWS), spatial_fields=True)

    assert store.budgets == []
    assert store.fields == []
