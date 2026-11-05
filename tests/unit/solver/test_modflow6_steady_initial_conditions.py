from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.time import (
    ResolvedSimulationTimeWindow,
    build_simulation_time_boundaries,
    validate_recharge_coverage,
)
from hydromodpy.core.time.steady_initialization import (
    single_period_mean_forcing_time_grid,
)
from hydromodpy.physics.flow.initial_conditions import FlowInitialConditions
from hydromodpy.solver.initial_conditions import (
    summarize_head_initial_condition_bounds,
)
from hydromodpy.solver.modflow6.build import mf6_safe_name
from hydromodpy.solver.modflow6.modflow6_config import (
    Modflow6Config,
    Modflow6RuntimeConfig,
)
from hydromodpy.solver.modflow6.support import steady_initial_conditions as ssic
from hydromodpy.solver.modflow6.support.steady_initial_conditions import (
    _modflow_config_for_steady_initialization,
    _read_final_percent_discrepancy,
    _steady_initialization_balance_is_acceptable,
)
from hydromodpy.solver.steady_initial_conditions import (
    cycles_have_settled,
    cyclic_flow_copy_for_initialization,
    cyclic_spinup_strategy,
    flow_uses_cyclic_spinup,
)
from hydromodpy.spatial.forcing.cells import stress_period_bounds


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

    def __init__(self, *, model_folder, model_name, **_kwargs) -> None:
        self.model_name = model_name
        self.model_name_mf6 = mf6_safe_name(model_name)
        self.model_output_name = model_name
        self.full_path = str(Path(model_folder) / model_name)
        self.auxiliary = False
        self.geographic = None
        self.modflow_config = None
        self.flow = SimpleNamespace()
        self.domain = None
        self.runtime_cell_mesh = None
        self.time_grid = None
        self.preprocess_options = SimpleNamespace()

    def pre_processing(self, **_kwargs) -> None:
        Path(self.full_path).mkdir(parents=True, exist_ok=True)

    def processing(self, _options) -> bool:
        # MF6 stopped short of convergence; its listing carries a closed budget.
        (Path(self.full_path) / f"{self.model_name_mf6}.lst").write_text(CLOSED_LISTING)
        return False


def test_a_run_named_with_capitals_still_finds_the_listing(monkeypatch, tmp_path) -> None:
    """The listing the solve wrote is the one the acceptance reads, so no RuntimeError."""
    monkeypatch.setattr(ssic, "_read_final_head", lambda *_a, **_k: np.zeros((1, 2)))
    monkeypatch.setattr(ssic, "steady_flow_copy_for_initialization", lambda flow: flow)
    monkeypatch.setattr(ssic, "_compact_flow_forcings_to_one_period", lambda *_a: 0)
    monkeypatch.setattr(ssic, "single_period_mean_forcing_time_grid", lambda grid: grid)
    monkeypatch.setattr(ssic, "_modflow_config_for_steady_initialization", lambda _m: None)
    parent = _StubMF6(model_folder=tmp_path, model_name="Run With Capitals")

    with pytest.warns(RuntimeWarning, match="final water budget is closed"):
        head = ssic.run_modflow6_steady_state_initialization(parent, verbose=False)

    assert head.shape == (1, 2)


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


def _flow(**ic):
    payload = {"kind": "spinup_cyclic", **ic}
    return SimpleNamespace(initial_conditions=FlowInitialConditions.model_validate({"h": payload}))


class TestTheDeclaration:
    def test_the_type_is_recognised(self) -> None:
        assert flow_uses_cyclic_spinup(_flow()) is True

    def test_another_initial_condition_is_not(self) -> None:
        other = SimpleNamespace(
            initial_conditions=FlowInitialConditions.model_validate({"h": {"kind": "top"}})
        )
        assert flow_uses_cyclic_spinup(other) is False

    def test_the_tolerance_carries_its_unit(self) -> None:
        assert cyclic_spinup_strategy(_flow(tol_head="2 cm")).tol_head_m == pytest.approx(0.02)

    def test_the_defaults_are_a_real_strategy(self) -> None:
        strategy = cyclic_spinup_strategy(_flow())
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


class TestTheCycleDoesNotSpawnItsOwn:
    """The defect that a real run found, and the only gate that catches it early."""

    def test_a_cycle_s_flow_no_longer_asks_for_cycling(self) -> None:
        # Measured before this was fixed: each auxiliary model re-entered the same
        # hook, so a three-cycle spin-up ran 143 solves and was stopped by the
        # machine rather than by the loop.
        cycle_flow = cyclic_flow_copy_for_initialization(_flow(max_cycles=3))
        assert flow_uses_cyclic_spinup(cycle_flow) is False

    def test_the_cycle_starts_from_the_top_surface(self) -> None:
        # The caller overwrites it with the previous cycle's heads; what matters is
        # that the copy carries a type the hook does not fire on.
        cycle_flow = cyclic_flow_copy_for_initialization(_flow())
        assert cycle_flow.initial_conditions.h.kind == "top"

    def test_the_original_flow_is_left_alone(self) -> None:
        flow = _flow(max_cycles=2)
        cyclic_flow_copy_for_initialization(flow)
        assert flow_uses_cyclic_spinup(flow) is True


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
