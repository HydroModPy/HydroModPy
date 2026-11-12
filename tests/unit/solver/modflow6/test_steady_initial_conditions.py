"""The steady and cyclic initial-condition solves that start a MF6 transient run.

Heads are in m and lake stages in m a.s.l. A steady solve gives the head of a run that starts from
the mean forcing. A cyclic spin-up repeats the run's own period, with the lakes cycling with the
heads, until the largest head change between two cycles is under a tolerance in m.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.runtime.interrupts import StopRequested
from hydromodpy.core.time.steady_initialization import (
    single_period_mean_forcing_time_grid,
)
from hydromodpy.core.time.window import (
    ResolvedSimulationTimeWindow,
    build_simulation_time_boundaries,
    validate_recharge_coverage,
)
from hydromodpy.model.boundaries.boundary_condition_registry import BoundaryConditionBundle
from hydromodpy.model.forcing.cells import stress_period_bounds
from hydromodpy.model.initial.heads import (
    cycles_have_settled,
    summarize_head_initial_condition_bounds,
)
from hydromodpy.model.initial.state import (
    CyclicSpinupStrategy,
    CyclicStart,
    HeadRule,
    SolvedState,
    SteadyStart,
)
from hydromodpy.model.initial_config import FlowInitialConditions, initial_state_of
from hydromodpy.model.model import ModelTime, steady_variant
from hydromodpy.solver.base.plan import RunSlot
from hydromodpy.solver.modflow6.modflow6_config import (
    Modflow6Config,
    Modflow6RuntimeConfig,
)
from hydromodpy.solver.modflow6.support import steady_initial_conditions as ssic
from hydromodpy.solver.modflow6.support.names import mf6_safe_name
from hydromodpy.solver.modflow6.support.steady_initial_conditions import (
    _modflow_config_for_steady_initialization,
    _read_final_percent_discrepancy,
    _steady_initialization_balance_is_acceptable,
)
from hydromodpy.solver.modflow_common.options import ModflowPreprocessOptions
from tests._helpers.model_factory import make_model


def test_steady_config_keeps_looser_settings() -> None:
    config = Modflow6Config(
        runtime=Modflow6RuntimeConfig(
            mf6_outer_dvclose=2e-3,
            mf6_inner_dvclose=3e-3,
            mf6_outer_maximum=1200,
            mf6_inner_maximum=1300,
        )
    )
    model = SimpleNamespace(modflow_config=config, exe="mf6")

    steady_config = _modflow_config_for_steady_initialization(model)

    assert steady_config.runtime.mf6_outer_dvclose == 2e-3
    assert steady_config.runtime.mf6_inner_dvclose == 3e-3
    assert steady_config.runtime.mf6_outer_maximum == 1200
    assert steady_config.runtime.mf6_inner_maximum == 1300


LISTINGS = [
    pytest.param(
        """
 PERCENT DISCREPANCY =        -200.00     PERCENT DISCREPANCY =        -200.00
 PERCENT DISCREPANCY =          -0.00     PERCENT DISCREPANCY =          -0.00
""",
        -0.0,
        True,
        id="closed budget after a non converged step",
    ),
    pytest.param(
        "PERCENT DISCREPANCY = -12.5     PERCENT DISCREPANCY = -12.5\n",
        -12.5,
        False,
        id="open budget",
    ),
]


@pytest.mark.parametrize(("listing", "discrepancy", "acceptable"), LISTINGS)
def test_final_budget(tmp_path, listing, discrepancy, acceptable) -> None:
    list_path = tmp_path / "ssic.lst"
    list_path.write_text(listing, encoding="utf-8")

    assert _read_final_percent_discrepancy(list_path) == discrepancy
    assert _steady_initialization_balance_is_acceptable(list_path) is acceptable


# MF6 names the listing after the safe (lowercase) model name, the head file after the
# output stem, so the solve must read the listing by the safe name.
CLOSED_LISTING = " PERCENT DISCREPANCY =  0.00     PERCENT DISCREPANCY =  0.00\n"


class StubMF6:
    """Names its files the way the MF6 wrapper does and writes a closed, unconverged solve."""

    nlay = 1
    ncpl = 2
    exe = "mf6"
    built: list[object] = []
    converges = False

    def __init__(self, *, model_folder, model_name, **_kwargs) -> None:
        self.model_name = model_name
        self.model_name_mf6 = mf6_safe_name(model_name)
        self.model_output_name = model_name
        self.full_path = str(Path(model_folder) / model_name)
        self.auxiliary = False
        self.modflow_config = None
        self.inputs = make_model()
        self.preprocess_options = ModflowPreprocessOptions()

    def pre_processing(self, inputs, **_kwargs) -> None:
        type(self).built.append(inputs)
        Path(self.full_path).mkdir(parents=True, exist_ok=True)

    def processing(self, _options) -> bool:
        # MF6 stopped short of convergence; its listing carries a closed budget.
        (Path(self.full_path) / f"{self.model_name_mf6}.lst").write_text(CLOSED_LISTING)
        return self.converges


@pytest.fixture
def stub_solve(monkeypatch) -> None:
    """The solves read a head of 0 m and leave the config of the parent alone."""
    monkeypatch.setattr(ssic, "_read_final_head", lambda *_a, **_k: np.zeros((1, 2)))
    monkeypatch.setattr(ssic, "_modflow_config_for_steady_initialization", lambda _m: None)


@pytest.mark.parametrize("converges", [True, False], ids=["converged", "closed budget only"])
def test_steady_solve_convergence_flag(stub_solve, monkeypatch, tmp_path, converges) -> None:
    # The flag the runner reads before a transport run is the verdict of the solve itself.
    monkeypatch.setattr(StubMF6, "converges", converges)
    parent = StubMF6(model_folder=tmp_path, model_name="Run")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        ssic.run_modflow6_steady_state_initialization(parent, verbose=False)

    assert parent.initial_state_converged is converges


def test_cyclic_seed_verdict_is_dropped(monkeypatch, tmp_path) -> None:
    # The cycles settle the state, so the verdict of the seed is not the one of the run.

    def seed_that_did_not_converge(model, *, verbose):
        model.initial_state_converged = False
        return np.zeros((1, 2))

    parent = StubMF6(model_folder=tmp_path, model_name="Run")
    parent.inputs = cyclic_model(first_cycle_from="steady_state", max_cycles=1)
    monkeypatch.setattr(
        ssic, "run_modflow6_steady_state_initialization", seed_that_did_not_converge
    )
    monkeypatch.setattr(ssic, "_run_one_spinup_cycle", lambda *_a, **_k: np.zeros((1, 2)))

    ssic.run_modflow6_cyclic_spinup(parent, verbose=False)

    assert parent.initial_state_converged is None


def test_mean_forcing_grid() -> None:
    source_window = ResolvedSimulationTimeWindow(
        start=pd.Timestamp("2003-01-01"),
        end=pd.Timestamp("2003-02-28"),
        step_value=1,
        step_unit="month",
        coverage_policy="error",
    )
    source_grid = type(
        "SourceGrid",
        (),
        {
            "window": source_window,
            "period_lengths_seconds": (31 * 86400.0, 28 * 86400.0),
        },
    )()

    steady_grid = single_period_mean_forcing_time_grid(source_grid)

    assert steady_grid.period_lengths_seconds.tolist() == [59 * 86400.0]
    assert steady_grid.window.start == pd.Timestamp("2003-01-01")
    assert steady_grid.window.end == pd.Timestamp("2003-02-28")
    assert steady_grid.window.coverage_policy == "error"
    assert build_simulation_time_boundaries(steady_grid.window) == [
        pd.Timestamp("2003-01-01"),
        pd.Timestamp("2003-03-01"),
    ]
    assert stress_period_bounds(1, steady_grid.window) == [
        (pd.Timestamp("2003-01-01"), pd.Timestamp("2003-03-01"))
    ]

    recharge = pd.Series(
        [1.0, 2.0],
        index=pd.DatetimeIndex([pd.Timestamp("2003-01-01"), pd.Timestamp("2003-02-28")]),
    )
    validate_recharge_coverage(recharge, steady_grid.window)


def cyclic_conditions(**ic) -> FlowInitialConditions:
    payload = {"kind": "spinup_cyclic", **ic}
    return FlowInitialConditions.model_validate({"h": payload})


def test_tolerance_unit() -> None:
    assert initial_state_of(
        cyclic_conditions(tol_head="2 cm")
    ).strategy.tol_head_m == pytest.approx(0.02)


UNSETTLED = [
    # Dry in one cycle and wet in the other is the state moving, not a missing value.
    pytest.param(np.array([1.0, np.nan, 3.0]), np.array([1.0, 2.0, 3.0]), 10.0, id="cell wetted"),
    pytest.param(np.full(4, np.nan), np.full(4, np.nan), 1.0, id="all cells inactive"),
]


@pytest.mark.parametrize(("before", "after", "tol_head_m"), UNSETTLED)
def test_cycles_not_settled(before, after, tol_head_m) -> None:
    assert cycles_have_settled(before, after, tol_head_m=tol_head_m) is False


def test_cycles_on_two_meshes() -> None:
    with pytest.raises(ValueError, match="same mesh"):
        cycles_have_settled(np.zeros(3), np.zeros(4), tol_head_m=1.0)


def cyclic_model(**strategy):
    return make_model(initial=initial_state_of(cyclic_conditions(**strategy)))


def parent_with(tmp_path, initial) -> StubMF6:
    parent = StubMF6(model_folder=tmp_path, model_name="parent")
    parent.inputs = make_model(
        initial=initial, time=ModelTime(grid=None, regime="transient", first_period_steady=True)
    )
    return parent


def test_steady_solve_variant(stub_solve, monkeypatch, tmp_path) -> None:
    built: list[object] = []
    monkeypatch.setattr(StubMF6, "built", built)
    parent = parent_with(tmp_path, SteadyStart())

    with pytest.warns(RuntimeWarning):
        ssic.run_modflow6_steady_state_initialization(parent, verbose=False)

    (variant,) = built
    assert variant.time.regime == "steady"
    assert variant.initial == HeadRule("top")
    assert parent.inputs.time.regime == "transient"
    assert parent.inputs.initial == SteadyStart()


def test_later_cycle_variant(stub_solve, monkeypatch, tmp_path) -> None:
    built: list[object] = []
    monkeypatch.setattr(StubMF6, "built", built)
    parent = parent_with(tmp_path, CyclicStart())

    ssic._run_one_spinup_cycle(parent, cycle=1, seed=np.array([[1.0, 2.0]]), verbose=False)

    (variant,) = built
    assert isinstance(variant.initial, SolvedState)
    assert variant.initial.head.tolist() == [[1.0, 2.0]]
    assert variant.time.regime == "transient"


class SlotStub(StubMF6):
    """Records how each auxiliary model is made and which slot its build reads."""

    made: list[dict] = []

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        type(self).made.append({"init": kwargs})

    def pre_processing(self, inputs, **kwargs) -> None:
        super().pre_processing(inputs)
        type(self).made[-1]["slot"] = kwargs.get("slot")


def solve_auxiliary(kind: str, parent: SlotStub) -> None:
    if kind == "steady":
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            ssic.run_modflow6_steady_state_initialization(parent, verbose=False)
    else:
        ssic._run_one_spinup_cycle(parent, cycle=3, seed=None, verbose=False)


AUXILIARY_SLOTS = [
    pytest.param("steady", ssic.STEADY_FOLDER, "ssic", id="steady"),
    pytest.param("cycle", f"{ssic.CYCLE_FOLDER_PREFIX}3", "cyc3", id="cycle"),
]


@pytest.mark.parametrize(("kind", "folder", "name"), AUXILIARY_SLOTS)
def test_auxiliary_slot(
    stub_solve, monkeypatch, tmp_path, kind: str, folder: str, name: str
) -> None:
    # Same binaries and same shared forcing folder as the run, in a folder of its own.
    monkeypatch.setattr(SlotStub, "made", [])
    parent = SlotStub(model_folder=tmp_path, model_name="run")
    parent.slot = RunSlot(
        tmp_path, "run", bin_dir=tmp_path / "bin", shared_forcing_dir=tmp_path / "_shared"
    )
    parent.inputs = make_model(
        initial=CyclicStart(),
        time=ModelTime(grid=None, regime="transient", first_period_steady=True),
    )

    solve_auxiliary(kind, parent)

    made = SlotStub.made[-1]
    slot = made["slot"]
    assert slot.folder == tmp_path / "run" / folder and slot.name == name
    assert (slot.bin_dir, slot.shared_forcing_dir) == (tmp_path / "bin", tmp_path / "_shared")
    assert made["init"]["bin_path"] == tmp_path / "bin"
    assert Path(made["init"]["model_folder"]) / made["init"]["model_name"] == slot.directory


@pytest.mark.parametrize(
    ("name", "auxiliary"),
    [("_ssic", True), ("_cyc0", True), ("_cyc12", True), ("_cycle", False), ("_recharge", False)],
)
def test_auxiliary_folder(name: str, auxiliary: bool) -> None:
    assert ssic.is_auxiliary_folder(name) is auxiliary


HEAD_BOUNDS = [
    pytest.param(
        [2.0, 3.0, 4.0],
        [5.0, 5.0, 5.0],
        [1.0, 2.0, 3.0],
        {
            "cell_count": 3,
            "finite_cell_count": 3,
            "nonfinite_cell_count": 0,
            "below_bottom_count": 0,
            "above_top_count": 0,
            "max_below_bottom_m": 0.0,
            "max_above_top_m": 0.0,
            "head_min_m": 2.0,
            "head_max_m": 4.0,
            "within_bounds": True,
        },
        id="valid field",
    ),
    pytest.param(
        [0.0, 6.0, 3.0, np.nan],
        [5.0, 5.0, 5.0, 5.0],
        [1.0, 1.0, 4.0, 1.0],
        {
            "cell_count": 4,
            "finite_cell_count": 3,
            "nonfinite_cell_count": 1,
            "below_bottom_count": 2,
            "above_top_count": 1,
            "max_below_bottom_m": 1.0,
            "max_above_top_m": 1.0,
            "head_min_m": 0.0,
            "head_max_m": 6.0,
            "within_bounds": False,
        },
        id="heads outside the cell",
    ),
]


@pytest.mark.parametrize(("head", "top", "bottom", "expected"), HEAD_BOUNDS)
def test_head_bounds(head, top, bottom, expected) -> None:
    summary = summarize_head_initial_condition_bounds(
        head=np.asarray(head), top=np.asarray(top), bottom=np.asarray(bottom)
    )
    for key, value in expected.items():
        if isinstance(value, bool):
            assert summary[key] is value
        else:
            assert summary[key] == pytest.approx(value)


def test_head_bounds_shapes() -> None:
    with pytest.raises(ValueError, match="bounds cannot broadcast"):
        summarize_head_initial_condition_bounds(
            head=np.zeros((2, 3)),
            top=np.zeros((4,)),
            bottom=np.zeros((2, 3)),
        )


def write_stage_file(path: Path, records: list[list[float]]) -> None:
    header = np.dtype(
        [
            ("kstp", "i4"),
            ("kper", "i4"),
            ("pertim", "f8"),
            ("totim", "f8"),
            ("text", "S16"),
            ("ncol", "i4"),
            ("nrow", "i4"),
            ("ilay", "i4"),
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        for step, values in enumerate(records, start=1):
            np.array([(1, step, step, step, b"STAGE", len(values), 1, 1)], dtype=header).tofile(
                handle
            )
            np.array(values, dtype="f8").tofile(handle)


def lake_model(tmp_path: Path, *, lakes: tuple[str, ...] = ("lac0", "lac1")) -> StubMF6:
    parent = StubMF6(model_folder=tmp_path, model_name="parent")
    parent.inputs = make_model(
        initial=CyclicStart(CyclicSpinupStrategy(max_cycles=5, tol_head_m=0.01)),
        boundaries=BoundaryConditionBundle(conditions={}, active_ids=("lake",)),
        lakes={lake: {"initial_stage": 60.0} for lake in lakes},
        time=ModelTime(grid=None, regime="transient", first_period_steady=True),
    )
    return parent


def test_cycle_stages(tmp_path: Path) -> None:
    parent = lake_model(tmp_path)
    folder = Path(parent.full_path) / f"{ssic.CYCLE_FOLDER_PREFIX}2" / "cyc2"
    write_stage_file(folder / "cyc2.lak.stage", [[60.0, 61.0], [59.5, 62.123456789012345]])

    assert ssic.cycle_lake_stages(parent, 2) == {"lac0": 59.5, "lac1": 62.123456789012345}


def test_cycle_without_stage_file(tmp_path: Path) -> None:
    parent = lake_model(tmp_path)

    with pytest.raises(FileNotFoundError, match="Spin-up cycle 0 should leave one lake stage file"):
        ssic.cycle_lake_stages(parent, 0)


def test_later_cycle_lake_stages(stub_solve, monkeypatch, tmp_path) -> None:
    built: list[object] = []
    monkeypatch.setattr(StubMF6, "built", built)
    parent = lake_model(tmp_path)

    ssic._run_one_spinup_cycle(
        parent,
        cycle=1,
        seed=np.array([[1.0, 2.0]]),
        seed_lake_stages={"lac0": 59.5},
        verbose=False,
    )

    (variant,) = built
    assert dict(variant.initial.lake_stages) == {"lac0": 59.5}


def run_loop(monkeypatch, tmp_path: Path, stages_by_cycle: list[dict[str, float]]):
    """Run the loop with cycles that always end on the same head, and the given lake stages."""
    seeds: list[dict[str, float]] = []

    def cycle(model, *, cycle, seed, seed_lake_stages, verbose):
        seeds.append(dict(seed_lake_stages))
        return np.array([[1.0, 2.0]])

    monkeypatch.setattr(ssic, "_run_one_spinup_cycle", cycle)
    monkeypatch.setattr(ssic, "cycle_lake_stages", lambda _model, n: stages_by_cycle[n])
    parent = lake_model(tmp_path)
    return ssic.run_modflow6_cyclic_spinup(parent, verbose=False), seeds


LAKE_LOOPS = [
    pytest.param(
        [{"lac0": 60.0}, {"lac0": 60.004}, {"lac0": 60.0}], 2, True, id="lake stopped moving"
    ),
    pytest.param(
        [{"lac0": 60.0}, {"lac0": 60.5}, {"lac0": 60.9}, {"lac0": 60.905}],
        4,
        True,
        id="lake drifts then settles",
    ),
    pytest.param(
        [{"lac0": 60.0 + n} for n in range(5)], 5, False, id="lake never settles, loop runs out"
    ),
    pytest.param([{}, {}, {}], 2, True, id="no lake, heads alone settle"),
]


@pytest.mark.parametrize(("stages", "cycles", "settled"), LAKE_LOOPS)
def test_spinup_settles(
    stages: list, cycles: int, settled: bool, monkeypatch, tmp_path: Path
) -> None:
    (_, ran, did_settle), _ = run_loop(monkeypatch, tmp_path, stages)

    assert (ran, did_settle) == (cycles, settled)


def test_cycle_seeds_next_lakes(monkeypatch, tmp_path: Path) -> None:
    stages = [{"lac0": 60.0}, {"lac0": 60.5}, {"lac0": 60.9}, {"lac0": 60.905}]

    _, seeds = run_loop(monkeypatch, tmp_path, stages)

    assert seeds == [{}, {"lac0": 60.0}, {"lac0": 60.5}, {"lac0": 60.9}]


class Packagedata:
    """Stands for the packagedata of a LAK package: a record array it hands back and takes."""

    def __init__(self) -> None:
        self.data = np.rec.fromrecords(
            [(0, 60.0, 1, "lac0"), (1, 61.0, 1, "lac1")],
            dtype=[("ifno", "<i8"), ("strt", "<f8"), ("nlakeconn", "<i8"), ("boundname", "O")],
        )

    def get_data(self):
        return self.data

    def set_data(self, data) -> None:
        self.data = data


def test_main_model_lake_stages(tmp_path: Path) -> None:
    parent = lake_model(tmp_path)
    parent.lak = SimpleNamespace(packagedata=Packagedata())
    folder = Path(parent.full_path) / f"{ssic.CYCLE_FOLDER_PREFIX}1" / "cyc1"
    write_stage_file(folder / "cyc1.lak.stage", [[59.0, 62.0], [59.5, 62.123456789012345]])

    ssic.apply_modflow6_cyclic_spinup_lakes(parent, 2)

    rows = list(parent.lak.packagedata.data)
    assert [(row["boundname"], row["strt"]) for row in rows] == [
        ("lac0", "59.5"),
        ("lac1", repr(62.123456789012345)),
    ]


def test_model_without_lak_package(tmp_path: Path) -> None:
    parent = StubMF6(model_folder=tmp_path, model_name="parent")

    ssic.apply_modflow6_cyclic_spinup_lakes(parent, 3)


def test_model_without_lakes_keeps_stages(tmp_path: Path) -> None:
    parent = StubMF6(model_folder=tmp_path, model_name="parent")
    parent.lak = SimpleNamespace(packagedata=Packagedata())

    ssic.apply_modflow6_cyclic_spinup_lakes(parent, 3)

    assert [row["strt"] for row in parent.lak.packagedata.data] == [60.0, 61.0]


def stop_flag(tmp_path: Path, *, written: bool) -> Path:
    flag = tmp_path / ".hmp" / "stop.json"
    if written:
        flag.parent.mkdir(exist_ok=True)
        flag.write_text('{"schema": "hydromodpy.stop.v1", "at": "2026-11-10T10:00:00+00:00"}')
    return flag


def test_stop_between_cycles(monkeypatch, tmp_path: Path) -> None:
    flag = stop_flag(tmp_path, written=False)
    ran: list[int] = []

    def cycle(model, *, cycle, **_kwargs):
        ran.append(cycle)
        stop_flag(tmp_path, written=True)
        return np.array([[float(cycle), 2.0]])

    monkeypatch.setattr(ssic, "_run_one_spinup_cycle", cycle)
    parent = lake_model(tmp_path, lakes=())
    parent.slot = SimpleNamespace(stop_flag=flag)

    with pytest.raises(StopRequested, match="stop requested at 2026-11-10T10:00:00"):
        ssic.run_modflow6_cyclic_spinup(parent, verbose=False)

    assert ran == [0]
