"""Single-pass MF6 .cbc budget extraction: ordering, dedup, scaling, stacks, policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from hydromodpy.core.budget_terms import (
    BUDGET_KEPT_TERMS_ATTR,
    BUDGET_POLICY_ATTR,
    POLICY_ALL,
    POLICY_CONSUMERS,
    BudgetKeep,
    kept_budget,
)
from hydromodpy.core.field_routing import CATCHMENT_BUDGET_ZONE, STREAM_CONSTANT_HEAD_BUDGET
from hydromodpy.results.zarr_store import SimulationZarr
from hydromodpy.solver.modflow6.extractors import flow as mf6_flow
from hydromodpy.solver.modflow6.extractors.cbc_reader import CbcRecord
from hydromodpy.solver.modflow6.extractors.flow import Modflow6OutputAdapter

_SPT = 86400.0
_NAMES = [b"    FLOW-JA-FACE", b"            RCHA", b"             DRN", b"             EVT"]


class _FakeCbb:
    """records + read_record stand-in for Mf6CellBudgetReader."""

    def __init__(
        self, records: list[tuple[int, int, bytes, Any]], names: list[bytes] | None = None
    ):
        self._names = list(_NAMES if names is None else names)
        self.records = tuple(
            CbcRecord(
                kstp=kstp,
                kper=kper,
                text=text.decode().strip(),
                imeth=1,
                delt=1.0,
                totim=1.0,
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
        return [name.decode().strip() for name in self._names]

    def read_record(self, idx: int) -> Any:
        payload = self._payloads[idx]
        if isinstance(payload, Exception):
            raise payload
        return payload

    def close(self) -> None:
        self.closed = True


class _PolicyRecorder:
    """The ``open_zarr`` handle: keeps the policy the extractor records."""

    def __init__(self, owner: _FakeStore) -> None:
        self._owner = owner

    def write_budget_policy(self, keep: BudgetKeep, written: Any) -> None:
        self._owner.policies.append((keep, sorted(written)))

    def close(self) -> None:
        pass


class _FakeStore:
    def __init__(self) -> None:
        self.budgets: list[dict] | None = None
        self.stacks: dict[str, tuple[np.ndarray, str | None]] = {}
        self.policies: list[tuple[BudgetKeep, list[str]]] = []

    def write_budgets(self, sim_id: str, records: list[dict]) -> None:
        self.budgets = records

    def write_field_stack(
        self, sim_id: str, name: str, stack: np.ndarray, subgroup: str | None = None, **_: Any
    ) -> None:
        self.stacks[name] = (stack, subgroup)

    def open_zarr(self, sim_id: str) -> _PolicyRecorder:
        return _PolicyRecorder(self)


def _drn_recarray(node: int, q: float) -> np.recarray:
    rec = np.zeros(1, dtype=[("node", "<i4"), ("q", "<f8")])
    rec["node"][0] = node
    rec["q"][0] = q
    return rec.view(np.recarray)


def _run_extract(
    fake_cbb: _FakeCbb,
    monkeypatch: pytest.MonkeyPatch,
    *,
    budget_terms: BudgetKeep | None = None,
    store: Any = None,
    stream_constant_head_mask: np.ndarray | None = None,
) -> Any:
    from hydromodpy.solver.modflow6.extractors import cbc_reader

    monkeypatch.setattr(cbc_reader, "Mf6CellBudgetReader", lambda *args, **kwargs: fake_cbb)
    store = _FakeStore() if store is None else store
    Modflow6OutputAdapter()._extract_budget(
        "sim",
        store,
        Path("unused.cbc"),
        times=[1.0, 2.0],
        kstpkpers=[(0, 0), (0, 1)],
        budget_terms=BudgetKeep.everything() if budget_terms is None else budget_terms,
        nlay=1,
        n_cells=4,
        seconds_per_time_unit=_SPT,
        stream_constant_head_mask=stream_constant_head_mask,
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


class TestCatchmentBudgetZone:
    """The second budget row whose support is the basin, not the buffered box.

    MODFLOW 6 meshes a box wider than the catchment, so the ``zone_id = "0"``
    row takes in the neighbouring basins. The per-cell array is in memory while
    the budget is read and dropped right after unless the run keeps the term,
    so this is the one place the basin can be summed for free.
    """

    def _rcha_cbb(self) -> _FakeCbb:
        payload = np.array([[[1.0, -2.0, 3.0, -4.0]]])
        return _FakeCbb([(1, 1, _NAMES[1], payload)])

    def _extract(self, cbb, monkeypatch, mask):
        from hydromodpy.solver.modflow6.extractors import cbc_reader

        monkeypatch.setattr(cbc_reader, "Mf6CellBudgetReader", lambda *a, **k: cbb)
        store = _FakeStore()
        Modflow6OutputAdapter()._extract_budget(
            "sim",
            store,
            Path("unused.cbc"),
            times=[1.0],
            kstpkpers=[(0, 0)],
            budget_terms=BudgetKeep.of_terms(()),
            nlay=1,
            n_cells=4,
            seconds_per_time_unit=_SPT,
            catchment_mask=mask,
        )
        return store

    def test_mask_adds_a_catchment_row_summed_on_the_basin_only(self, monkeypatch):
        mask = np.array([True, False, True, False])

        store = self._extract(self._rcha_cbb(), monkeypatch, mask)

        by_zone = {row["zone_id"]: row for row in store.budgets}
        assert set(by_zone) == {"0", CATCHMENT_BUDGET_ZONE}
        # Domain keeps every cell: +1 +3 in, -2 -4 out.
        assert by_zone["0"]["flux_in"] == pytest.approx(4.0 / _SPT)
        assert by_zone["0"]["flux_out"] == pytest.approx(6.0 / _SPT)
        # The basin holds cells 0 and 2, so it sees no outflow at all.
        assert by_zone[CATCHMENT_BUDGET_ZONE]["flux_in"] == pytest.approx(4.0 / _SPT)
        assert by_zone[CATCHMENT_BUDGET_ZONE]["flux_out"] == pytest.approx(0.0)
        assert by_zone[CATCHMENT_BUDGET_ZONE]["component"] == by_zone["0"]["component"]
        assert by_zone[CATCHMENT_BUDGET_ZONE]["unit"] == "m3/s"

    def test_without_a_mask_only_the_domain_row_is_written(self, monkeypatch):
        store = self._extract(self._rcha_cbb(), monkeypatch, None)

        assert [row["zone_id"] for row in store.budgets] == ["0"]

    def test_an_empty_basin_is_not_written_as_zero(self, monkeypatch):
        # An all-false mask would write a row of zeros under a name that claims
        # to be the catchment, which is worse than carrying no row at all.
        store = self._extract(self._rcha_cbb(), monkeypatch, np.zeros(4, dtype=bool))

        rows = [row for row in store.budgets if row["zone_id"] == CATCHMENT_BUDGET_ZONE]
        assert rows == [] or rows[0]["flux_in"] != 0.0 or rows[0]["flux_out"] != 0.0


# -- what the run keeps of the per-cell budget --------------------------------

_ALL_NAMES = [
    b"    FLOW-JA-FACE",
    b"            RCHA",
    b"             DRN",
    b"          STO-SS",
    b"          STO-SY",
    b"             CHD",
    b"             GHB",
]
_CANONICAL = {
    "recharge",
    "drain",
    "storage_ss",
    "storage_sy",
    "constant_head",
    "general_head",
}


def _every_record_cbb() -> _FakeCbb:
    records: list[tuple[int, int, bytes, Any]] = []
    for kper in (1, 2):
        records.append((1, kper, _ALL_NAMES[0], np.full((1, 1, 4), 9.9)))
        for rank, name in enumerate(_ALL_NAMES[1:], start=1):
            payload = np.array([[[1.0, -2.0, 0.5, 0.0]]]) * rank * kper
            records.append((1, kper, name, payload))
    return _FakeCbb(records, names=_ALL_NAMES)


_STREAM_MASK = np.array([[False, True, True, False]])


class _FieldMeanSpy:
    """Count the per-cell means the extractor computes: one per slab entry."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.calls = 0
        real = mf6_flow.weighted_period_mean

        def spy(fields, weights):
            self.calls += 1
            return real(fields, weights)

        monkeypatch.setattr(mf6_flow, "weighted_period_mean", spy)


def test_everything_writes_each_scalar_record_under_its_canonical_name(monkeypatch):
    store = _run_extract(_every_record_cbb(), monkeypatch)

    assert set(store.stacks) == _CANONICAL
    assert all(subgroup == "budget" for _stack, subgroup in store.stacks.values())
    sto_ss, _ = store.stacks["storage_ss"]
    np.testing.assert_allclose(sto_ss[1, 0], np.array([1.0, -2.0, 0.5, 0.0]) * 3 * 2 / _SPT)


def test_everything_writes_the_stream_constant_head_with_a_stream_mask(monkeypatch):
    store = _run_extract(_every_record_cbb(), monkeypatch, stream_constant_head_mask=_STREAM_MASK)

    assert set(store.stacks) == _CANONICAL | {STREAM_CONSTANT_HEAD_BUDGET}


def test_an_unkept_term_never_gets_a_slab(monkeypatch):
    spy = _FieldMeanSpy(monkeypatch)
    store = _run_extract(
        _every_record_cbb(), monkeypatch, budget_terms=BudgetKeep.of_terms({"recharge"})
    )

    assert set(store.stacks) == {"recharge"}
    # Two stamps of one kept record: no other per-cell mean was computed.
    assert spy.calls == 2


def test_a_lumped_run_builds_no_slab_at_all(monkeypatch):
    spy = _FieldMeanSpy(monkeypatch)
    store = _run_extract(_every_record_cbb(), monkeypatch, budget_terms=BudgetKeep.of_terms(()))

    assert store.stacks == {}
    assert spy.calls == 0


@pytest.mark.parametrize(
    "budget_terms",
    [BudgetKeep.of_terms(()), BudgetKeep.of_terms({"recharge", "storage_sy"})],
    ids=["lumped", "two_terms"],
)
def test_the_budget_table_does_not_depend_on_the_kept_terms(monkeypatch, budget_terms):
    mask = _STREAM_MASK
    reference = _run_extract(_every_record_cbb(), monkeypatch, stream_constant_head_mask=mask)
    filtered = _run_extract(
        _every_record_cbb(),
        monkeypatch,
        budget_terms=budget_terms,
        stream_constant_head_mask=mask,
    )

    assert filtered.budgets == reference.budgets
    assert {row["component"] for row in reference.budgets} == _CANONICAL


def test_the_stream_constant_head_is_kept_without_the_constant_head(monkeypatch):
    store = _run_extract(
        _every_record_cbb(),
        monkeypatch,
        budget_terms=BudgetKeep.of_terms({STREAM_CONSTANT_HEAD_BUDGET}),
        stream_constant_head_mask=_STREAM_MASK,
    )

    assert set(store.stacks) == {STREAM_CONSTANT_HEAD_BUDGET}
    stream, subgroup = store.stacks[STREAM_CONSTANT_HEAD_BUDGET]
    assert subgroup == "budget"
    chd_rank = 5
    expected = np.where(_STREAM_MASK, np.array([[1.0, -2.0, 0.5, 0.0]]) * chd_rank, 0.0) / _SPT
    np.testing.assert_allclose(stream[0], expected)


def test_the_extractor_records_its_policy_once(monkeypatch):
    keep = BudgetKeep.of_terms({"recharge", "lake"})
    store = _run_extract(_every_record_cbb(), monkeypatch, budget_terms=keep)

    assert store.policies == [(keep, ["recharge"])]


class _ZarrBackedStore:
    """A catalog stand-in that writes into a real field store."""

    def __init__(self, path: Path) -> None:
        self.path = path
        SimulationZarr.create(path, n_cells=4, n_layers=1).close()
        self.budgets: list[dict] | None = None

    def write_budgets(self, sim_id: str, records: list[dict]) -> None:
        self.budgets = records

    def write_field_stack(self, sim_id: str, name: str, values: np.ndarray, **kwargs: Any):
        sz = SimulationZarr(self.path)
        try:
            sz.write_field_stack(name, values, **kwargs)
        finally:
            sz.close()

    def open_zarr(self, sim_id: str) -> SimulationZarr:
        return SimulationZarr(self.path)

    def budget_attrs(self) -> dict[str, Any]:
        sz = SimulationZarr(self.path)
        try:
            return dict(sz.root["budget"].attrs)
        finally:
            sz.close()


def test_the_store_says_it_kept_every_written_term(monkeypatch, tmp_path):
    store = _run_extract(
        _every_record_cbb(),
        monkeypatch,
        store=_ZarrBackedStore(tmp_path / "fields.zarr"),
        stream_constant_head_mask=_STREAM_MASK,
    )

    attrs = store.budget_attrs()
    assert attrs[BUDGET_POLICY_ATTR] == POLICY_ALL
    assert attrs[BUDGET_KEPT_TERMS_ATTR] == sorted(_CANONICAL | {STREAM_CONSTANT_HEAD_BUDGET})


def test_the_store_says_it_kept_the_planned_terms(monkeypatch, tmp_path):
    keep = BudgetKeep.of_terms({"drain", "lake"})
    store = _run_extract(
        _every_record_cbb(),
        monkeypatch,
        budget_terms=keep,
        store=_ZarrBackedStore(tmp_path / "fields.zarr"),
    )

    attrs = store.budget_attrs()
    assert attrs[BUDGET_POLICY_ATTR] == POLICY_CONSUMERS
    # ``lake`` is planned but not produced: kept, with no array.
    assert attrs[BUDGET_KEPT_TERMS_ATTR] == ["drain", "lake"]
    sz = SimulationZarr(store.path)
    try:
        assert sorted(sz.root["budget"].array_keys()) == ["drain"]
        assert kept_budget(sz.root) == (POLICY_CONSUMERS, ("drain", "lake"))
    finally:
        sz.close()


def test_a_lumped_store_still_carries_its_budget_group(monkeypatch, tmp_path):
    store = _run_extract(
        _every_record_cbb(),
        monkeypatch,
        budget_terms=BudgetKeep.of_terms(()),
        store=_ZarrBackedStore(tmp_path / "fields.zarr"),
    )

    attrs = store.budget_attrs()
    assert attrs[BUDGET_POLICY_ATTR] == POLICY_CONSUMERS
    assert attrs[BUDGET_KEPT_TERMS_ATTR] == []
