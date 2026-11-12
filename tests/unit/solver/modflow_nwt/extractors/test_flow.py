"""What the MODFLOW-NWT extractor writes in the store from a solved run.

A budget term is positive where water enters the aquifer and negative where it leaves, and is
stored as an inflow and an outflow, both positive. The intercell face flows are antisymmetric, so
they never become a budget term. A face flow is positive towards the cell of the larger flat index.
A head equal to ``hdry`` or ``hnoflo`` (or of about 1e30) is not a head and becomes NaN. The
retention of the run decides the per-cell budget terms and the model gives the layering and the
start date of the time axis (s).
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.budget.terms import BudgetKeep
from hydromodpy.core.exceptions import ExtractError, NothingThereError
from hydromodpy.core.fields.vertical_column import (
    VERTICAL_LAYOUT_COLUMN_FRACTIONS,
    VERTICAL_LAYOUT_SURFACES,
)
from hydromodpy.model.domain.domain_config import DomainConfig
from hydromodpy.model.model import ModelTime
from hydromodpy.results.field_registry import CONNECTION_CELLS, FACE_FLOW
from hydromodpy.solver.modflow_common.flow_run import final_state_head
from hydromodpy.solver.modflow_nwt.extractors import flow as nwt_flow
from hydromodpy.solver.modflow_nwt.extractors.flow import ModflowNwtOutputAdapter, face_connections
from hydromodpy.solver.modflow_nwt.nwt.nwt_config import ModflowConfig
from tests._helpers.model_factory import make_model, small_geometry, time_grid
from tests.unit.solver.modflow_common.solver_runs import keep_all, retention, solved_run

# Budget records are read from a fake cell-by-cell budget file of one layer and one row.
EVERYTHING = BudgetKeep.everything()
LUMPED = BudgetKeep.of_terms(())
N_CELLS = 4

FACE_FLOWS = {
    "FLOW RIGHT FACE": np.array([8.0, -8.0, 3.0, -3.0]),
    "FLOW FRONT FACE": np.array([2.0, -2.0, 5.0, -5.0]),
}
EVERY_RECORD = {
    "STORAGE": np.array([0.5, -0.5, 0.25, 0.0]),
    "CONSTANT HEAD": np.array([0.0, 1.0, 0.0, -1.0]),
    "DRAINS": np.array([-5.0, 0.0, -1.5, 0.0]),
    "RECHARGE": np.full(N_CELLS, 1.25),
    "HEAD DEP BOUNDS": np.array([0.0, 0.0, 2.0, -2.0]),
}

# Default sentinels of the backend, and those of the sentinel-head table.
HDRY, HNOFLO = -100.0, -9999.0
TABLE_HDRY, TABLE_HNOFLO = -888.0, -9999.0


class _BudgetStore:
    """A store that keeps every budget write the extractor asks for."""

    def __init__(self) -> None:
        self.budgets: list[dict] = []
        self.fields: list[tuple[str, str | None, np.ndarray]] = []

    def write_budgets(self, sim_id: str, records: list[dict]) -> None:
        self.budgets.extend(records)

    def write_field_stack(self, sim_id: str, name: str, values: np.ndarray, **kwargs) -> None:
        self.fields.append((name, kwargs.get("subgroup"), np.asarray(values)))

    def open_zarr(self, sim_id: str) -> _BudgetStore:
        return self

    def write_budget_policy(self, *args) -> None:
        pass

    def close(self) -> None:
        pass


def fake_cbc(records: dict[str, np.ndarray]):
    """A CellBudgetFile stand-in serving ``records`` at one step, one row, one layer."""
    names = list(records)

    class _FakeCellBudgetFile:
        def __init__(self, path: str, precision: str = "double") -> None:
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
            return np.asarray(records[names[idx]], dtype=float).reshape(1, 1, -1)

        def close(self) -> None:
            pass

    return _FakeCellBudgetFile


def extract_budget(
    monkeypatch, tmp_path: Path, records, *, keep: BudgetKeep = EVERYTHING, scale: float = 1.0
) -> _BudgetStore:
    monkeypatch.setattr("flopy.utils.binaryfile.CellBudgetFile", fake_cbc(records))
    store = _BudgetStore()
    n_cols = len(next(iter(records.values()))) if records else N_CELLS
    ModflowNwtOutputAdapter()._extract_budget(
        "sim",
        store,
        tmp_path / "run.cbc",
        [1.0],
        [(0, 0)],
        1,
        1,
        n_cols,
        budget_terms=keep,
        flux_scale_to_m3_s=scale,
    )
    return store


# One row per drain record: the signed values in model units, the scale to m3/s, and the inflow
# and the outflow stored. A drain loses water, so its values are negative.
BUDGET_SPLIT = [
    pytest.param([-2.0], 1.0, 0.0, 2.0, id="a drain leaving"),
    pytest.param([3.0], 1.0, 3.0, 0.0, id="water entering"),
    pytest.param([-2.0, 3.0, 0.0], 1.0, 3.0, 2.0, id="mixed cells split on their own sign"),
    pytest.param([0.0], 1.0, 0.0, 0.0, id="no flux"),
    pytest.param([-0.0], 1.0, 0.0, 0.0, id="negative zero is no flux"),
    pytest.param([-1.0e-12], 1.0, 0.0, 1.0e-12, id="a tiny loss is a loss"),
    pytest.param([-864.0], 1.0 / 86400.0, 0.0, 0.01, id="per day to per second"),
]


@pytest.mark.parametrize(("values", "scale", "flux_in", "flux_out"), BUDGET_SPLIT)
def test_budget_term_split(monkeypatch, tmp_path, values, scale, flux_in, flux_out) -> None:
    store = extract_budget(monkeypatch, tmp_path, {"DRAINS": values}, scale=scale)

    row = next(row for row in store.budgets if row["zone_id"] != "catchment")
    assert row["component"] == "drain"
    assert row["flux_in"] == pytest.approx(flux_in, abs=1e-18)
    assert row["flux_out"] == pytest.approx(flux_out, abs=1e-18)


def test_face_flows_are_no_budget_term(tmp_path, monkeypatch) -> None:
    records = {"DRAINS": np.array([-5.0, 0.0, 0.0, 0.0]), "RECHARGE": np.full(N_CELLS, 1.25)}

    store = extract_budget(monkeypatch, tmp_path, records | FACE_FLOWS, keep=LUMPED)

    assert {row["component"] for row in store.budgets} == {"drain", "recharge"}


def test_stress_terms_fluxes(tmp_path, monkeypatch) -> None:
    records = {"DRAINS": np.array([-5.0, 0.0, -1.5, 0.0]), "RECHARGE": np.full(N_CELLS, 1.25)}

    store = extract_budget(monkeypatch, tmp_path, records | FACE_FLOWS)

    by_component = {row["component"]: row for row in store.budgets}
    assert by_component["drain"]["flux_out"] == pytest.approx(6.5)
    assert by_component["drain"]["flux_in"] == pytest.approx(0.0)
    assert by_component["recharge"]["flux_in"] == pytest.approx(5.0)
    drain_field = next(values for name, _sub, values in store.fields if name == "drain")
    assert drain_field.shape == (1, 1, N_CELLS)
    assert drain_field[0, 0].tolist() == [-5.0, 0.0, -1.5, 0.0]


def test_only_face_flows_write_nothing(tmp_path, monkeypatch) -> None:
    store = extract_budget(monkeypatch, tmp_path, dict(FACE_FLOWS))

    assert store.budgets == []
    assert store.fields == []


@pytest.mark.parametrize(
    "keep",
    [
        pytest.param(LUMPED, id="lumped"),
        pytest.param(BudgetKeep.of_terms({"storage", "recharge"}), id="two terms"),
    ],
)
def test_budget_ignores_kept_terms(tmp_path, monkeypatch, keep) -> None:
    reference = extract_budget(monkeypatch, tmp_path, EVERY_RECORD)
    filtered = extract_budget(monkeypatch, tmp_path, EVERY_RECORD, keep=keep)

    assert filtered.budgets == reference.budgets
    assert len(reference.budgets) == len(EVERY_RECORD)


def faces(right, front=None, lower=None, active=None):
    shape = np.shape(right)
    zeros = np.zeros(shape)
    return face_connections(
        np.asarray(right, dtype=float),
        zeros if front is None else np.asarray(front, dtype=float),
        zeros if lower is None else np.asarray(lower, dtype=float),
        active=np.ones(shape, dtype=bool) if active is None else active,
    )


# One row per grid: the right, front and lower face records, the active cells, the flat
# index pairs and the flow of each pair.
FACE_PAIRS = [
    # Three columns in a row. +2 flows from cell 0 to cell 1, -3 flows from cell 2 to cell 1
    # (against the index), and the last column has no face to the right, so its 9.0 is dropped.
    pytest.param([[[2.0, -3.0, 9.0]]], None, None, None, [[0, 1], [1, 2]], [2.0, -3.0], id="right"),
    # Two layers, two rows, one column: flat index = layer * 2 + row.
    pytest.param(
        np.zeros((2, 2, 1)),
        [[[1.5], [0.0]], [[2.5], [0.0]]],
        [[[4.0], [5.0]], [[0.0], [0.0]]],
        None,
        [[0, 1], [0, 2], [1, 3], [2, 3]],
        [1.5, 4.0, 5.0, 2.5],
        id="front to the next row, lower to the next layer",
    ),
    pytest.param(
        [[[1.0, 2.0, 3.0, 4.0]]],
        None,
        None,
        np.array([[[True, False, True, True]]]),
        [[2, 3]],
        [3.0],
        id="a pair that touches an inactive cell is left out",
    ),
]


@pytest.mark.parametrize(("right", "front", "lower", "active", "pairs", "flows"), FACE_PAIRS)
def test_face_connections(right, front, lower, active, pairs, flows) -> None:
    cells, found = faces(right, front, lower, active)

    assert cells.tolist() == pairs
    assert found.tolist() == flows


class _FaceBudget:
    """One saved step of a CBC file: the records named, each a grid array."""

    def __init__(self, records: dict[str, np.ndarray]) -> None:
        self._arrays = list(records.values())
        self.recordarray = np.array(
            [(1, 1, 1, 86400.0, 86400.0, name.rjust(16).encode()) for name in records],
            dtype=[
                ("kstp", "i4"),
                ("kper", "i4"),
                ("imeth", "i4"),
                ("delt", "f8"),
                ("totim", "f8"),
                ("text", "S16"),
            ],
        )

    def get_record(self, index: int, full3D: bool = False) -> np.ndarray:
        return self._arrays[index]

    def close(self) -> None:
        pass


class _FaceStore:
    def __init__(self) -> None:
        self.stacks: dict[str, np.ndarray] = {}
        self.static: dict[str, np.ndarray] = {}

    def write_field_stack(self, sim_id, name, stack, *, n_timesteps) -> None:
        self.stacks[name] = stack

    def open_zarr(self, sim_id):
        store = self

        class _Zarr:
            def write_static_field(self, name, values) -> None:
                store.static[name] = values

            def close(self) -> None:
                pass

        return _Zarr()


def extract_face_flows(monkeypatch, records: dict[str, np.ndarray], shape):
    monkeypatch.setattr(nwt_flow, "open_cell_budget", lambda path: _FaceBudget(records))
    monkeypatch.setattr(nwt_flow, "_active_cells", lambda *a: np.ones(shape, dtype=bool))
    store = _FaceStore()
    adapter = object.__new__(ModflowNwtOutputAdapter)
    written = adapter._extract_face_flows(
        "sim",
        store,
        Path("model.cbc"),
        Path("."),
        "model",
        [(0, 0)],
        *shape,
        flux_scale_to_m3_s=0.5,
    )
    return written, store


def test_face_flows_of_one_layer(monkeypatch) -> None:
    shape = (1, 2, 2)
    right = np.zeros(shape)
    right[0, 0, 0] = 2.0
    front = np.zeros(shape)
    front[0, 0, 1] = -4.0

    written, store = extract_face_flows(
        monkeypatch, {"FLOW RIGHT FACE": right, "FLOW FRONT FACE": front}, shape
    )

    assert written == 4
    assert store.static[CONNECTION_CELLS].tolist() == [[0, 1], [0, 2], [1, 3], [2, 3]]
    # 2 m3/d leave cell 0 by its right face towards cell 1: the flow from the first to the second
    # cell is positive. 4 m3/d reach cell 1 from cell 3 by the front face of cell 1: the flow from
    # 1 to 3 is negative.
    np.testing.assert_array_equal(store.stacks[FACE_FLOW], [[1.0, 0.0, -2.0, 0.0]])


# One row per head: its value and whether it becomes NaN. The sentinels the run was configured
# with are caught within one meter, and a head of the order of 1e30 is caught whatever the config.
SENTINEL_HEADS = [
    pytest.param(120.0, False, id="a head"),
    pytest.param(-888.0, True, id="hdry"),
    pytest.param(-888.5, True, id="hdry within a meter"),
    pytest.param(-9999.0, True, id="hnoflo"),
    pytest.param(-9999.9, True, id="hnoflo within a meter"),
    pytest.param(-880.0, False, id="not the sentinel"),
    pytest.param(1.0e30, True, id="mf6 style dry"),
    pytest.param(-1.0e30, True, id="mf6 style dry negative"),
    pytest.param(0.0, False, id="zero is a head"),
]


@pytest.mark.parametrize(("head", "masked"), SENTINEL_HEADS)
def test_sentinel_head_becomes_nan(head, masked) -> None:
    final = final_state_head(
        np.array([[head]]), nlay=1, n_cells=1, sentinels=(TABLE_HDRY, TABLE_HNOFLO)
    )

    assert bool(np.isnan(final[0, 0])) is masked
    if not masked:
        assert final[0, 0] == head


class _HeadStore:
    """A store that keeps the heads and the time axis it is asked to write."""

    sim_id = "sim-1"
    save_zarr = False

    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.heads: np.ndarray | None = None
        self.time: np.ndarray | None = None

    def run_dir_for(self, sim_id: str) -> Path:
        return self.run_dir

    def write_time(self, sim_id: str, values: Any, **_: Any) -> None:
        self.time = np.asarray(values, dtype=float)

    def write_field_stack(self, sim_id: str, name: str, values: np.ndarray, **_: Any) -> None:
        assert name == "head"
        self.heads = np.asarray(values)


class _Heads:
    """A head file of one period whose cells hold two sentinels, a real head and a stray value."""

    def __init__(self, path: str) -> None:
        del path

    def get_times(self) -> list[float]:
        return [86400.0]

    def get_kstpkper(self) -> list[tuple[int, int]]:
        return [(0, 0)]

    def get_data(self, totim: float) -> np.ndarray:
        del totim
        return np.array([[[HDRY, HNOFLO, 12.5, -1234.0]]])

    def close(self) -> None:
        pass


@pytest.fixture
def folder(tmp_path: Path, monkeypatch) -> Path:
    """A run folder holding one head file name, read through ``_Heads``."""
    (tmp_path / "flow.hds").write_text("heads")
    monkeypatch.setattr("flopy.utils.binaryfile.HeadFile", _Heads)
    monkeypatch.setattr(nwt_flow, "record_budget_policy", lambda *_args: None)
    return tmp_path


@pytest.fixture
def surface(monkeypatch) -> list[dict]:
    """Record the keywords the extractor gives the writer of the vertical geometry."""
    calls: list[dict] = []
    monkeypatch.setattr(
        ModflowNwtOutputAdapter,
        "_write_surface_elevation",
        lambda self, *args, **kwargs: calls.append(kwargs),
    )
    return calls


def model_with(*, layers: dict | None = None, **members: Any):
    """A ``Model`` on a domain, which MODFLOW-NWT requires, whose layers are ``layers``."""
    config = DomainConfig.model_validate({"layers": layers or {}})
    geometry = replace(small_geometry(), domain=SimpleNamespace(config=config))
    return make_model(geometry=geometry, **members)


def options_with(**sentinels: dict[str, float]) -> ModflowConfig:
    return ModflowConfig.model_validate({"runtime": sentinels})


MASKED_SENTINELS = [
    pytest.param(options_with(), (HDRY, HNOFLO), id="the defaults of the backend"),
    pytest.param(
        options_with(upw={"hdry": -1234.0}, bas={"hnoflo": -4321.0}),
        (-1234.0, -4321.0),
        id="the sentinels the run was configured with",
    ),
]


@pytest.mark.parametrize(("options", "masked"), MASKED_SENTINELS)
def test_sentinels_of_the_options(
    folder: Path, surface: list[dict], options: ModflowConfig, masked: tuple[float, float]
) -> None:
    store = _HeadStore(folder)

    ModflowNwtOutputAdapter().extract(solved_run(folder, options=options), store, keep_all)

    heads = np.array([HDRY, HNOFLO, 12.5, -1234.0])
    np.testing.assert_array_equal(
        store.heads[0, 0], np.where(np.isin(heads, masked), np.nan, heads)
    )


LAYOUTS = [
    pytest.param(
        {"genmtd_lay": "constant", "nlay": 2}, VERTICAL_LAYOUT_COLUMN_FRACTIONS, id="constant"
    ),
    pytest.param(
        {"genmtd_lay": "surfaces", "layer": [{"name": "a", "depth": 5.0}, {"name": "b"}]},
        VERTICAL_LAYOUT_SURFACES,
        id="surfaces",
    ),
]


@pytest.mark.parametrize(("layers", "layout"), LAYOUTS)
def test_layering_reaches_geometry(
    folder: Path, surface: list[dict], layers: dict, layout: str
) -> None:
    model = model_with(layers=layers)

    ModflowNwtOutputAdapter().extract(
        solved_run(folder, options=options_with(), model=model), _HeadStore(folder), keep_all
    )

    assert surface == [{"vertical_layout": layout}]


def test_default_layout_without_model(folder: Path, surface: list[dict]) -> None:
    store = _HeadStore(folder)

    ModflowNwtOutputAdapter().extract(solved_run(folder, options=options_with()), store, keep_all)

    assert surface == [{"vertical_layout": VERTICAL_LAYOUT_COLUMN_FRACTIONS}]
    assert store.time is not None and store.time[0] == pytest.approx(86400.0)


def test_time_axis_start(folder: Path, surface: list[dict]) -> None:
    grid = time_grid(10)
    grid.boundaries = ("2020-01-01", "2020-01-11")
    model = model_with(time=ModelTime(grid=grid, regime="transient", first_period_steady=False))
    dated, undated = _HeadStore(folder), _HeadStore(folder)

    ModflowNwtOutputAdapter().extract(
        solved_run(folder, options=options_with(), model=model), dated, keep_all
    )
    ModflowNwtOutputAdapter().extract(solved_run(folder, options=options_with()), undated, keep_all)

    assert dated.time is not None and undated.time is not None
    start = pd.Timestamp("2020-01-01", tz="UTC").timestamp()
    assert dated.time[0] - undated.time[0] == pytest.approx(start)


def test_retention_sets_budget_terms(folder: Path, surface: list[dict], monkeypatch) -> None:
    (folder / "flow.cbc").write_text("budget")
    seen: list[BudgetKeep] = []
    monkeypatch.setattr(
        ModflowNwtOutputAdapter,
        "_extract_budget",
        lambda self, *args, budget_terms, **kwargs: seen.append(budget_terms),
    )
    planned = BudgetKeep.of_terms(("drain",))

    ModflowNwtOutputAdapter().extract(
        solved_run(folder, options=options_with()), _HeadStore(folder), retention(planned)
    )

    assert seen == [planned]


def test_refuses_mismatched_faces() -> None:
    with pytest.raises(ExtractError, match="face flows of this run cannot be read"):
        face_connections(
            np.zeros((1, 1, 3)),
            np.zeros((1, 1, 2)),
            np.zeros((1, 1, 3)),
            active=np.ones((1, 1, 3), dtype=bool),
        )


def test_refuses_missing_lower_face(monkeypatch) -> None:
    shape = (2, 2, 2)
    records = {"FLOW RIGHT FACE": np.zeros(shape), "FLOW FRONT FACE": np.zeros(shape)}

    with pytest.raises(ExtractError, match="FLOW LOWER FACE"):
        extract_face_flows(monkeypatch, records, shape)


def test_refuses_no_options(folder: Path, surface: list[dict]) -> None:
    # The sentinels come from the options of the run.
    with pytest.raises(AttributeError):
        ModflowNwtOutputAdapter().extract(solved_run(folder), _HeadStore(folder), keep_all)


def test_refuses_no_head_file(tmp_path: Path) -> None:
    with pytest.raises(NothingThereError, match="No .hds file"):
        ModflowNwtOutputAdapter().extract(
            solved_run(tmp_path, options=options_with()), _HeadStore(tmp_path), keep_all
        )
