"""A calibration trial that moves property profiles only derives its Model and reruns its lane.

The preparation plays ``prepare_solver`` once on the base configuration, and the
trials start at ``run_solver``. The fork of such a trial replaces the profiles
it moves on the prepared ``Model`` and keeps every other member, so the runner
can rerun the last solved trial of its lane. It never rebuilds the ``Flow``,
never binds the forcings again and never plays ``prepare_solver``. Any other
path keeps the fork of before. A trial returns the profile of its steps and
solves.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel

from hydromodpy.calibration.runners import trial as trial_module
from hydromodpy.calibration.runners.lanes import TrialParents
from hydromodpy.calibration.runners.trial import (
    TrialContext,
    _with_the_model_built,
    run_trial_light,
)
from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.model.flow import Flow
from hydromodpy.model.flow_config import FlowConfig
from hydromodpy.model.model import ModelTime, model_from_flow
from hydromodpy.solver.base.plan import RunSlot, SolverRun
from hydromodpy.workflow.state import PipelineState
from tests._helpers.model_factory import default_options, small_geometry, time_grid
from tests.unit.calibration._factories_runners import FakePipeline

GEOMETRY = small_geometry()
TIME = ModelTime(grid=time_grid(10.0), regime="steady", first_period_steady=True)
OPTIONS = default_options()
K_PATH = "flow.param.K.field.value"


class _Cfg(BaseModel):
    flow: FlowConfig


def _base_cfg() -> _Cfg:
    return _Cfg(
        flow=FlowConfig.model_validate(
            {
                "param_list": ["K", "Sy"],
                "param": {
                    "K": {"field": {"id": "K", "kind": "homogeneous", "value": "1e-5 m/s"}},
                    "Sy": {"field": {"id": "Sy", "kind": "homogeneous", "value": "0.1 -"}},
                },
            }
        )
    )


class _Counted:
    """A step that counts its calls and runs ``action`` on the context."""

    def __init__(self, name: str, action: Any = None) -> None:
        self.name = name
        self.action = action
        self.calls = 0

    def run(self, state: PipelineState) -> PipelineState:
        self.calls += 1
        if self.action is not None:
            self.action(state.get("ctx"))
        return state.advance(step_index=state.step_index + 1, step_name=self.name)


def _build_model(ctx: Any) -> None:
    """What ``prepare_solver`` leaves on a light run: the plan, the budget policy, the Model."""
    ctx.execution.simulation_plan = SimpleNamespace(runs=(SimpleNamespace(id="flow"),))
    ctx.budget_terms = "kept terms"
    ctx.setup.model = model_from_flow(ctx.setup.flow, geometry=GEOMETRY, time=TIME, options=OPTIONS)


class _Launching(_Counted):
    """Stands in for ``RunSolverStep``: runs the plan through the launcher it is given."""

    def __init__(self, launcher: Any = None) -> None:
        super().__init__("run_solver")
        self.launcher = launcher

    def run(self, state: PipelineState) -> PipelineState:
        ctx = state.get("ctx")
        if self.launcher is not None:
            self.launcher.execute(ctx.execution.simulation_plan, ctx)
        return super().run(state)


class _Pipeline(FakePipeline):
    """Counts the forcing bindings, builds the Flow they bind, and hands the launcher on."""

    def __init__(self) -> None:
        self.bindings = 0

    def apply_structural_updates_from_data(self, ctx) -> None:
        self.bindings += 1
        ctx.setup.flow = Flow(ctx.cfg.flow)

    def with_solver_launcher(self, steps, launcher):
        return tuple(_Launching(launcher) if step.name == "run_solver" else step for step in steps)


@pytest.fixture
def pipeline(monkeypatch: pytest.MonkeyPatch) -> _Pipeline:
    installed = _Pipeline()
    monkeypatch.setattr(trial_module, "_PIPELINE", installed)
    return installed


def _steps() -> tuple[_Counted, ...]:
    return (
        _Counted("setup_process"),
        _Counted("prepare_solver", _build_model),
        _Launching(),
        _Counted("extract"),
    )


def _prepared(tmp_path: Path, *, paths: dict[str, str], earliest: int = 1) -> TrialContext:
    cfg = _base_cfg()
    setup = SimpleNamespace(
        run_id="calage",
        workspace=SimpleNamespace(solver_scratch_folder=tmp_path / "scratch"),
        domain=object(),
        flow=Flow(cfg.flow),
        model=None,
        slot_request=None,
    )
    ctx = SimpleNamespace(
        cfg=cfg,
        setup=setup,
        loaded_data=SimpleNamespace(recharge=None),
        data_plan=None,
        execution=SimpleNamespace(rng=None, simulation_plan=None),
        bounds=Bounds(),
        budget_terms=None,
    )
    return TrialContext(
        base_cfg=cfg,
        ctx=ctx,
        earliest=earliest,
        downstream_steps=_steps(),
        override_paths=paths,
        workspace=tmp_path,
        cfg_path=tmp_path / "calib.toml",
    )


def _contents(model: Any) -> dict[str, Any]:
    return {name: profile.as_dict() for name, profile in model.properties.profiles.items()}


def test_profile_paths_build_the_model_once_and_start_the_trials_at_run_solver(
    tmp_path: Path, pipeline: _Pipeline
) -> None:
    prepared = _with_the_model_built(_prepared(tmp_path, paths={"K": K_PATH}), pipeline)

    assert prepared.model_from_profiles is True
    assert prepared.downstream_steps[prepared.earliest].name == "run_solver"
    assert prepared.downstream_steps[1].calls == 1
    assert prepared.ctx.setup.model is not None
    assert prepared.ctx.budget_terms == "kept terms"
    assert prepared.profile_ids() == ("K",)


def test_the_fork_of_a_trial_on_k_derives_its_model_without_rebuilding_anything(
    tmp_path: Path, pipeline: _Pipeline
) -> None:
    prepared = _with_the_model_built(_prepared(tmp_path, paths={"K": K_PATH}), pipeline)
    model = prepared.ctx.setup.model
    bindings = pipeline.bindings

    forks = [prepared.fork({"K": value}, derive_model=True) for value in (2e-5, 3e-5)]

    assert pipeline.bindings == bindings, "no forcing is bound again"
    assert prepared.downstream_steps[1].calls == 1, "prepare_solver is not played again"
    for fork, value in zip(forks, (2e-5, 3e-5), strict=True):
        derived = fork.ctx.setup.model
        built = model_from_flow(
            Flow(fork.ctx.cfg.flow), geometry=GEOMETRY, time=TIME, options=OPTIONS
        )
        assert _contents(derived) == _contents(built)
        assert derived.properties.profiles["K"].value == pytest.approx(value)
        assert derived.properties.profiles["Sy"] is model.properties.profiles["Sy"]
        assert derived.geometry is model.geometry and derived.time is model.time
        assert fork.ctx.setup.flow is None
        assert fork.ctx.execution.simulation_plan is prepared.ctx.execution.simulation_plan
        assert fork.ctx.budget_terms == "kept terms"
        assert fork.model_from_profiles and fork.parents is None


def test_a_promotion_fork_rebuilds_the_flow_and_plays_prepare_solver_again(
    tmp_path: Path, pipeline: _Pipeline
) -> None:
    prepared = _with_the_model_built(_prepared(tmp_path, paths={"K": K_PATH}), pipeline)
    bindings = pipeline.bindings

    fork = prepared.fork({"K": 2e-5})

    assert pipeline.bindings == bindings + 1
    assert fork.ctx.setup.model is None
    assert fork.ctx.setup.flow.parameters["K"].value == pytest.approx(2e-5)


KEPT: tuple[tuple[str, dict[str, str], int], ...] = (
    ("a recharge factor", {"f": "flow.sinks_sources.recharge.factor"}, 1),
    ("a profile and a recharge factor", {"K": K_PATH, "f": "flow.sinks_sources.recharge.f"}, 1),
    ("an id param_list does not declare", {"Ss": "flow.param.Ss.field.value"}, 1),
    ("an earliest step before prepare_solver", {"K": K_PATH}, 0),
)


@pytest.mark.parametrize(("case", "paths", "earliest"), KEPT, ids=[c for c, *_ in KEPT])
def test_any_other_trial_keeps_the_fork_of_before(
    tmp_path: Path, pipeline: _Pipeline, case: str, paths: dict[str, str], earliest: int
) -> None:
    del case
    context = _prepared(tmp_path, paths=paths, earliest=earliest)
    prepared = _with_the_model_built(context, pipeline)

    assert prepared is context
    assert prepared.model_from_profiles is False
    assert prepared.downstream_steps[1].calls == 0
    fork = prepared.fork({}, derive_model=True)
    assert fork.ctx.setup.model is None
    assert pipeline.bindings == 1


class _Runner:
    """Stands in for ``SimulationRunner``: writes the input files and remembers its parents."""

    given: ClassVar[list[Any]] = []

    def execute(self, plan, state, *, callbacks=None, previous=None):
        del callbacks
        self.given.append(None if previous is None else dict(previous))
        slot = state.setup.slot_request
        folder = Path(state.setup.workspace.solver_scratch_folder) / slot.name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "model.npf").write_text("npf", encoding="utf-8")
        sim = SimpleNamespace(sim_path=os.fspath(folder))
        sim.set_sim_path = lambda path: setattr(sim, "sim_path", path)
        run = SolverRun(
            slot=RunSlot(folder.parent, folder.name),
            model=state.setup.model,
            solver_model=SimpleNamespace(sim=sim),
            output_dir=folder,
            input_files=("model.npf",),
            written=True,
            solved=True,
            solve_s=0.01,
            reran=previous is not None,
        )
        executed = []
        for planned in plan.runs:
            state.execution.solver_runs[planned.id] = run
            executed.append((planned, run))
        return tuple(executed)


def _cost(ctx, *, objective, variable):
    del objective, variable
    return float(ctx.setup.model.properties.profiles["K"].value) * 1e5, {}


def test_a_trial_hands_the_parent_of_its_lane_to_the_runner_and_returns_its_profile(
    tmp_path: Path, pipeline: _Pipeline, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("hydromodpy.solver.base.runner.SimulationRunner", _Runner)
    _Runner.given.clear()
    prepared = _with_the_model_built(_prepared(tmp_path, paths={"K": K_PATH}), pipeline)
    prepared.parents = TrialParents.of(prepared)

    first = run_trial_light(prepared, {"K": 2e-5}, metric_fn=_cost, trial_id=1)
    second = run_trial_light(prepared, {"K": 3e-5}, metric_fn=_cost, trial_id=2)

    assert (first.status, second.status) == ("completed", "completed")
    assert second.primary_metric == pytest.approx(3.0)
    assert _Runner.given[0] is None
    (parent,) = _Runner.given[1].values()
    lane = tmp_path / "scratch" / "calage_lane1" / "flow"
    assert parent.output_dir == lane
    assert (lane / "model.npf").is_file()
    assert not (tmp_path / "scratch" / "calage_trial000001").exists()
    assert [line.name for line in first.profile if line.kind == "step"] == ["run_solver", "extract"]


def test_a_failed_trial_leaves_its_lane_empty(
    tmp_path: Path, pipeline: _Pipeline, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("hydromodpy.solver.base.runner.SimulationRunner", _Runner)
    _Runner.given.clear()
    prepared = _with_the_model_built(_prepared(tmp_path, paths={"K": K_PATH}), pipeline)
    prepared.parents = TrialParents.of(prepared)

    def fails(ctx, *, objective, variable):
        raise RuntimeError("no record")

    run_trial_light(prepared, {"K": 2e-5}, metric_fn=_cost, trial_id=1)
    failed = run_trial_light(prepared, {"K": 3e-5}, metric_fn=fails, trial_id=2)
    run_trial_light(prepared, {"K": 4e-5}, metric_fn=_cost, trial_id=3)

    assert failed.status == "failed"
    assert _Runner.given[1] is not None
    assert _Runner.given[2] is None, "the parent of the failed trial was consumed"
