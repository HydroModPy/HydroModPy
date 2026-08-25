"""Single-pass MF6 .cbc budget extraction: ordering, dedup, scaling, stacks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from hydromodpy.solver.modflow6.extractors.cbc_reader import CbcRecord
from hydromodpy.solver.modflow6.extractors.flow import Modflow6OutputAdapter

_SPT = 86400.0
_NAMES = [b"    FLOW-JA-FACE", b"            RCHA", b"             DRN", b"             EVT"]


class _FakeCbb:
    """records + read_record stand-in for Mf6CellBudgetReader."""

    def __init__(self, records: list[tuple[int, int, bytes, Any]]):
        self.records = tuple(
            CbcRecord(
                kstp=kstp,
                kper=kper,
                text=text.decode().strip(),
                imeth=1,
                ndim1=4,
                ndim2=1,
                ndim3=-1,
                nlist=0,
                aux_names=(),
                data_pos=0,
            )
            for kstp, kper, text, _ in records
        )
        self._payloads: list[Any] = [payload for *_, payload in records]
        self.closed = False

    def unique_record_names(self) -> list[str]:
        return [name.decode().strip() for name in _NAMES]

    def read_record(self, idx: int) -> Any:
        payload = self._payloads[idx]
        if isinstance(payload, Exception):
            raise payload
        return payload

    def close(self) -> None:
        self.closed = True


class _FakeStore:
    def __init__(self) -> None:
        self.budgets: list[dict] | None = None
        self.stacks: dict[str, tuple[np.ndarray, str | None]] = {}

    def write_budgets(self, sim_id: str, records: list[dict]) -> None:
        self.budgets = records

    def write_field_stack(
        self, sim_id: str, name: str, stack: np.ndarray, subgroup: str | None = None, **_: Any
    ) -> None:
        self.stacks[name] = (stack, subgroup)


def _drn_recarray(node: int, q: float) -> np.recarray:
    rec = np.zeros(1, dtype=[("node", "<i4"), ("q", "<f8")])
    rec["node"][0] = node
    rec["q"][0] = q
    return rec.view(np.recarray)


def _run_extract(fake_cbb: _FakeCbb, monkeypatch: pytest.MonkeyPatch) -> _FakeStore:
    from hydromodpy.solver.modflow6.extractors import cbc_reader

    monkeypatch.setattr(cbc_reader, "Mf6CellBudgetReader", lambda *args, **kwargs: fake_cbb)
    store = _FakeStore()
    Modflow6OutputAdapter()._extract_budget(
        "sim",
        store,
        Path("unused.cbc"),
        times=[1.0, 2.0],
        kstpkpers=[(0, 0), (0, 1)],
        spatial_fields=True,
        nlay=1,
        n_cells=4,
        seconds_per_time_unit=_SPT,
    )
    return store


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> _FakeStore:
    fake = _FakeCbb(
        [
            (1, 1, _NAMES[0], np.full((1, 1, 4), 9.9)),  # FLOW-JA-FACE: excluded
            (1, 1, _NAMES[1], np.array([[[1.0, -2.0, 3.0, 0.0]]])),
            (1, 1, _NAMES[2], _drn_recarray(node=2, q=-5.0)),
            (1, 1, _NAMES[2], _drn_recarray(node=3, q=-99.0)),  # 2nd DRN package: dropped
            (1, 1, _NAMES[3], np.array([[[0.0, -1.0, 0.0, 0.0]]])),  # EVT only at t0
            (1, 2, _NAMES[1], np.array([[[2.0, 0.0, 0.0, 0.0]]])),
            (1, 2, _NAMES[2], _drn_recarray(node=1, q=4.0)),
        ]
    )
    out = _run_extract(fake, monkeypatch)
    assert fake.closed
    return out


def test_budget_records_time_major_then_component_order(store: _FakeStore) -> None:
    assert store.budgets is not None
    keys = [(rec["timestep"], rec["component"]) for rec in store.budgets]
    assert keys == [
        (0, "recharge"),
        (0, "drain"),
        (0, "evapotranspiration"),
        (1, "recharge"),
        (1, "drain"),
    ]


def test_budget_fluxes_scaled_and_split(store: _FakeStore) -> None:
    by_key = {(rec["timestep"], rec["component"]): rec for rec in store.budgets}
    rcha0 = by_key[(0, "recharge")]
    assert rcha0["flux_in"] == pytest.approx(4.0 / _SPT)
    assert rcha0["flux_out"] == pytest.approx(2.0 / _SPT)
    assert rcha0["zone_id"] == "0"
    assert rcha0["unit"] == "m3/s"
    drn1 = by_key[(1, "drain")]
    assert drn1["flux_in"] == pytest.approx(4.0 / _SPT)
    assert drn1["flux_out"] == pytest.approx(0.0)


def test_first_record_wins_for_duplicate_package_type(store: _FakeStore) -> None:
    drn0 = next(r for r in store.budgets if r["timestep"] == 0 and r["component"] == "drain")
    assert drn0["flux_out"] == pytest.approx(5.0 / _SPT)


def test_spatial_stacks_per_component(store: _FakeStore) -> None:
    rcha_stack, subgroup = store.stacks["recharge"]
    assert subgroup == "budget"
    assert rcha_stack.shape == (2, 1, 4)
    np.testing.assert_allclose(rcha_stack[0, 0], np.array([1.0, -2.0, 3.0, 0.0]) / _SPT)
    drn_stack, _ = store.stacks["drain"]
    np.testing.assert_allclose(drn_stack[0, 0], np.array([0.0, -5.0, 0.0, 0.0]) / _SPT)
    evt_stack, _ = store.stacks["evapotranspiration"]
    assert np.isnan(evt_stack[1]).all()  # EVT has no t1 record


def test_unreadable_record_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeCbb(
        [
            (1, 1, _NAMES[1], ValueError("corrupt record")),
            (1, 2, _NAMES[1], np.array([[[1.0, 0.0, 0.0, 0.0]]])),
        ]
    )
    store = _run_extract(fake, monkeypatch)
    assert [(r["timestep"], r["component"]) for r in store.budgets] == [(1, "recharge")]


def test_unknown_kstpkper_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeCbb([(7, 9, _NAMES[1], np.array([[[1.0, 0.0, 0.0, 0.0]]]))])
    store = _run_extract(fake, monkeypatch)
    assert store.budgets is None
    assert store.stacks == {}
