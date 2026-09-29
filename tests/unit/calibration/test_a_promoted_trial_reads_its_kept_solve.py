"""A promoted trial reads the solve its trial kept instead of solving again.

Three things are pinned here, none of them spawning a solver:

- retention: which trial solves stay on disk, and when each one goes;
- the trial primitive hands a completed solve to the retention before its
  sandbox would delete it, and a promotion reads it through the solver step;
- the fallback: a trial with no kept solve is solved again, and the log says why.

The equality of a promoted run with a replay on a real MODFLOW 6 model is in
``tests/e2e/test_a_promoted_trial_is_not_solved_again_e2e.py``.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.runners import promotion as promotion_module
from hydromodpy.calibration.runners import trial as trial_module
from hydromodpy.calibration.runners.cli_runner import _keep_trial_solves, _release_trial_solves
from hydromodpy.calibration.runners.kept_solves import (
    KeptSolve,
    KeptSolveLauncher,
    RecordingLauncher,
    TrialSolveRetention,
    retention_capacity,
)
from hydromodpy.calibration.runners.trial import (
    TrialContext,
    promote_prepared_trial,
    run_trial_light,
)
from hydromodpy.core.exceptions import CalibrationError
from hydromodpy.core.state.execution import ExecutionRegistry
from hydromodpy.simulation.planning.plan import RunExecutionResult
from hydromodpy.workflow.internals.state import PipelineState
from hydromodpy.workflow.runner import Pipeline

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module", autouse=True)
def _ensure_bootstrap():
    import hydromodpy

    hydromodpy.bootstrap()


def _folder(root: Path, name: str) -> Path:
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "model.hds").write_bytes(b"heads")
    return folder


def _results(folder: Path, run_id: str = "flow_main") -> dict[str, RunExecutionResult]:
    return {run_id: RunExecutionResult(primary_model=object(), solver_output_dir=folder)}


def _offer(retention: TrialSolveRetention, root: Path, trial_id: int, cost: float) -> Path:
    folder = _folder(root, f"m_trial{trial_id:06d}")
    retention.offer(trial_id, cost, [folder], _results(folder))
    return folder


# ---------------------------------------------------------------------------
# What a session keeps
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("declared", "expected"),
    [
        ({"save_runs": "all"}, None),
        ({"save_runs": "best_n", "save_best_n": 3}, 3),
        ({"save_runs": "none", "rerun_best_with_outputs": True}, 1),
        ({"save_runs": "best_n", "save_best_n": 0, "rerun_best_with_outputs": True}, 1),
        ({"save_runs": "none"}, 0),
    ],
)
def test_a_session_keeps_as_many_solves_as_it_promotes(declared, expected) -> None:
    assert retention_capacity(CalibrationConfig(**declared)) == expected


def test_a_session_that_promotes_nothing_attaches_no_retention() -> None:
    trial_ctx = SimpleNamespace(kept_solves=None)
    _keep_trial_solves(CalibrationConfig(save_runs="none"), trial_ctx)
    assert trial_ctx.kept_solves is None
    _keep_trial_solves(CalibrationConfig(save_runs="all"), trial_ctx)
    assert isinstance(trial_ctx.kept_solves, TrialSolveRetention)


def test_every_completed_trial_is_kept_when_all_are_promoted(tmp_path: Path) -> None:
    retention = TrialSolveRetention(None, keep_everything=False)
    folders = [
        _offer(retention, tmp_path, trial_id, cost) for trial_id, cost in enumerate((3, 1, 2))
    ]
    assert all(folder.is_dir() for folder in folders)
    assert all(retention.take(trial_id)[0] is not None for trial_id in range(3))


def test_a_solve_goes_as_soon_as_cheaper_ones_fill_the_retention(tmp_path: Path) -> None:
    retention = TrialSolveRetention(2, keep_everything=False)
    first = _offer(retention, tmp_path, 1, 3.0)
    second = _offer(retention, tmp_path, 2, 1.0)
    assert first.is_dir() and second.is_dir()

    third = _offer(retention, tmp_path, 3, 2.0)

    assert not first.is_dir(), "the most expensive solve can no longer be promoted"
    assert second.is_dir() and third.is_dir()
    kept, why_not = retention.take(1)
    assert kept is None and "cheapest" in str(why_not)


def test_a_trial_worse_than_every_kept_one_is_left_to_its_sandbox(tmp_path: Path) -> None:
    retention = TrialSolveRetention(1, keep_everything=False)
    _offer(retention, tmp_path, 1, 1.0)
    folder = _folder(tmp_path, "m_trial000002")
    assert retention.offer(2, 5.0, [folder], _results(folder)) is False
    # Retention does not delete what it never took: the sandbox exit does.
    assert folder.is_dir()


def test_a_tie_keeps_the_earlier_trial(tmp_path: Path) -> None:
    retention = TrialSolveRetention(1, keep_everything=False)
    early = _offer(retention, tmp_path, 1, 1.0)
    late = _folder(tmp_path, "m_trial000002")
    assert retention.offer(2, 1.0, [late], _results(late)) is False
    assert early.is_dir()


def test_trials_offered_side_by_side_keep_the_cheapest(tmp_path: Path) -> None:
    retention = TrialSolveRetention(1, keep_everything=False)
    costs = [float((7 * index) % 20) + 0.5 for index in range(20)]
    outcome: dict[int, bool] = {}
    folders: dict[int, Path] = {}

    def _worker(trial_id: int) -> None:
        folders[trial_id] = _folder(tmp_path, f"m_trial{trial_id:06d}")
        outcome[trial_id] = retention.offer(
            trial_id, costs[trial_id], [folders[trial_id]], _results(folders[trial_id])
        )

    threads = [threading.Thread(target=_worker, args=(index,)) for index in range(20)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    cheapest = min(range(20), key=lambda index: costs[index])
    assert retention.take(cheapest)[0] is not None
    for trial_id in range(20):
        if trial_id == cheapest:
            continue
        assert retention.take(trial_id)[0] is None
        # Taken and later pushed out: deleted by retention. Refused on arrival:
        # left to the sandbox, so still on disk here.
        assert folders[trial_id].is_dir() is (not outcome[trial_id])


def test_a_promoted_solve_belongs_to_its_run_and_the_rest_go_at_release(tmp_path: Path) -> None:
    retention = TrialSolveRetention(None, keep_everything=False)
    promoted = _offer(retention, tmp_path, 1, 1.0)
    other = _offer(retention, tmp_path, 2, 2.0)

    assert retention.spared_folders(1) == (other,)
    retention.promoted(1)
    retention.release()

    assert promoted.is_dir(), "the promoted run's export step decides about its folder"
    assert not other.is_dir()
    assert retention.take(2)[0] is None


def test_a_trial_that_finishes_after_the_session_ended_is_not_kept(tmp_path: Path) -> None:
    retention = TrialSolveRetention(None, keep_everything=False)
    retention.release()
    late = _folder(tmp_path, "m_trial000001")
    assert retention.offer(1, 1.0, [late], _results(late)) is False
    assert late.is_dir(), "left to its sandbox, which deletes it on exit"


def test_keep_trial_scratch_keeps_every_folder(tmp_path: Path) -> None:
    retention = TrialSolveRetention(1, keep_everything=True)
    dropped = _offer(retention, tmp_path, 1, 3.0)
    kept = _offer(retention, tmp_path, 2, 1.0)
    retention.release()
    assert dropped.is_dir() and kept.is_dir()
    assert dropped in retention.spared_folders()


def test_the_session_releases_its_solves_and_detaches_the_retention(tmp_path: Path) -> None:
    retention = TrialSolveRetention(None, keep_everything=False)
    folder = _offer(retention, tmp_path, 1, 1.0)
    trial_ctx = SimpleNamespace(kept_solves=retention)

    _release_trial_solves(trial_ctx)

    assert trial_ctx.kept_solves is None
    assert not folder.is_dir()


def test_a_solve_whose_folder_is_gone_is_not_read(tmp_path: Path) -> None:
    retention = TrialSolveRetention(None, keep_everything=False)
    folder = _offer(retention, tmp_path, 1, 1.0)
    for child in folder.iterdir():
        child.unlink()
    folder.rmdir()
    kept, why_not = retention.take(1)
    assert kept is None and "is gone" in str(why_not)


def test_a_trial_that_never_ran_here_says_so(tmp_path: Path) -> None:
    kept, why_not = TrialSolveRetention(None, keep_everything=False).take(7)
    assert kept is None and "cache hit" in str(why_not)


# ---------------------------------------------------------------------------
# The launchers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Run:
    id: str
    process_type: str = "flow"
    solver: str = "modflow6"

    @property
    def is_solver_backed(self) -> bool:
        return self.process_type != "mesh"


@dataclass(frozen=True)
class _Plan:
    runs: tuple[_Run, ...]


def test_the_kept_solve_launcher_records_what_the_trial_produced(tmp_path: Path) -> None:
    folder = _folder(tmp_path, "m_trial000001")
    model = object()
    kept = KeptSolve(
        trial_id=1,
        cost=0.5,
        folders=(folder,),
        results={
            "mesh_main": RunExecutionResult(primary_model=None, metrics={"backend": "catchment"}),
            "flow_main": RunExecutionResult(primary_model=model, solver_output_dir=folder),
        },
    )
    fired: list[tuple[str, str]] = []
    callbacks = SimpleNamespace(
        before_process=lambda family: fired.append(("before", family)),
        after_process=lambda family: fired.append(("after", family)),
    )
    state = SimpleNamespace(execution=ExecutionRegistry(), setup=SimpleNamespace(flow=object()))
    plan = _Plan(runs=(_Run("mesh_main", "mesh", "catchment"), _Run("flow_main")))

    executed = KeptSolveLauncher(kept).execute(plan, state, callbacks=callbacks)

    assert [run.id for run, _ in executed] == ["mesh_main", "flow_main"]
    assert state.execution.models_by_run_id == {"flow_main": model}
    assert state.execution.output_dirs_by_run_id == {"flow_main": folder}
    assert fired == [("before", "mesh"), ("after", "mesh"), ("before", "flow"), ("after", "flow")]


def test_the_kept_solve_launcher_refuses_a_run_it_has_no_solve_for(tmp_path: Path) -> None:
    kept = KeptSolve(trial_id=4, cost=0.5, folders=(), results={})
    state = SimpleNamespace(execution=ExecutionRegistry(), setup=SimpleNamespace(flow=object()))
    with pytest.raises(CalibrationError, match="Trial 4 kept no solve"):
        KeptSolveLauncher(kept).execute(_Plan(runs=(_Run("flow_main"),)), state)


def test_the_solver_step_of_a_pipeline_takes_the_launcher_it_is_given() -> None:
    from hydromodpy.calibration.runners.contracts import get_trial_pipeline_provider
    from hydromodpy.workflow.steps.run_solver import RunSolverStep

    provider = get_trial_pipeline_provider()
    steps = tuple(provider.standard_steps())
    launcher = RecordingLauncher()

    swapped = provider.with_solver_launcher(steps, launcher)

    assert [step.name for step in swapped] == [step.name for step in steps]
    solver_steps = [step for step in swapped if isinstance(step, RunSolverStep)]
    assert len(solver_steps) == 1 and solver_steps[0].launcher is launcher
    assert all(
        new is old for new, old in zip(swapped, steps, strict=True) if new.name != "run_solver"
    )


# ---------------------------------------------------------------------------
# Trial and promotion over a stubbed solver
# ---------------------------------------------------------------------------


@dataclass
class _Cfg:
    K: float = 1.0
    simulation: Any = field(default_factory=lambda: SimpleNamespace(name="toy"))

    def model_copy(self, *, deep: bool = False) -> _Cfg:
        return _Cfg(K=self.K)


@dataclass
class _Setup:
    workspace: Any = None
    geographic: Any = None
    flow: Any = None
    transport: Any = None
    flow_runtime_overrides: Any = None
    run_id: str = "toy"
    time_grid: Any = None


@dataclass
class _Ctx:
    cfg: _Cfg
    config_path: Path
    raw_toml: dict[str, Any]
    data_plan: Any = None
    setup: _Setup = field(default_factory=_Setup)
    loaded_data: Any = None
    execution: ExecutionRegistry = field(default_factory=ExecutionRegistry)
    sim_id: Any = None
    reserved_sim_id: Any = None


class _Solver:
    """A solver that writes one head file whose bytes depend on K only."""

    solves: ClassVar[list[str]] = []

    def execute(self, plan, state, *, callbacks=None, store=None):
        del callbacks, store
        overrides = state.setup.flow_runtime_overrides or {}
        model_name = overrides.get("model_name_override") or state.setup.run_id
        folder = Path(state.setup.workspace.solver_scratch_folder) / model_name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "model.hds").write_text(f"heads for K={state.cfg.K!r}", encoding="utf-8")
        self.solves.append(model_name)
        executed = []
        for run in plan.runs:
            result = RunExecutionResult(
                primary_model=SimpleNamespace(name=model_name),
                solver_output_dir=folder,
                metrics={"water_budget_percent_discrepancy": 0.01},
            )
            state.execution.models_by_run_id[run.id] = result.primary_model
            state.execution.output_dirs_by_run_id[run.id] = folder
            executed.append((run, result))
        return tuple(executed)


class _Step:
    def __init__(self, name: str, action=None) -> None:
        self.name = name
        self._action = action

    def run(self, state: PipelineState) -> PipelineState:
        if self._action is not None:
            self._action(state)
        return state.advance(step_index=state.step_index + 1, step_name=self.name)


class _SolverStep(_Step):
    """Stands in for ``RunSolverStep``: runs the plan through its launcher."""

    def __init__(self, launcher=None) -> None:
        super().__init__("run_solver")
        self.launcher = launcher

    def run(self, state: PipelineState) -> PipelineState:
        ctx = state.get("ctx")
        launcher = self.launcher if self.launcher is not None else _Solver()
        executed = launcher.execute(ctx.execution.simulation_plan, ctx)
        state = state.with_data(runtime_metrics=[result.metrics for _, result in executed])
        return state.advance(step_index=state.step_index + 1, step_name=self.name)


class _Provider:
    """The workflow provider over the toy steps above."""

    def make_pipeline(self, steps):
        return Pipeline(steps)

    def make_state(self, run_id, data):
        return PipelineState(run_id=run_id, data=dict(data))

    def with_solver_launcher(self, steps, launcher):
        return tuple(_SolverStep(launcher) if step.name == "run_solver" else step for step in steps)

    def apply_structural_updates_from_data(self, ctx) -> None:
        del ctx


def _bind_flow(state: PipelineState) -> None:
    state.get("ctx").setup.flow = SimpleNamespace(name="flow")


def _plan(state: PipelineState) -> None:
    ctx = state.get("ctx")
    if ctx.execution.simulation_plan is None:
        ctx.execution.simulation_plan = _Plan(runs=(_Run("flow_main"),))


def _toy_trial_context(tmp_path: Path, stores: dict[str, str]) -> TrialContext:
    """A trial context whose extraction copies the head file into ``stores``."""

    def _extract(state: PipelineState) -> None:
        ctx = state.get("ctx")
        folder = ctx.execution.output_dirs_by_run_id["flow_main"]
        stores[ctx.setup.run_id] = (Path(folder) / "model.hds").read_text(encoding="utf-8")

    def _export(state: PipelineState) -> None:
        ctx = state.get("ctx")
        ctx.sim_id = ctx.reserved_sim_id
        stores[f"{ctx.setup.run_id}:spared"] = ",".join(sorted(state.get("kept_scratch") or ()))

    steps = (
        _Step("validate"),
        _Step("setup_process", _bind_flow),
        _Step("prepare_solver", _plan),
        _SolverStep(),
        _Step("extract", _extract),
        _Step("derive"),
        _Step("display"),
        _Step("export", _export),
    )
    cfg = _Cfg()
    setup = _Setup(workspace=SimpleNamespace(solver_scratch_folder=tmp_path / "scratch"))
    ctx = _Ctx(cfg=cfg, config_path=tmp_path / "calib.toml", raw_toml={}, setup=setup)
    return TrialContext(
        base_cfg=cfg,
        ctx=ctx,
        earliest=1,
        downstream_steps=steps,
        override_paths={"K": "K"},
        workspace=tmp_path,
        cfg_path=tmp_path / "calib.toml",
        raw_toml={},
    )


@pytest.fixture
def toy(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(trial_module, "get_trial_pipeline_provider", _Provider)
    monkeypatch.setattr(trial_module, "_attach_tags_to_simulation", _record_tags)
    monkeypatch.setattr("hydromodpy.simulation.execution.runner.SimulationRunner", _Solver)
    _Solver.solves.clear()
    _TAGS.clear()
    stores: dict[str, str] = {}
    return _toy_trial_context(tmp_path, stores), stores


_TAGS: dict[str, list[str]] = {}


def _record_tags(ctx, sim_id, tags) -> None:
    del ctx
    _TAGS[str(sim_id)] = list(tags)


def _cost(ctx, *, objective, variable):
    del objective, variable
    return float(ctx.cfg.K), {"cost": float(ctx.cfg.K)}


def test_a_trial_hands_its_solve_to_the_retention(toy) -> None:
    trial_ctx, _ = toy
    trial_ctx.kept_solves = TrialSolveRetention(1, keep_everything=False)
    scratch = trial_ctx.ctx.setup.workspace.solver_scratch_folder

    run_trial_light(trial_ctx, {"K": 2.0}, metric_fn=_cost, trial_id=1)
    assert (scratch / "toy_trial000001" / "model.hds").is_file()

    run_trial_light(trial_ctx, {"K": 1.0}, metric_fn=_cost, trial_id=2)
    assert not (scratch / "toy_trial000001").exists(), "pushed out by a cheaper trial"
    assert (scratch / "toy_trial000002" / "model.hds").is_file()

    run_trial_light(trial_ctx, {"K": 5.0}, metric_fn=_cost, trial_id=3)
    assert not (scratch / "toy_trial000003").exists(), "never kept, deleted by its sandbox"

    kept, _ = trial_ctx.kept_solves.take(2)
    assert kept is not None
    assert kept.results["flow_main"].metrics == {"water_budget_percent_discrepancy": 0.01}


def test_a_failed_trial_keeps_nothing(toy) -> None:
    trial_ctx, _ = toy
    trial_ctx.kept_solves = TrialSolveRetention(None, keep_everything=False)
    scratch = trial_ctx.ctx.setup.workspace.solver_scratch_folder

    result = run_trial_light(
        trial_ctx,
        {"K": 1.0},
        metric_fn=lambda ctx, *, objective, variable: (float("nan"), {}),
        trial_id=1,
    )

    assert result.status == "failed"
    assert not (scratch / "toy_trial000001").exists()
    assert trial_ctx.kept_solves.take(1)[0] is None


def test_the_promoted_run_is_the_one_a_replay_writes_without_a_second_solve(toy) -> None:
    trial_ctx, stores = toy
    trial_ctx.kept_solves = TrialSolveRetention(None, keep_everything=False)
    run_trial_light(trial_ctx, {"K": 3.0}, metric_fn=_cost, trial_id=1)
    run_trial_light(trial_ctx, {"K": 4.0}, metric_fn=_cost, trial_id=2)
    kept, _ = trial_ctx.kept_solves.take(1)
    assert kept is not None
    solves_before = list(_Solver.solves)

    promote_prepared_trial(
        trial_ctx,
        {"K": 3.0},
        name="from_kept",
        sim_id="a" * 32,
        kept=kept,
        spared=trial_ctx.kept_solves.spared_folders(1),
    )
    assert _Solver.solves == solves_before, "the promotion read the kept solve"

    promote_prepared_trial(trial_ctx, {"K": 3.0}, name="replayed", sim_id="b" * 32)
    assert _Solver.solves == [*solves_before, "replayed"]

    assert stores["from_kept"] == stores["replayed"] == "heads for K=3.0"
    other = trial_ctx.ctx.setup.workspace.solver_scratch_folder / "toy_trial000002"
    assert stores["from_kept:spared"] == str(other)
    assert stores["replayed:spared"] == ""
    assert "promoted_from_trial:1" in _TAGS["a" * 32]
    assert not any(tag.startswith("promoted_from_trial") for tag in _TAGS.get("b" * 32, []))


def test_a_trial_without_a_kept_solve_is_solved_again_and_the_log_says_why(
    tmp_path: Path, monkeypatch, caplog
) -> None:
    retention = TrialSolveRetention(1, keep_everything=False)
    _offer(retention, tmp_path, 1, 1.0)
    second = _offer(retention, tmp_path, 2, 0.5)
    calls: list[dict[str, Any]] = []

    def _fake_promote(trial_ctx, values, **kwargs):
        del trial_ctx, values
        calls.append(kwargs)
        return kwargs["sim_id"]

    class _Persistence:
        def load_iterations(self, session_id):
            del session_id
            return [
                {"iteration": 1, "status": "completed", "objective_value": 1.0, "parameters": {}},
                {"iteration": 2, "status": "completed", "objective_value": 0.5, "parameters": {}},
            ]

    monkeypatch.setattr(promotion_module, "promote_prepared_trial", _fake_promote)
    monkeypatch.setattr(promotion_module, "update_iter_sim_id", lambda *args: None)
    trial_ctx = SimpleNamespace(kept_solves=retention)

    with caplog.at_level(logging.INFO, logger=promotion_module.logger.name):
        count, failures, _ = promotion_module.promote_iterations(
            cfg=CalibrationConfig(save_runs="all"),
            trial_ctx=trial_ctx,
            catalog=None,
            persistence=_Persistence(),
            session_id="c" * 32,
            best=None,
            override_paths={},
            run_name="toy",
        )

    assert (count, failures) == (2, [])
    assert calls[0]["kept"] is None
    assert calls[1]["kept"] is not None and calls[1]["kept"].trial_id == 2
    replayed = [record.getMessage() for record in caplog.records if "again" in record.getMessage()]
    assert len(replayed) == 1
    assert "trial 1" in replayed[0] and "cheapest" in replayed[0]
    retention.release()
    assert second.is_dir(), "a promoted solve is left to its run"
