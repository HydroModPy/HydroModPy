"""What a calibration run in phases hands from one stage to the next.

The solver never runs here: :func:`run_calibration_core` and
:func:`prepare_trials` are replaced by a recorder, so what is under test is
the staging itself -- the order of the phases, the configuration each one
runs under, where a frozen value lands, and the chain of sessions.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.calibration.report import CalibrationReport
from hydromodpy.calibration.runners import staged_runner
from hydromodpy.calibration.runners.staged_runner import run_staged_calibration
from hydromodpy.calibration.runners.trial import TrialContext

K_PATH = "flow.param.K.field.value"
SY_PATH = "flow.param.Sy.field.value"
K_TOML = 1e-5
SY_TOML = 0.1
K_CALIBRATED = 2.5e-5
SY_CALIBRATED = 0.07

BASE = """
[calibration]
method = "grid"
max_iter = 4

[calibration.parameters.K]
bounds = [1e-9, 1e-3]
transform = "log"
target = "flow.param.K.field.value"

[calibration.parameters.Sy]
bounds = [0.001, 0.3]
target = "flow.param.Sy.field.value"

[calibration.outputs.q]
variable = "discharge"
support = "boundary"
boundary_id = "outlet"
observed_values = [1.0, 2.0]

[calibration.outputs.h]
variable = "head"
support = "point"
x = 100.0
y = 0.0
observed_values = [42.0, 41.5]

[[calibration.objective_blocks]]
name = "q_block"
metric = "rmse"
uses_outputs = ["q"]

[[calibration.objective_blocks]]
name = "h_block"
metric = "rmse"
uses_outputs = ["h"]
"""

TWO_PHASES = """
[[calibration.phases]]
name = "steady_k"
method = "bisection"
max_iter = 12
parameters = ["K"]
outputs = ["q"]
objective_blocks = ["q_block"]

[[calibration.phases]]
name = "transient_sy"
method = "grid"
max_iter = 30
parameters = ["Sy"]
depends_on = "steady_k"
"""

NO_FREEZE = """
[[calibration.phases]]
name = "steady_k"
method = "bisection"
max_iter = 12
parameters = ["K"]
freeze_on_success = false

[[calibration.phases]]
name = "transient_sy"
method = "grid"
max_iter = 30
parameters = ["Sy", "K"]
depends_on = "steady_k"
"""


def _write(tmp_path: Path, phases: str = TWO_PHASES) -> Path:
    """Write a calibration TOML and return its path."""
    path = tmp_path / "calibration.toml"
    path.write_text(BASE + phases, encoding="utf-8")
    return path


def _baseline() -> SimpleNamespace:
    """A configuration tree the calibrated paths can be written into."""
    return SimpleNamespace(
        flow=SimpleNamespace(
            param=SimpleNamespace(
                K=SimpleNamespace(field=SimpleNamespace(value=K_TOML)),
                Sy=SimpleNamespace(field=SimpleNamespace(value=SY_TOML)),
            )
        )
    )


class FakeRunner:
    """Stands in for the preparation and the calibration loop of one phase."""

    def __init__(self, *, best_objective: float | None = 0.25) -> None:
        self.best_objective = best_objective
        self.values = {"K": K_CALIBRATED, "Sy": SY_CALIBRATED}
        self.prepared: list[dict[str, str]] = []
        self.calls: list[SimpleNamespace] = []

    @property
    def phases_run(self) -> list[str]:
        return [call.chain.phase_name for call in self.calls]

    def prepare_trials(
        self,
        cfg_path: Path,
        *,
        override_paths,
        steps=None,
        parameter_space=None,
    ) -> TrialContext:
        self.prepared.append(dict(override_paths))
        return TrialContext(
            base_cfg=_baseline(),
            ctx=None,
            earliest=0,
            downstream_steps=(),
            override_paths=dict(override_paths),
            workspace=cfg_path.parent,
            cfg_path=cfg_path,
            parameter_space=parameter_space,
        )

    def run_calibration_core(
        self,
        cfg,
        trial_ctx,
        *,
        workspace,
        space,
        project_label="calibration",
        cfg_path=None,
        metric_fn=None,
        objective=None,
        store_factory=None,
        chain=None,
    ) -> CalibrationReport:
        self.calls.append(
            SimpleNamespace(
                cfg=cfg,
                trial_ctx=trial_ctx,
                baseline=trial_ctx.base_cfg,
                space=space,
                workspace=workspace,
                chain=chain,
            )
        )
        best = {name: self.values[name] for name in cfg.parameters}
        return CalibrationReport(
            session_id=chain.session_id,
            method=cfg.method,
            n_iterations=cfg.max_iter,
            best_objective=self.best_objective,
            best_sim_id=None,
            duration_s=1.0,
            save_runs=cfg.save_runs,
            promoted=0,
            best_parameters=None if self.best_objective is None else best,
            workspace=workspace,
        )


@pytest.fixture
def runner(monkeypatch) -> FakeRunner:
    fake = FakeRunner()
    monkeypatch.setattr(staged_runner, "prepare_trials", fake.prepare_trials)
    monkeypatch.setattr(staged_runner, "run_calibration_core", fake.run_calibration_core)
    return fake


# -- order and per-phase configuration --------------------------------------


def test_the_phases_run_in_declaration_order(tmp_path, runner) -> None:
    report = run_staged_calibration(_write(tmp_path))

    assert runner.phases_run == ["steady_k", "transient_sy"]
    assert [phase.name for phase in report.phases] == ["steady_k", "transient_sy"]
    assert [phase.index for phase in report.phases] == [0, 1]


def test_each_phase_runs_the_search_it_declares(tmp_path, runner) -> None:
    run_staged_calibration(_write(tmp_path))

    steady, transient = (call.cfg for call in runner.calls)
    assert (steady.method, steady.max_iter) == ("bisection", 12)
    assert (transient.method, transient.max_iter) == ("grid", 30)
    assert list(steady.parameters) == ["K"]
    assert list(transient.parameters) == ["Sy"]
    assert runner.calls[0].space.names == ("K",)
    assert runner.calls[1].space.names == ("Sy",)


def test_a_phase_config_is_an_ordinary_mono_phase_calibration(tmp_path, runner) -> None:
    run_staged_calibration(_write(tmp_path))

    assert all(call.cfg.phases is None for call in runner.calls)


def test_a_phase_scores_on_what_it_selects_and_a_silent_phase_on_everything(
    tmp_path, runner
) -> None:
    run_staged_calibration(_write(tmp_path))

    steady, transient = (call.cfg for call in runner.calls)
    assert list(steady.outputs) == ["q"]
    assert [block.name for block in steady.objective_blocks] == ["q_block"]
    assert sorted(transient.outputs) == ["h", "q"]
    assert [block.name for block in transient.objective_blocks] == ["q_block", "h_block"]


# -- freezing ----------------------------------------------------------------


def test_a_frozen_parameter_leaves_the_search_of_the_next_phase(tmp_path, runner) -> None:
    run_staged_calibration(_write(tmp_path))

    transient = runner.calls[1]
    assert "K" not in transient.cfg.parameters
    assert "K" not in transient.space.names


def test_a_frozen_parameter_enters_the_baseline_of_the_next_phase(tmp_path, runner) -> None:
    run_staged_calibration(_write(tmp_path))

    steady, transient = runner.calls
    assert steady.baseline.flow.param.K.field.value == pytest.approx(K_TOML)
    assert transient.baseline.flow.param.K.field.value == pytest.approx(K_CALIBRATED)
    assert transient.baseline.flow.param.Sy.field.value == pytest.approx(SY_TOML)


def test_the_prepared_pipeline_treats_the_frozen_path_as_varying(tmp_path, runner) -> None:
    # A preparation step reading the frozen path has to re-run per trial,
    # otherwise the prepared prefix would keep the value the TOML declares.
    run_staged_calibration(_write(tmp_path))

    assert runner.prepared[0] == {"K": K_PATH}
    assert runner.prepared[1] == {"Sy": SY_PATH, "K": K_PATH}


def test_the_report_names_each_frozen_value_with_its_path(tmp_path, runner) -> None:
    report = run_staged_calibration(_write(tmp_path))

    assert [item.to_dict() for item in report.frozen] == [
        {
            "name": "K",
            "path": K_PATH,
            "value": pytest.approx(K_CALIBRATED),
            "mode": "replace",
            "phase": "steady_k",
        },
        {
            "name": "Sy",
            "path": SY_PATH,
            "value": pytest.approx(SY_CALIBRATED),
            "mode": "replace",
            "phase": "transient_sy",
        },
    ]
    assert report.to_dict()["phases"][0]["frozen"][0]["path"] == K_PATH


def test_freeze_on_success_false_leaves_the_next_phase_free_to_move_it(tmp_path, runner) -> None:
    report = run_staged_calibration(_write(tmp_path, NO_FREEZE))

    transient = runner.calls[1]
    assert "K" in transient.cfg.parameters
    assert "K" in transient.space.names
    assert transient.baseline.flow.param.K.field.value == pytest.approx(K_TOML)
    assert report.phases[0].frozen == ()


def test_a_phase_that_did_not_converge_freezes_nothing(tmp_path, monkeypatch) -> None:
    fake = FakeRunner(best_objective=None)
    monkeypatch.setattr(staged_runner, "prepare_trials", fake.prepare_trials)
    monkeypatch.setattr(staged_runner, "run_calibration_core", fake.run_calibration_core)

    report = run_staged_calibration(_write(tmp_path))

    assert report.frozen == ()
    assert fake.calls[1].baseline.flow.param.K.field.value == pytest.approx(K_TOML)
    assert "K" not in fake.prepared[1]


def test_a_best_cost_at_the_failure_sentinel_is_not_a_convergence(tmp_path, monkeypatch) -> None:
    from hydromodpy.calibration.optim.optimizer import FAILED_EVAL_COST

    fake = FakeRunner(best_objective=FAILED_EVAL_COST)
    monkeypatch.setattr(staged_runner, "prepare_trials", fake.prepare_trials)
    monkeypatch.setattr(staged_runner, "run_calibration_core", fake.run_calibration_core)

    report = run_staged_calibration(_write(tmp_path))

    assert report.frozen == ()


# -- selecting one phase -----------------------------------------------------


def test_selecting_a_phase_whose_dependency_did_not_run_is_refused(tmp_path, runner) -> None:
    with pytest.raises(ValueError, match="steady_k"):
        run_staged_calibration(_write(tmp_path), phase="transient_sy")

    assert runner.calls == []


def test_selecting_an_independent_phase_runs_only_it(tmp_path, runner) -> None:
    report = run_staged_calibration(_write(tmp_path), phase="steady_k")

    assert runner.phases_run == ["steady_k"]
    assert [phase.index for phase in report.phases] == [0]


def test_selecting_an_undeclared_phase_lists_the_declared_ones(tmp_path, runner) -> None:
    with pytest.raises(ValueError, match="transient_sy"):
        run_staged_calibration(_write(tmp_path), phase="nowhere")


def test_a_calibration_without_phases_is_refused(tmp_path, runner) -> None:
    with pytest.raises(ValueError, match="run_calibration_cli"):
        run_staged_calibration(_write(tmp_path, ""))


# -- session chain -----------------------------------------------------------


def test_the_chain_links_each_phase_to_the_previous_one(tmp_path, runner) -> None:
    report = run_staged_calibration(_write(tmp_path))

    first, second = (call.chain for call in runner.calls)
    assert first.parent_session_id is None
    assert first.root_session_id == first.session_id
    assert second.parent_session_id == first.session_id
    assert second.root_session_id == first.session_id
    assert first.session_id != second.session_id
    assert (first.phase_index, second.phase_index) == (0, 1)
    assert (first.phase_name, second.phase_name) == ("steady_k", "transient_sy")


def test_the_report_carries_the_chain_of_the_run(tmp_path, runner) -> None:
    report = run_staged_calibration(_write(tmp_path))

    assert report.root_session_id == report.phases[0].session_id
    assert report.phases[0].parent_session_id is None
    assert report.phases[1].parent_session_id == report.phases[0].session_id
    assert report.phases[1].root_session_id == report.root_session_id


def test_a_single_selected_phase_is_the_root_of_its_own_chain(tmp_path, runner) -> None:
    report = run_staged_calibration(_write(tmp_path), phase="steady_k")

    chain = runner.calls[0].chain
    assert chain.parent_session_id is None
    assert chain.root_session_id == chain.session_id == report.root_session_id
