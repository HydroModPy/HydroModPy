"""Budget terms read from a MODFLOW 6 .cbc file (fluxes in m3/s).

One pass over the records gives the scalar terms by component, their per-cell
stacks, a catchment row, and the policy of what the run keeps. Intercell face
flows (FLOW-JA-FACE) and specific discharge (DATA-SPDIS, m/s) are never terms.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from hydromodpy.core.budget.flux import STREAM_CONSTANT_HEAD_BUDGET
from hydromodpy.core.budget.terms import (
    BUDGET_KEPT_TERMS_ATTR,
    BUDGET_POLICY_ATTR,
    POLICY_CONSUMERS,
    BudgetKeep,
)
from hydromodpy.core.scope import CATCHMENT
from hydromodpy.results.zarr_store.simulation_zarr import SimulationZarr
from hydromodpy.solver.modflow6.extractors.budget import extract_budget
from hydromodpy.solver.modflow6.extractors.cbc_reader import CbcRecord
from hydromodpy.solver.modflow_common.budget_components import is_scalar_budget_component

SECONDS_PER_DAY = 86400.0  # one time unit is a day
NAMES = [b"    FLOW-JA-FACE", b"            RCHA", b"             DRN", b"             EVT"]


class FakeCbb:
    def __init__(
        self, records: list[tuple[int, int, bytes, Any]], names: list[bytes] | None = None
    ):
        self._names = list(NAMES if names is None else names)
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


class PolicyRecorder:
    def __init__(self, owner: FakeStore) -> None:
        self._owner = owner

    def write_budget_policy(self, keep: BudgetKeep, written: Any) -> None:
        self._owner.policies.append((keep, sorted(written)))

    def close(self) -> None:
        pass


class FakeStore:
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

    def open_zarr(self, sim_id: str) -> PolicyRecorder:
        return PolicyRecorder(self)


def drn_recarray(node: int, q: float) -> np.recarray:
    rec = np.zeros(1, dtype=[("node", "<i4"), ("q", "<f8")])
    rec["node"][0] = node
    rec["q"][0] = q
    return rec.view(np.recarray)


def run_extract(
    fake_cbb: FakeCbb,
    monkeypatch: pytest.MonkeyPatch,
    *,
    budget_terms: BudgetKeep | None = None,
    store: Any = None,
    stream_constant_head_mask: np.ndarray | None = None,
) -> Any:
    from hydromodpy.solver.modflow6.extractors import cbc_reader

    monkeypatch.setattr(cbc_reader, "Mf6CellBudgetReader", lambda *args, **kwargs: fake_cbb)
    store = FakeStore() if store is None else store
    extract_budget(
        "sim",
        store,
        Path("unused.cbc"),
        times=[1.0, 2.0],
        kstpkpers=[(0, 0), (0, 1)],
        budget_terms=BudgetKeep.everything() if budget_terms is None else budget_terms,
        nlay=1,
        n_cells=4,
        seconds_per_time_unit=SECONDS_PER_DAY,
        stream_constant_head_mask=stream_constant_head_mask,
    )
    return store


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> FakeStore:
    fake = FakeCbb(
        [
            (1, 1, NAMES[0], np.full((1, 1, 4), 9.9)),  # FLOW-JA-FACE: excluded
            (1, 1, NAMES[1], np.array([[[1.0, -2.0, 3.0, 0.0]]])),
            (1, 1, NAMES[2], drn_recarray(node=2, q=-5.0)),
            (1, 1, NAMES[2], drn_recarray(node=3, q=-99.0)),  # 2nd DRN package: dropped
            (1, 1, NAMES[3], np.array([[[0.0, -1.0, 0.0, 0.0]]])),  # EVT only at t0
            (1, 2, NAMES[1], np.array([[[2.0, 0.0, 0.0, 0.0]]])),
            (1, 2, NAMES[2], drn_recarray(node=1, q=4.0)),
        ]
    )
    out = run_extract(fake, monkeypatch)
    assert fake.closed
    return out


def test_records_by_time_then_component(store: FakeStore) -> None:
    assert store.budgets is not None
    keys = [(rec["timestep"], rec["component"]) for rec in store.budgets]
    assert keys == [
        (0, "recharge"),
        (0, "drain"),
        (0, "evapotranspiration"),
        (1, "recharge"),
        (1, "drain"),
    ]


def test_fluxes_scaled_and_split(store: FakeStore) -> None:
    by_key = {(rec["timestep"], rec["component"]): rec for rec in store.budgets}
    rcha0 = by_key[(0, "recharge")]
    assert rcha0["flux_in"] == pytest.approx(4.0 / SECONDS_PER_DAY)
    assert rcha0["flux_out"] == pytest.approx(2.0 / SECONDS_PER_DAY)
    assert rcha0["zone_id"] == "domain"
    assert rcha0["unit"] == "m3 s-1"
    drn1 = by_key[(1, "drain")]
    assert drn1["flux_in"] == pytest.approx(4.0 / SECONDS_PER_DAY)
    assert drn1["flux_out"] == pytest.approx(0.0)


def test_first_duplicate_package_wins(store: FakeStore) -> None:
    drn0 = next(r for r in store.budgets if r["timestep"] == 0 and r["component"] == "drain")
    assert drn0["flux_out"] == pytest.approx(5.0 / SECONDS_PER_DAY)


def test_stacks_per_component(store: FakeStore) -> None:
    rcha_stack, subgroup = store.stacks["recharge"]
    assert subgroup == "budget"
    assert rcha_stack.shape == (2, 1, 4)
    np.testing.assert_allclose(rcha_stack[0, 0], np.array([1.0, -2.0, 3.0, 0.0]) / SECONDS_PER_DAY)
    drn_stack, _ = store.stacks["drain"]
    np.testing.assert_allclose(drn_stack[0, 0], np.array([0.0, -5.0, 0.0, 0.0]) / SECONDS_PER_DAY)
    evt_stack, _ = store.stacks["evapotranspiration"]
    assert np.isnan(evt_stack[1]).all()  # EVT has no t1 record


def test_unreadable_record_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeCbb(
        [
            (1, 1, NAMES[1], ValueError("corrupt record")),
            (1, 2, NAMES[1], np.array([[[1.0, 0.0, 0.0, 0.0]]])),
        ]
    )
    store = run_extract(fake, monkeypatch)
    assert [(r["timestep"], r["component"]) for r in store.budgets] == [(1, "recharge")]


def test_unknown_stamp_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeCbb([(7, 9, NAMES[1], np.array([[[1.0, 0.0, 0.0, 0.0]]]))])
    store = run_extract(fake, monkeypatch)
    assert store.budgets is None
    assert store.stacks == {}


def rcha_cbb() -> FakeCbb:
    payload = np.array([[[1.0, -2.0, 3.0, -4.0]]])
    return FakeCbb([(1, 1, NAMES[1], payload)])


def extract_with_mask(monkeypatch, mask):
    from hydromodpy.solver.modflow6.extractors import cbc_reader

    monkeypatch.setattr(cbc_reader, "Mf6CellBudgetReader", lambda *a, **k: rcha_cbb())
    store = FakeStore()
    extract_budget(
        "sim",
        store,
        Path("unused.cbc"),
        times=[1.0],
        kstpkpers=[(0, 0)],
        budget_terms=BudgetKeep.of_terms(()),
        nlay=1,
        n_cells=4,
        seconds_per_time_unit=SECONDS_PER_DAY,
        catchment_mask=mask,
    )
    return store


def test_catchment_row_sums_basin_only(monkeypatch):
    # The box is wider than the basin, so "domain" takes in the neighbouring basins.
    store = extract_with_mask(monkeypatch, np.array([True, False, True, False]))

    by_zone = {row["zone_id"]: row for row in store.budgets}
    assert set(by_zone) == {"domain", CATCHMENT}
    # Domain keeps every cell: +1 +3 in, -2 -4 out.
    assert by_zone["domain"]["flux_in"] == pytest.approx(4.0 / SECONDS_PER_DAY)
    assert by_zone["domain"]["flux_out"] == pytest.approx(6.0 / SECONDS_PER_DAY)
    # The basin holds cells 0 and 2, so it sees no outflow at all.
    assert by_zone[CATCHMENT]["flux_in"] == pytest.approx(4.0 / SECONDS_PER_DAY)
    assert by_zone[CATCHMENT]["flux_out"] == pytest.approx(0.0)
    assert by_zone[CATCHMENT]["component"] == by_zone["domain"]["component"]
    assert by_zone[CATCHMENT]["unit"] == "m3 s-1"


def test_empty_basin_no_zero_row(monkeypatch):
    # A row of zeros named catchment is worse than no row.
    store = extract_with_mask(monkeypatch, np.zeros(4, dtype=bool))

    rows = [row for row in store.budgets if row["zone_id"] == CATCHMENT]
    assert rows == [] or rows[0]["flux_in"] != 0.0 or rows[0]["flux_out"] != 0.0


EVERY_NAMES = [
    b"    FLOW-JA-FACE",
    b"            RCHA",
    b"             DRN",
    b"          STO-SS",
    b"          STO-SY",
    b"             CHD",
    b"             GHB",
]
CANONICAL = {
    "recharge",
    "drain",
    "storage_ss",
    "storage_sy",
    "constant_head",
    "general_head",
}


def every_record_cbb() -> FakeCbb:
    records: list[tuple[int, int, bytes, Any]] = []
    for kper in (1, 2):
        records.append((1, kper, EVERY_NAMES[0], np.full((1, 1, 4), 9.9)))
        for rank, name in enumerate(EVERY_NAMES[1:], start=1):
            payload = np.array([[[1.0, -2.0, 0.5, 0.0]]]) * rank * kper
            records.append((1, kper, name, payload))
    return FakeCbb(records, names=EVERY_NAMES)


STREAM_MASK = np.array([[False, True, True, False]])


def test_everything_keeps_canonical_names(monkeypatch):
    store = run_extract(every_record_cbb(), monkeypatch)

    assert set(store.stacks) == CANONICAL
    assert all(subgroup == "budget" for _stack, subgroup in store.stacks.values())
    sto_ss, _ = store.stacks["storage_ss"]
    np.testing.assert_allclose(
        sto_ss[1, 0], np.array([1.0, -2.0, 0.5, 0.0]) * 3 * 2 / SECONDS_PER_DAY
    )


@pytest.mark.parametrize(
    "budget_terms",
    [BudgetKeep.of_terms(()), BudgetKeep.of_terms({"recharge", "storage_sy"})],
    ids=["lumped", "two_terms"],
)
def test_table_independent_of_kept_terms(monkeypatch, budget_terms):
    mask = STREAM_MASK
    reference = run_extract(every_record_cbb(), monkeypatch, stream_constant_head_mask=mask)
    filtered = run_extract(
        every_record_cbb(),
        monkeypatch,
        budget_terms=budget_terms,
        stream_constant_head_mask=mask,
    )

    assert filtered.budgets == reference.budgets
    assert {row["component"] for row in reference.budgets} == CANONICAL


def test_stream_chd_kept_alone(monkeypatch):
    store = run_extract(
        every_record_cbb(),
        monkeypatch,
        budget_terms=BudgetKeep.of_terms({STREAM_CONSTANT_HEAD_BUDGET}),
        stream_constant_head_mask=STREAM_MASK,
    )

    assert set(store.stacks) == {STREAM_CONSTANT_HEAD_BUDGET}
    stream, subgroup = store.stacks[STREAM_CONSTANT_HEAD_BUDGET]
    assert subgroup == "budget"
    chd_rank = 5
    expected = (
        np.where(STREAM_MASK, np.array([[1.0, -2.0, 0.5, 0.0]]) * chd_rank, 0.0) / SECONDS_PER_DAY
    )
    np.testing.assert_allclose(stream[0], expected)


class ZarrBackedStore:
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


def test_lumped_store_keeps_budget_group(monkeypatch, tmp_path):
    store = run_extract(
        every_record_cbb(),
        monkeypatch,
        budget_terms=BudgetKeep.of_terms(()),
        store=ZarrBackedStore(tmp_path / "fields.zarr"),
    )

    attrs = store.budget_attrs()
    assert attrs[BUDGET_POLICY_ATTR] == POLICY_CONSUMERS
    assert attrs[BUDGET_KEPT_TERMS_ATTR] == []


class ScalarStore:
    # No field store: the extractor records no budget policy.
    save_zarr = False

    def __init__(self) -> None:
        self.budgets: list | None = None

    def write_budgets(self, sim_id, records) -> None:
        self.budgets = records


def fake_cbc_reader(record_data: dict, kstpkpers: list[tuple[int, int]]):
    # record_data maps record name -> {kstpkper: array} or array (all steps).
    flat: list[tuple[int, int, str, np.ndarray]] = []
    for name, entry in record_data.items():
        for kstpkper in kstpkpers:
            payload = entry[kstpkper] if isinstance(entry, dict) else entry
            flat.append((kstpkper[0] + 1, kstpkper[1] + 1, name, payload))

    class _FakeCBC:
        def __init__(self, path, *args, **kwargs):
            del path, args, kwargs
            self.records = tuple(
                CbcRecord(
                    kstp=kstp,
                    kper=kper,
                    text=text,
                    imeth=1,
                    delt=1.0,
                    totim=1.0,
                    ndim1=2,
                    ndim2=1,
                    ndim3=-1,
                    nlist=0,
                    aux_names=(),
                    data_pos=0,
                )
                for kstp, kper, text, _ in flat
            )

        def unique_record_names(self):
            return list(record_data)

        def read_record(self, idx: int):
            return flat[idx][3]

        def close(self) -> None:
            pass

    return _FakeCBC


def extract_scalars(monkeypatch, tmp_path, record_data, *, times, kstpkpers, nlay=1, n_cells=2):
    monkeypatch.setattr(
        "hydromodpy.solver.modflow6.extractors.cbc_reader.Mf6CellBudgetReader",
        fake_cbc_reader(record_data, kstpkpers),
        raising=True,
    )
    store = ScalarStore()
    extract_budget(
        "sim",
        store,
        tmp_path / "flow.cbc",
        times,
        kstpkpers,
        budget_terms=BudgetKeep.of_terms(()),
        nlay=nlay,
        n_cells=n_cells,
        seconds_per_time_unit=1.0,
    )
    return store


SCALARNAMES = [
    pytest.param("FLOW-JA-FACE", False, id="face flow"),
    pytest.param("flow-ja-face", False, id="face flow lower case"),
    pytest.param("  FLOW-JA-FACE  ", False, id="face flow padded"),
    pytest.param("DATA-SPDIS", False, id="specific discharge"),
    pytest.param("FLOW RIGHT FACE", False, id="right face"),
    pytest.param("FLOW FRONT FACE", False, id="front face"),
    pytest.param("FLOW LOWER FACE", False, id="lower face"),
    *[
        pytest.param(name, True, id=name.lower())
        for name in ("DRN", "WEL", "RCHA", "EVT", "CHD", "STO-SS", "STO-SY", "STORAGE")
    ],
]


@pytest.mark.parametrize(("name", "is_scalar"), SCALARNAMES)
def test_scalar_component_names(name: str, is_scalar: bool) -> None:
    assert is_scalar_budget_component(name) is is_scalar


def test_face_flow_and_spdis_dropped(tmp_path, monkeypatch) -> None:
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
    store = extract_scalars(monkeypatch, tmp_path, records, times=[1.0], kstpkpers=[(0, 0)])
    by = {r["component"]: r for r in store.budgets}
    assert set(by) == {"drain", "recharge"}
    assert by["recharge"]["flux_in"] == pytest.approx(5.0)
    assert by["drain"]["flux_out"] == pytest.approx(5.0)


def test_balanced_term_kept(tmp_path, monkeypatch) -> None:
    records = {
        "WEL": np.array([10.0, -10.0]),
        "FLOW-JA-FACE": np.array([1.0, -1.0]),
    }
    store = extract_scalars(monkeypatch, tmp_path, records, times=[1.0], kstpkpers=[(0, 0)])
    assert len(store.budgets) == 1
    row = store.budgets[0]
    assert row["component"] == "well"
    assert row["flux_in"] == pytest.approx(10.0)
    assert row["flux_out"] == pytest.approx(10.0)


def test_spdis_alone_no_term(tmp_path, monkeypatch) -> None:
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
    store = extract_scalars(
        monkeypatch, tmp_path, {"DATA-SPDIS": spdis}, times=[1.0], kstpkpers=[(0, 0)]
    )
    # No scalar budget term at all; the velocity magnitudes never appear.
    assert store.budgets is None


def test_two_layers_and_two_steps(tmp_path, monkeypatch) -> None:
    # nlay=2, n_cells=2: node = lay*n_cells + cell + 1.
    drn_t0 = np.array([(1, 1, -3.0)], dtype=[("node", "<i4"), ("node2", "<i4"), ("q", "<f8")])
    drn_t1 = np.array([(4, 4, -7.0)], dtype=[("node", "<i4"), ("node2", "<i4"), ("q", "<f8")])
    records = {
        "DRN": {(0, 0): drn_t0, (1, 0): drn_t1},
        "FLOW-JA-FACE": {(0, 0): np.array([2.0, -2.0]), (1, 0): np.array([2.0, -2.0])},
    }
    store = extract_scalars(
        monkeypatch,
        tmp_path,
        records,
        times=[1.0, 2.0],
        kstpkpers=[(0, 0), (1, 0)],
        nlay=2,
        n_cells=2,
    )
    by_step = {r["timestep"]: r for r in store.budgets}
    assert {r["component"] for r in store.budgets} == {"drain"}
    assert by_step[0]["flux_out"] == pytest.approx(3.0)
    assert by_step[1]["flux_out"] == pytest.approx(7.0)
