"""WP10 - the scalar budget table excludes intercell face flows and SPDIS.

FLOW-JA-FACE (and the directional FACE flows) are antisymmetric intercell
fluxes that net to ~0; DATA-SPDIS is a specific-discharge velocity (m/s). Both
must be skipped so the scalar budget aggregates only real stress/storage terms.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.solver.modflow6.extractors.flow import Modflow6OutputAdapter
from hydromodpy.solver.modflow_common.budget_components import is_scalar_budget_component


class _FakeStore:
    def __init__(self) -> None:
        self.budgets: list | None = None
        self.fields: list = []

    def write_budgets(self, sim_id, records) -> None:
        self.budgets = records

    def write_field(self, sim_id, name, t, values, n_timesteps=None, subgroup=None) -> None:
        self.fields.append((name, t, np.asarray(values)))


def _fake_cbc(record_data: dict, kstpkpers: list[tuple[int, int]]):
    """record_data maps record name -> {kstpkper: array} or array (all steps)."""
    flat: list[tuple[int, int, bytes, np.ndarray]] = []
    for name, entry in record_data.items():
        for kstpkper in kstpkpers:
            payload = entry[kstpkper] if isinstance(entry, dict) else entry
            flat.append((kstpkper[0] + 1, kstpkper[1] + 1, name.encode(), payload))

    class _FakeCBC:
        def __init__(self, path, *args, **kwargs):
            del path, args, kwargs
            self.recordarray = np.zeros(
                len(flat), dtype=[("kstp", "<i4"), ("kper", "<i4"), ("text", "S16")]
            )
            for idx, (kstp, kper, text, _) in enumerate(flat):
                self.recordarray["kstp"][idx] = kstp
                self.recordarray["kper"][idx] = kper
                self.recordarray["text"][idx] = text

        def get_unique_record_names(self):
            return [name.encode() for name in record_data]

        def get_record(self, idx: int):
            return flat[idx][3]

        def close(self) -> None:
            pass

    return _FakeCBC


def _extract(monkeypatch, tmp_path, record_data, *, times, kstpkpers, nlay=1, n_cells=2):
    monkeypatch.setattr(
        "flopy.utils.binaryfile.CellBudgetFile", _fake_cbc(record_data, kstpkpers), raising=True
    )
    store = _FakeStore()
    Modflow6OutputAdapter()._extract_budget(
        "sim",
        store,
        tmp_path / "flow.cbc",
        times,
        kstpkpers,
        nlay=nlay,
        n_cells=n_cells,
        seconds_per_time_unit=1.0,
    )
    return store


def test_is_scalar_budget_component_excludes_intercell_and_spdis() -> None:
    for excluded in (
        "FLOW-JA-FACE",
        "flow-ja-face",
        "  FLOW-JA-FACE  ",
        "DATA-SPDIS",
        "FLOW RIGHT FACE",
        "FLOW FRONT FACE",
        "FLOW LOWER FACE",
    ):
        assert is_scalar_budget_component(excluded) is False
    for kept in ("DRN", "WEL", "RCHA", "EVT", "CHD", "STO-SS", "STO-SY", "STORAGE"):
        assert is_scalar_budget_component(kept) is True


def test_extract_budget_drops_flow_ja_face_and_spdis(tmp_path, monkeypatch) -> None:
    spdis = np.array(
        [(1, 1, 0.0, 3.0, 4.0, 0.0)],
        dtype=[
            ("node", "<i4"),
            ("node2", "<i4"),
            ("q", "<f8"),
            ("qx", "<f8"),
            ("qy", "<f8"),
            ("qz", "<f8"),
        ],
    )
    records = {
        "DRN": np.array([-5.0, 0.0]),
        "RCHA": np.array([5.0, 0.0]),
        "FLOW-JA-FACE": np.array([8.0, -8.0]),
        "DATA-SPDIS": spdis,
    }
    store = _extract(monkeypatch, tmp_path, records, times=[1.0], kstpkpers=[(0, 0)])
    by = {r["component"]: r for r in store.budgets}
    assert set(by) == {"drn", "rcha"}
    assert by["rcha"]["flux_in"] == pytest.approx(5.0)
    assert by["drn"]["flux_out"] == pytest.approx(5.0)


def test_extract_budget_keeps_balanced_stress_term(tmp_path, monkeypatch) -> None:
    records = {
        "WEL": np.array([10.0, -10.0]),
        "FLOW-JA-FACE": np.array([1.0, -1.0]),
    }
    store = _extract(monkeypatch, tmp_path, records, times=[1.0], kstpkpers=[(0, 0)])
    assert len(store.budgets) == 1
    row = store.budgets[0]
    assert row["component"] == "wel"
    assert row["flux_in"] == pytest.approx(10.0)
    assert row["flux_out"] == pytest.approx(10.0)


def test_extract_budget_spdis_not_reduced_to_magnitude(tmp_path, monkeypatch) -> None:
    spdis = np.array(
        [(1, 1, 0.0, 1.0, 0.0, 0.0), (2, 2, 0.0, 0.0, 3.0, 0.0)],
        dtype=[
            ("node", "<i4"),
            ("node2", "<i4"),
            ("q", "<f8"),
            ("qx", "<f8"),
            ("qy", "<f8"),
            ("qz", "<f8"),
        ],
    )
    store = _extract(monkeypatch, tmp_path, {"DATA-SPDIS": spdis}, times=[1.0], kstpkpers=[(0, 0)])
    # No scalar budget term at all; the velocity magnitudes never appear.
    assert store.budgets is None


def test_extract_budget_multilayer_and_multistep_excludes_face_flow(tmp_path, monkeypatch) -> None:
    # nlay=2, n_cells=2: node = lay*n_cells + cell + 1.
    drn_t0 = np.array([(1, 1, -3.0)], dtype=[("node", "<i4"), ("node2", "<i4"), ("q", "<f8")])
    drn_t1 = np.array([(4, 4, -7.0)], dtype=[("node", "<i4"), ("node2", "<i4"), ("q", "<f8")])
    records = {
        "DRN": {(0, 0): drn_t0, (1, 0): drn_t1},
        "FLOW-JA-FACE": {(0, 0): np.array([2.0, -2.0]), (1, 0): np.array([2.0, -2.0])},
    }
    store = _extract(
        monkeypatch,
        tmp_path,
        records,
        times=[1.0, 2.0],
        kstpkpers=[(0, 0), (1, 0)],
        nlay=2,
        n_cells=2,
    )
    by_step = {r["timestep"]: r for r in store.budgets}
    assert {r["component"] for r in store.budgets} == {"drn"}
    assert by_step[0]["flux_out"] == pytest.approx(3.0)
    assert by_step[1]["flux_out"] == pytest.approx(7.0)
