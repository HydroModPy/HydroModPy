from __future__ import annotations

import warnings
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.runtime.interrupts import StopRequested
from hydromodpy.core.time import (
    ResolvedSimulationTimeWindow,
    build_simulation_time_boundaries,
    validate_recharge_coverage,
)
from hydromodpy.core.time.steady_initialization import (
    single_period_mean_forcing_time_grid,
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
from hydromodpy.model.model import ModelTime, cycle_variant, steady_variant
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
from hydromodpy.solver.modflow_common import ModflowPreprocessOptions
from tests._helpers.model_factory import make_model


def test_modflow6_steady_initialization_relaxes_auxiliary_solver_only() -> None:
    config = Modflow6Config(
        runtime=Modflow6RuntimeConfig(
            mf6_executable_name="mf6",
            mf6_outer_dvclose=1e-4,
            mf6_inner_dvclose=1e-4,
            mf6_outer_maximum=500,
            mf6_inner_maximum=500,
        )
    )
    model = SimpleNamespace(modflow_config=config, exe="/opt/mf6")

    steady_config = _modflow_config_for_steady_initialization(model)

    assert steady_config.runtime.mf6_executable_name == "/opt/mf6"
    assert steady_config.runtime.mf6_outer_dvclose == 1e-3
    assert steady_config.runtime.mf6_inner_dvclose == 1e-3
    assert steady_config.runtime.mf6_outer_maximum == 1000
    assert steady_config.runtime.mf6_inner_maximum == 1000
    assert steady_config.runtime.mf6_newton is True
    assert steady_config.runtime.mf6_newton_under_relaxation is True
    assert config.runtime.mf6_outer_dvclose == 1e-4
    assert config.runtime.mf6_inner_dvclose == 1e-4


def test_modflow6_steady_initialization_disables_rewet_when_forcing_newton() -> None:
    # A user-valid newton=False + rewet=True + CG transient config must not trip
    # the NEWTON+REWET or NEWTON+CG guard during the steady spin-up (forces Newton).
    config = Modflow6Config(
        runtime=Modflow6RuntimeConfig(
            mf6_newton=False, mf6_enable_rewet=True, mf6_linear_acceleration="CG"
        )
    )
    model = SimpleNamespace(modflow_config=config, exe="mf6")

    steady_config = _modflow_config_for_steady_initialization(model)

    assert steady_config.runtime.mf6_newton is True
    assert steady_config.runtime.mf6_enable_rewet is False
    assert steady_config.runtime.mf6_linear_acceleration == "BICGSTAB"
    # The user's transient config is untouched.
    assert config.runtime.mf6_newton is False
    assert config.runtime.mf6_enable_rewet is True
    assert config.runtime.mf6_linear_acceleration == "CG"


def test_modflow6_steady_initialization_preserves_looser_user_settings() -> None:
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


def test_modflow6_steady_initialization_accepts_closed_nonconverged_budget(
    tmp_path,
) -> None:
    list_path = tmp_path / "ssic.lst"
    list_path.write_text(
        """
 PERCENT DISCREPANCY =        -200.00     PERCENT DISCREPANCY =        -200.00
 PERCENT DISCREPANCY =          -0.00     PERCENT DISCREPANCY =          -0.00
""",
        encoding="utf-8",
    )

    assert _read_final_percent_discrepancy(list_path) == -0.0
    assert _steady_initialization_balance_is_acceptable(list_path) is True


def test_modflow6_steady_initialization_rejects_open_budget(tmp_path) -> None:
    list_path = tmp_path / "ssic.lst"
    list_path.write_text(
        "PERCENT DISCREPANCY = -12.5     PERCENT DISCREPANCY = -12.5\n",
        encoding="utf-8",
    )

    assert _read_final_percent_discrepancy(list_path) == -12.5
    assert _steady_initialization_balance_is_acceptable(list_path) is False


# The steady initial-condition solve reads the listing MF6 wrote, whatever the run name.
#
# MF6 names the listing after the safe model name, which is lowercase. The head file
# keeps the output stem. A reader that built the listing name from the output stem
# looked for a file that did not exist as soon as the two differed.

CLOSED_LISTING = " PERCENT DISCREPANCY =  0.00     PERCENT DISCREPANCY =  0.00\n"


def test_the_listing_is_named_after_the_safe_model_name(tmp_path: Path) -> None:
    model = SimpleNamespace(
        model_name="Nancon Lake_A",
        model_name_mf6=mf6_safe_name("Nancon Lake_A"),
        model_output_name="Nancon Lake_A",
        full_path=str(tmp_path),
    )
    (tmp_path / "nancon_lake_a.lst").write_text(CLOSED_LISTING)

    assert ssic._model_listing_path(model).is_file()


def test_a_name_with_a_capital_letter_reaches_the_safe_name_without_the_attribute(
    tmp_path: Path,
) -> None:
    model = SimpleNamespace(model_name="Run One", full_path=str(tmp_path))

    assert ssic._model_listing_path(model) == tmp_path / "run_one.lst"


class _StubMF6:
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


def test_a_run_named_with_capitals_still_finds_the_listing(monkeypatch, tmp_path) -> None:
    """The listing the solve wrote is the one the acceptance reads, so no RuntimeError."""
    monkeypatch.setattr(ssic, "_read_final_head", lambda *_a, **_k: np.zeros((1, 2)))
    monkeypatch.setattr(ssic, "_modflow_config_for_steady_initialization", lambda _m: None)
    parent = _StubMF6(model_folder=tmp_path, model_name="Run With Capitals")

    with pytest.warns(RuntimeWarning, match="final water budget is closed"):
        head = ssic.run_modflow6_steady_state_initialization(parent, verbose=False)

    assert head.shape == (1, 2)


@pytest.mark.parametrize("converges", [True, False], ids=["converged", "closed budget only"])
def test_the_steady_solve_tells_the_run_whether_it_converged(
    monkeypatch, tmp_path, converges
) -> None:
    """The flag the runner reads before a transport run: the solve's own verdict."""
    monkeypatch.setattr(ssic, "_read_final_head", lambda *_a, **_k: np.zeros((1, 2)))
    monkeypatch.setattr(ssic, "_modflow_config_for_steady_initialization", lambda _m: None)
    monkeypatch.setattr(_StubMF6, "converges", converges)
    parent = _StubMF6(model_folder=tmp_path, model_name="Run")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        ssic.run_modflow6_steady_state_initialization(parent, verbose=False)

    assert parent.initial_state_converged is converges


def test_a_steady_seed_of_a_cyclic_spinup_is_not_the_start_of_the_run(
    monkeypatch, tmp_path
) -> None:
    """The cycles settle the state, so the seed's verdict is not the run's."""

    def seed_that_did_not_converge(model, *, verbose):
        model.initial_state_converged = False
        return np.zeros((1, 2))

    parent = _StubMF6(model_folder=tmp_path, model_name="Run")
    parent.inputs = _cyclic_model(first_cycle_from="steady_state", max_cycles=1)
    monkeypatch.setattr(
        ssic, "run_modflow6_steady_state_initialization", seed_that_did_not_converge
    )
    monkeypatch.setattr(ssic, "_run_one_spinup_cycle", lambda *_a, **_k: np.zeros((1, 2)))

    ssic.run_modflow6_cyclic_spinup(parent, verbose=False)

    assert parent.initial_state_converged is None


def test_single_period_mean_forcing_time_grid_spans_full_source_window() -> None:
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


# Repeating the run's own period until the state stops moving.
#
# A steady solve carries the forcing's mean and none of its history, which is the
# wrong antecedent for an aquifer whose response time is long against the record. The
# cycles are auxiliary solves inside one run, exactly as the steady initialization
# already is, which is what lets a calibration trial use them: nothing touches the
# run's store.
#
# What is gated here is the loop's bookkeeping and its two honesty rules, with no
# solver: how many cycles run, that the largest change decides and not the mean, and
# that a loop out of cycles hands back its last state while saying it did not settle.


def _ic(**ic) -> FlowInitialConditions:
    payload = {"kind": "spinup_cyclic", **ic}
    return FlowInitialConditions.model_validate({"h": payload})


class TestTheDeclaration:
    def test_the_type_is_recognised(self) -> None:
        assert isinstance(initial_state_of(_ic()), CyclicStart)

    def test_another_initial_condition_is_not(self) -> None:
        other = FlowInitialConditions.model_validate({"h": {"kind": "top"}})
        assert not isinstance(initial_state_of(other), CyclicStart)

    def test_the_tolerance_carries_its_unit(self) -> None:
        assert initial_state_of(_ic(tol_head="2 cm")).strategy.tol_head_m == pytest.approx(0.02)

    def test_the_defaults_are_a_real_strategy(self) -> None:
        strategy = initial_state_of(_ic()).strategy
        assert strategy.max_cycles >= 1
        assert strategy.tol_head_m > 0.0
        assert strategy.first_cycle_from == "top"

    def test_a_first_cycle_source_it_does_not_know_is_refused(self) -> None:
        with pytest.raises(ValueError):
            FlowInitialConditions.model_validate(
                {"h": {"kind": "spinup_cyclic", "first_cycle_from": "yesterday"}}
            )


class TestWhatCountsAsSettled:
    def test_the_largest_change_decides_not_the_mean(self) -> None:
        # A basin settled on average while one compartment still drifts has not
        # settled, and averaging is how that gets missed.
        before = np.zeros(100)
        after = np.zeros(100)
        after[42] = 5.0
        assert cycles_have_settled(before, after, tol_head_m=0.01) is False

    def test_a_change_under_the_tolerance_everywhere_is_settled(self) -> None:
        before = np.linspace(10.0, 20.0, 50)
        assert cycles_have_settled(before, before + 0.005, tol_head_m=0.01) is True

    def test_the_first_cycle_has_nothing_to_compare_to(self) -> None:
        assert cycles_have_settled(None, np.zeros(5), tol_head_m=1.0) is False

    def test_a_cell_that_wetted_between_cycles_is_a_change(self) -> None:
        # Dry in one and wet in the other is the state moving, not a missing value.
        before = np.array([1.0, np.nan, 3.0])
        after = np.array([1.0, 2.0, 3.0])
        assert cycles_have_settled(before, after, tol_head_m=10.0) is False

    def test_two_meshes_of_different_size_are_refused(self) -> None:
        with pytest.raises(ValueError, match="same mesh"):
            cycles_have_settled(np.zeros(3), np.zeros(4), tol_head_m=1.0)

    def test_a_field_that_is_entirely_inactive_never_counts_as_settled(self) -> None:
        nans = np.full(4, np.nan)
        assert cycles_have_settled(nans, nans, tol_head_m=1.0) is False


def _cyclic_model(**strategy):
    return make_model(initial=initial_state_of(_ic(**strategy)))


class TestTheCycleDoesNotSpawnItsOwn:
    """The defect that a real run found, and the only gate that catches it early."""

    def test_a_cycle_s_model_no_longer_asks_for_cycling(self) -> None:
        # Measured before this was fixed: each auxiliary model re-entered the same
        # hook, so a three-cycle spin-up ran 143 solves and was stopped by the
        # machine rather than by the loop.
        cycle = cycle_variant(_cyclic_model(max_cycles=3), None)
        assert not isinstance(cycle.initial, CyclicStart)

    def test_the_cycle_starts_from_the_top_surface(self) -> None:
        # The caller overwrites it with the previous cycle's heads; what matters is
        # that the variant carries a state the hook does not fire on.
        assert cycle_variant(_cyclic_model(), None).initial == HeadRule("top")

    def test_a_later_cycle_starts_from_the_heads_of_the_one_before(self) -> None:
        seed = SolvedState(head=np.ones((1, 2)), solver="modflow6")
        assert cycle_variant(_cyclic_model(), seed).initial is seed

    def test_the_original_model_is_left_alone(self) -> None:
        model = _cyclic_model(max_cycles=2)
        cycle_variant(model, None)
        assert model.initial == CyclicStart(CyclicSpinupStrategy(max_cycles=2, tol_head_m=0.01))


class TestTheAuxiliaryModelsAreBuiltFromVariants:
    """The run's own model is the one source, and the stub solver sees only the variant."""

    def _parent(self, tmp_path, initial):
        parent = _StubMF6(model_folder=tmp_path, model_name="parent")
        parent.inputs = make_model(
            initial=initial,
            time=ModelTime(grid=None, regime="transient", first_period_steady=True),
        )
        return parent

    def test_the_steady_solve_runs_on_a_steady_model_that_starts_from_the_top(
        self, monkeypatch, tmp_path
    ) -> None:
        monkeypatch.setattr(ssic, "_read_final_head", lambda *_a, **_k: np.zeros((1, 2)))
        monkeypatch.setattr(ssic, "_modflow_config_for_steady_initialization", lambda _m: None)
        built: list[object] = []
        monkeypatch.setattr(_StubMF6, "built", built)
        parent = self._parent(tmp_path, SteadyStart())

        with pytest.warns(RuntimeWarning):
            ssic.run_modflow6_steady_state_initialization(parent, verbose=False)

        (variant,) = built
        assert variant.time.regime == "steady"
        assert variant.initial == HeadRule("top")
        assert parent.inputs.time.regime == "transient"
        assert parent.inputs.initial == SteadyStart()

    def test_a_cycle_that_follows_another_starts_from_a_solved_state(
        self, monkeypatch, tmp_path
    ) -> None:
        monkeypatch.setattr(ssic, "_read_final_head", lambda *_a, **_k: np.zeros((1, 2)))
        monkeypatch.setattr(ssic, "_modflow_config_for_steady_initialization", lambda _m: None)
        built: list[object] = []
        monkeypatch.setattr(_StubMF6, "built", built)
        parent = self._parent(tmp_path, CyclicStart())

        ssic._run_one_spinup_cycle(parent, cycle=1, seed=np.array([[1.0, 2.0]]), verbose=False)

        (variant,) = built
        assert isinstance(variant.initial, SolvedState)
        assert variant.initial.head.tolist() == [[1.0, 2.0]]
        assert variant.time.regime == "transient"


class _SlotStub(_StubMF6):
    """Records how each auxiliary model is made and which slot its build reads."""

    made: list[dict] = []

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        type(self).made.append({"init": kwargs})

    def pre_processing(self, inputs, **kwargs) -> None:
        super().pre_processing(inputs)
        type(self).made[-1]["slot"] = kwargs.get("slot")


def _solve_auxiliary(kind: str, parent: _SlotStub) -> None:
    if kind == "steady":
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            ssic.run_modflow6_steady_state_initialization(parent, verbose=False)
    else:
        ssic._run_one_spinup_cycle(parent, cycle=3, seed=None, verbose=False)


AUXILIARY_SLOT_CASES = (
    ("steady", ssic.STEADY_FOLDER, "ssic"),
    ("cycle", f"{ssic.CYCLE_FOLDER_PREFIX}3", "cyc3"),
)


@pytest.mark.parametrize(
    ("kind", "folder", "name"), AUXILIARY_SLOT_CASES, ids=[c[0] for c in AUXILIARY_SLOT_CASES]
)
def test_an_auxiliary_model_solves_in_a_slot_derived_from_the_run(
    monkeypatch, tmp_path, kind: str, folder: str, name: str
) -> None:
    """Same binaries and same shared forcing folder as the run, in a folder of its own."""
    from hydromodpy.solver.base.plan import RunSlot

    monkeypatch.setattr(ssic, "_read_final_head", lambda *_a, **_k: np.zeros((1, 2)))
    monkeypatch.setattr(ssic, "_modflow_config_for_steady_initialization", lambda _m: None)
    monkeypatch.setattr(_SlotStub, "made", [])
    parent = _SlotStub(model_folder=tmp_path, model_name="run")
    parent.slot = RunSlot(
        tmp_path, "run", bin_dir=tmp_path / "bin", shared_forcing_dir=tmp_path / "_shared"
    )
    parent.inputs = make_model(
        initial=CyclicStart(),
        time=ModelTime(grid=None, regime="transient", first_period_steady=True),
    )

    _solve_auxiliary(kind, parent)

    made = _SlotStub.made[-1]
    slot = made["slot"]
    assert slot.folder == tmp_path / "run" / folder and slot.name == name
    assert (slot.bin_dir, slot.shared_forcing_dir) == (tmp_path / "bin", tmp_path / "_shared")
    assert made["init"]["bin_path"] == tmp_path / "bin"
    assert Path(made["init"]["model_folder"]) / made["init"]["model_name"] == slot.directory


def test_an_auxiliary_model_of_a_run_without_a_slot_keeps_its_files_beside_it(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(ssic, "_read_final_head", lambda *_a, **_k: np.zeros((1, 2)))
    monkeypatch.setattr(ssic, "_modflow_config_for_steady_initialization", lambda _m: None)
    monkeypatch.setattr(_SlotStub, "made", [])
    parent = _SlotStub(model_folder=tmp_path, model_name="run")

    _solve_auxiliary("steady", parent)

    slot = _SlotStub.made[-1]["slot"]
    assert (slot.bin_dir, slot.shared_forcing_dir) == (None, None)


@pytest.mark.parametrize(
    ("name", "auxiliary"),
    [("_ssic", True), ("_cyc0", True), ("_cyc12", True), ("_cycle", False), ("_recharge", False)],
)
def test_the_auxiliary_folders_are_told_by_name(name: str, auxiliary: bool) -> None:
    assert ssic.is_auxiliary_folder(name) is auxiliary


def test_summarize_head_initial_condition_bounds_reports_valid_field() -> None:
    summary = summarize_head_initial_condition_bounds(
        head=np.asarray([2.0, 3.0, 4.0]),
        top=np.asarray([5.0, 5.0, 5.0]),
        bottom=np.asarray([1.0, 2.0, 3.0]),
    )

    assert summary["cell_count"] == 3
    assert summary["finite_cell_count"] == 3
    assert summary["nonfinite_cell_count"] == 0
    assert summary["below_bottom_count"] == 0
    assert summary["above_top_count"] == 0
    assert summary["max_below_bottom_m"] == pytest.approx(0.0)
    assert summary["max_above_top_m"] == pytest.approx(0.0)
    assert summary["head_min_m"] == pytest.approx(2.0)
    assert summary["head_max_m"] == pytest.approx(4.0)
    assert summary["within_bounds"] is True


def test_summarize_head_initial_condition_bounds_reports_violations() -> None:
    summary = summarize_head_initial_condition_bounds(
        head=np.asarray([0.0, 6.0, 3.0, np.nan]),
        top=np.asarray([5.0, 5.0, 5.0, 5.0]),
        bottom=np.asarray([1.0, 1.0, 4.0, 1.0]),
    )

    assert summary["cell_count"] == 4
    assert summary["finite_cell_count"] == 3
    assert summary["nonfinite_cell_count"] == 1
    assert summary["below_bottom_count"] == 2
    assert summary["above_top_count"] == 1
    assert summary["max_below_bottom_m"] == pytest.approx(1.0)
    assert summary["max_above_top_m"] == pytest.approx(1.0)
    assert summary["head_min_m"] == pytest.approx(0.0)
    assert summary["head_max_m"] == pytest.approx(6.0)
    assert summary["within_bounds"] is False


def test_summarize_head_initial_condition_bounds_rejects_shape_mismatch() -> None:
    with pytest.raises(ValueError, match="bounds cannot broadcast"):
        summarize_head_initial_condition_bounds(
            head=np.zeros((2, 3)),
            top=np.zeros((4,)),
            bottom=np.zeros((2, 3)),
        )


# The lakes cycle with the heads, and the flag of the run stops the cycles.
#
# A spin-up that restarted each cycle from the ``initial_stage`` of its lakes kept
# the heads settling under a lake that never moved. A lake starts each cycle at the
# stage the cycle before ended on, and the loop settles only when the stages did.


def _write_stage_file(path: Path, records: list[list[float]]) -> None:
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


def _lake_model(tmp_path: Path, *, lakes: tuple[str, ...] = ("lac0", "lac1")) -> _StubMF6:
    parent = _StubMF6(model_folder=tmp_path, model_name="parent")
    parent.inputs = make_model(
        initial=CyclicStart(CyclicSpinupStrategy(max_cycles=5, tol_head_m=0.01)),
        boundaries=BoundaryConditionBundle(conditions={}, active_ids=("lake",)),
        lakes={lake: {"initial_stage": 60.0} for lake in lakes},
        time=ModelTime(grid=None, regime="transient", first_period_steady=True),
    )
    return parent


def test_the_stages_of_a_cycle_are_the_last_record_of_its_stage_file(tmp_path: Path) -> None:
    parent = _lake_model(tmp_path)
    folder = Path(parent.full_path) / f"{ssic.CYCLE_FOLDER_PREFIX}2" / "cyc2"
    _write_stage_file(folder / "cyc2.lak.stage", [[60.0, 61.0], [59.5, 62.123456789012345]])

    assert ssic.cycle_lake_stages(parent, 2) == {"lac0": 59.5, "lac1": 62.123456789012345}


def test_a_model_without_a_lake_has_no_cycle_stages(tmp_path: Path) -> None:
    parent = _StubMF6(model_folder=tmp_path, model_name="parent")

    assert ssic.cycle_lake_stages(parent, 0) == {}


def test_a_cycle_without_its_stage_file_is_a_failure_to_name(tmp_path: Path) -> None:
    parent = _lake_model(tmp_path)

    with pytest.raises(FileNotFoundError, match="Spin-up cycle 0 should leave one lake stage file"):
        ssic.cycle_lake_stages(parent, 0)


def test_a_cycle_that_follows_another_starts_its_lakes_from_the_stages_of_the_one_before(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(ssic, "_read_final_head", lambda *_a, **_k: np.zeros((1, 2)))
    monkeypatch.setattr(ssic, "_modflow_config_for_steady_initialization", lambda _m: None)
    built: list[object] = []
    monkeypatch.setattr(_StubMF6, "built", built)
    parent = _lake_model(tmp_path)

    ssic._run_one_spinup_cycle(
        parent,
        cycle=1,
        seed=np.array([[1.0, 2.0]]),
        seed_lake_stages={"lac0": 59.5},
        verbose=False,
    )

    (variant,) = built
    assert dict(variant.initial.lake_stages) == {"lac0": 59.5}


def _loop(monkeypatch, tmp_path: Path, stages_by_cycle: list[dict[str, float]]):
    """Run the loop with cycles that always end on the same head, and the given lake stages."""
    seeds: list[dict[str, float]] = []

    def cycle(model, *, cycle, seed, seed_lake_stages, verbose):
        seeds.append(dict(seed_lake_stages))
        return np.array([[1.0, 2.0]])

    monkeypatch.setattr(ssic, "_run_one_spinup_cycle", cycle)
    monkeypatch.setattr(ssic, "cycle_lake_stages", lambda _model, n: stages_by_cycle[n])
    parent = _lake_model(tmp_path)
    return ssic.run_modflow6_cyclic_spinup(parent, verbose=False), seeds


LAKE_LOOPS = (
    ("a lake that has stopped moving", [{"lac0": 60.0}, {"lac0": 60.004}, {"lac0": 60.0}], 2, True),
    (
        "a lake that still drifts keeps the loop going",
        [{"lac0": 60.0}, {"lac0": 60.5}, {"lac0": 60.9}, {"lac0": 60.905}],
        4,
        True,
    ),
    (
        "a lake that never settles runs the loop out",
        [{"lac0": 60.0 + n} for n in range(5)],
        5,
        False,
    ),
    ("no lake at all, the heads alone settle", [{}, {}, {}], 2, True),
)


@pytest.mark.parametrize(
    ("case", "stages", "cycles", "settled"), LAKE_LOOPS, ids=[c[0] for c in LAKE_LOOPS]
)
def test_the_spinup_settles_only_when_the_lake_stages_settle_too(
    case: str, stages: list, cycles: int, settled: bool, monkeypatch, tmp_path: Path
) -> None:
    del case

    (_, ran, did_settle), _ = _loop(monkeypatch, tmp_path, stages)

    assert (ran, did_settle) == (cycles, settled)


def test_each_cycle_starts_its_lakes_from_the_stages_of_the_cycle_before(
    monkeypatch, tmp_path: Path
) -> None:
    stages = [{"lac0": 60.0}, {"lac0": 60.5}, {"lac0": 60.9}, {"lac0": 60.905}]

    _, seeds = _loop(monkeypatch, tmp_path, stages)

    assert seeds == [{}, {"lac0": 60.0}, {"lac0": 60.5}, {"lac0": 60.9}]


class _Packagedata:
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


def test_the_main_model_starts_its_lakes_from_the_last_cycle(tmp_path: Path) -> None:
    parent = _lake_model(tmp_path)
    parent.lak = SimpleNamespace(packagedata=_Packagedata())
    folder = Path(parent.full_path) / f"{ssic.CYCLE_FOLDER_PREFIX}1" / "cyc1"
    _write_stage_file(folder / "cyc1.lak.stage", [[59.0, 62.0], [59.5, 62.123456789012345]])

    ssic.apply_modflow6_cyclic_spinup_lakes(parent, 2)

    rows = list(parent.lak.packagedata.data)
    assert [(row["boundname"], row["strt"]) for row in rows] == [
        ("lac0", "59.5"),
        ("lac1", repr(62.123456789012345)),
    ]


@pytest.mark.parametrize(
    "has_lake_package",
    [False, True],
    ids=["a model without a LAK package", "a model without lakes"],
)
def test_a_model_without_lakes_keeps_its_package_as_it_is(
    has_lake_package: bool, tmp_path: Path
) -> None:
    parent = _StubMF6(model_folder=tmp_path, model_name="parent")
    if has_lake_package:
        parent.lak = SimpleNamespace(packagedata=_Packagedata())

    ssic.apply_modflow6_cyclic_spinup_lakes(parent, 3)

    if has_lake_package:
        assert [row["strt"] for row in parent.lak.packagedata.data] == [60.0, 61.0]


def _flag(tmp_path: Path, *, written: bool) -> Path:
    flag = tmp_path / ".hmp" / "stop.json"
    if written:
        flag.parent.mkdir(exist_ok=True)
        flag.write_text('{"schema": "hydromodpy.stop.v1", "at": "2026-11-10T10:00:00+00:00"}')
    return flag


def test_a_stop_asked_between_two_cycles_ends_the_spinup(monkeypatch, tmp_path: Path) -> None:
    flag = _flag(tmp_path, written=False)
    ran: list[int] = []

    def cycle(model, *, cycle, **_kwargs):
        ran.append(cycle)
        _flag(tmp_path, written=True)
        return np.array([[float(cycle), 2.0]])

    monkeypatch.setattr(ssic, "_run_one_spinup_cycle", cycle)
    parent = _lake_model(tmp_path, lakes=())
    parent.slot = SimpleNamespace(stop_flag=flag)

    with pytest.raises(StopRequested, match="stop requested at 2026-11-10T10:00:00"):
        ssic.run_modflow6_cyclic_spinup(parent, verbose=False)

    assert ran == [0]


def test_a_spinup_without_a_slot_cannot_be_stopped(monkeypatch, tmp_path: Path) -> None:
    _flag(tmp_path, written=True)
    monkeypatch.setattr(ssic, "_run_one_spinup_cycle", lambda *_a, **_k: np.array([[1.0, 2.0]]))

    (_, cycles, settled) = ssic.run_modflow6_cyclic_spinup(
        _lake_model(tmp_path, lakes=()), verbose=False
    )

    assert (cycles, settled) == (2, True)


STOP_FLAGS_OF_AN_AUXILIARY_SLOT = (
    ("a run with a flag", True),
    ("a run without a flag, a trial", False),
)


@pytest.mark.parametrize(
    ("case", "has_flag"),
    STOP_FLAGS_OF_AN_AUXILIARY_SLOT,
    ids=[c[0] for c in STOP_FLAGS_OF_AN_AUXILIARY_SLOT],
)
def test_an_auxiliary_model_reads_the_stop_flag_of_its_run(
    case: str, has_flag: bool, tmp_path: Path
) -> None:
    from hydromodpy.solver.base.plan import RunSlot

    del case
    flag = tmp_path / ".hmp" / "stop.json" if has_flag else None
    parent = SimpleNamespace(slot=RunSlot(tmp_path, "run", stop_flag=flag))

    slot = ssic.auxiliary_slot(parent, tmp_path / "run" / "_cyc0", "cyc0")

    assert slot.stop_flag == flag
