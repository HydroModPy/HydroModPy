"""Solves that a calibration trial keeps on disk for its promotion.

A promoted trial reads the solve its trial kept instead of solving again. No
solver runs here. Costs are unitless and head files are stand-in bytes. The
equality with a replay on a real MODFLOW 6 model is in tests/e2e.
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.persistence import CalibrationPersistence
from hydromodpy.calibration.runners import trial as trial_module
from hydromodpy.calibration.runners.kept_solves import (
    KeptSolve,
    KeptSolveLauncher,
    TrialSolveRetention,
)
from hydromodpy.calibration.runners.session_scope import keep_trial_solves
from hydromodpy.calibration.runners.trial import (
    TrialContext,
    promote_prepared_trial,
    run_trial_light,
)
from hydromodpy.core.exceptions import CalibrationError
from hydromodpy.core.state.run_state import ExecutionRegistry
from hydromodpy.model.initial.state import PriorState
from hydromodpy.model.model import Properties
from hydromodpy.solver.base.plan import RunSlot, SolverRun
from hydromodpy.workflow.runner import Pipeline
from hydromodpy.workflow.state import PipelineState
from tests._helpers.model_factory import make_model
from tests.unit.calibration._factories import Setup
from tests.unit.calibration._factories_runners import FakePipeline, ToyCtx

pytestmark = pytest.mark.usefixtures("ensure_bootstrap")


def _folder(root: Path, name: str) -> Path:
    folder = root / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "model.hds").write_bytes(b"heads")
    return folder


def _solved(folder: Path, solver_model: Any = None, **fields: Any) -> SolverRun:
    return SolverRun(
        slot=RunSlot(folder.parent, folder.name),
        solver_model=solver_model,
        output_dir=folder,
        written=True,
        solved=True,
        **fields,
    )


def _results(folder: Path, run_id: str = "flow_main") -> dict[str, SolverRun]:
    return {run_id: _solved(folder, object())}


def _offer(retention: TrialSolveRetention, root: Path, trial_id: int, cost: float) -> Path:
    folder = _folder(root, f"m_trial{trial_id:06d}")
    retention.offer(trial_id, cost, [folder], _results(folder))
    return folder


def test_retention_attached_by_save_runs() -> None:
    trial_ctx = SimpleNamespace(kept_solves=None)
    keep_trial_solves(CalibrationConfig(save_runs="none"), trial_ctx)
    assert trial_ctx.kept_solves is None
    keep_trial_solves(CalibrationConfig(save_runs="all"), trial_ctx)
    assert isinstance(trial_ctx.kept_solves, TrialSolveRetention)


def test_worker_solve_adopted_by_cost(tmp_path: Path) -> None:
    retention = TrialSolveRetention(1, keep_everything=False)
    solves = []
    for trial_id, cost in ((7, 1.0), (8, 5.0)):
        folder = _folder(tmp_path, f"w_trial{trial_id}")
        solves.append(KeptSolve(trial_id, cost, (folder,), _results(folder)))
        retention.adopt(solves[-1])

    kept, _ = retention.take(7)
    assert (kept.trial_id, kept.cost, kept.folders) == (7, 1.0, solves[0].folders)
    # The solver object stays with the kept solve.
    assert kept.results == solves[0].results
    assert solves[0].folders[0].is_dir() and not solves[1].folders[0].exists()


def test_promoted_solve_kept_at_release(tmp_path: Path) -> None:
    retention = TrialSolveRetention(None, keep_everything=False)
    promoted = _offer(retention, tmp_path, 1, 1.0)
    other = _offer(retention, tmp_path, 2, 2.0)

    assert retention.spared_folders(1) == (other,)
    retention.promoted(1)
    retention.release()

    assert promoted.is_dir(), "the promoted run's export step decides about its folder"
    assert not other.is_dir()
    assert retention.take(2)[0] is None


def test_late_trial_not_kept(tmp_path: Path) -> None:
    retention = TrialSolveRetention(None, keep_everything=False)
    retention.release()
    late = _folder(tmp_path, "m_trial000001")
    assert retention.offer(1, 1.0, [late], _results(late)) is False
    assert late.is_dir(), "left to its sandbox, which deletes it on exit"


def test_keep_everything_keeps_folders(tmp_path: Path) -> None:
    retention = TrialSolveRetention(1, keep_everything=True)
    dropped = _offer(retention, tmp_path, 1, 3.0)
    kept = _offer(retention, tmp_path, 2, 1.0)
    retention.release()
    assert dropped.is_dir() and kept.is_dir()
    assert dropped in retention.spared_folders()


def test_missing_folder_not_read(tmp_path: Path) -> None:
    retention = TrialSolveRetention(None, keep_everything=False)
    folder = _offer(retention, tmp_path, 1, 1.0)
    for child in folder.iterdir():
        child.unlink()
    folder.rmdir()
    kept, why_not = retention.take(1)
    assert kept is None and "is gone" in str(why_not)


class _SolverStandIn:
    """A solver object as an adapter returns it: the frozen Model in ``inputs``."""

    def __init__(self, inputs: object) -> None:
        self.inputs = inputs


def test_kept_solve_pickles_with_model(tmp_path: Path) -> None:
    # A worker of a parallel calibration sends the solves it keeps to the parent
    # with conn.send, which pickles them.
    model = make_model(
        properties=Properties(profiles={"K": 1e-5}, overrides={"K": 2e-5}),
        lakes={"lake": {"bedleak": 1.0}},
        sfr={"reach": {"streambed_k": 2.0}},
        flow_barriers={"wall": {"hydchr": 3.0}},
        initial=PriorState(head=[[1.0, 2.0]], lake_stages={"lake": 4.0}, path="prior"),
    )
    folder = _folder(tmp_path, "trial_1")
    kept = KeptSolve(
        trial_id=1,
        cost=0.5,
        folders=(folder,),
        results={"flow_main": _solved(folder, _SolverStandIn(model))},
    )

    copy = pickle.loads(pickle.dumps(kept))

    assert (copy.trial_id, copy.cost, copy.folders) == (1, 0.5, (folder,))
    sent = copy.results["flow_main"].solver_model.inputs
    assert copy.results["flow_main"].output_dir == folder
    assert sent.properties.overrides == {"K": 2e-5}
    assert sent.lakes == {"lake": {"bedleak": 1.0}}
    assert sent.sfr == {"reach": {"streambed_k": 2.0}}
    assert sent.flow_barriers == {"wall": {"hydchr": 3.0}}
    assert sent.initial.lake_stages == {"lake": 4.0}
    with pytest.raises(TypeError):
        sent.lakes["other"] = {}


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


def test_launcher_records_trial_solve(tmp_path: Path) -> None:
    folder = _folder(tmp_path, "m_trial000001")
    model = object()
    kept = KeptSolve(
        trial_id=1,
        cost=0.5,
        folders=(folder,),
        results={
            "mesh_main": SolverRun(
                slot=RunSlot(tmp_path, "mesh_main"), metrics={"backend": "catchment"}
            ),
            "flow_main": _solved(folder, model),
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
    assert state.execution.solver_runs == kept.results
    assert state.execution.solver_runs["flow_main"].solver_model is model
    assert state.execution.solver_runs["flow_main"].output_dir == folder
    assert fired == [("before", "mesh"), ("after", "mesh"), ("before", "flow"), ("after", "flow")]


def test_launcher_refuses_missing_solve(tmp_path: Path) -> None:
    kept = KeptSolve(trial_id=4, cost=0.5, folders=(), results={})
    state = SimpleNamespace(execution=ExecutionRegistry(), setup=SimpleNamespace(flow=object()))
    with pytest.raises(CalibrationError, match="Trial 4 kept no solve"):
        KeptSolveLauncher(kept).execute(_Plan(runs=(_Run("flow_main"),)), state)


@dataclass
class _Cfg:
    K: float = 1.0
    simulation: Any = field(default_factory=lambda: SimpleNamespace(name="toy"))

    def model_copy(self, *, deep: bool = False) -> _Cfg:
        return _Cfg(K=self.K)


class _Solver:
    """A solver that writes one head file whose bytes depend on K only."""

    solves: ClassVar[list[str]] = []

    def execute(self, plan, state, *, callbacks=None, store=None):
        del callbacks, store
        request = state.setup.slot_request
        model_name = (request.name if request is not None else None) or state.setup.run_id
        folder = Path(state.setup.workspace.solver_scratch_folder) / model_name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "model.hds").write_text(f"heads for K={state.cfg.K!r}", encoding="utf-8")
        self.solves.append(model_name)
        executed = []
        for run in plan.runs:
            result = _solved(
                folder,
                SimpleNamespace(name=model_name),
                metrics={"water_budget_percent_discrepancy": 0.01},
            )
            state.execution.solver_runs[run.id] = result
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


class _Provider(FakePipeline):
    """The workflow pipeline over the toy steps above."""

    def with_solver_launcher(self, steps, launcher):
        return tuple(_SolverStep(launcher) if step.name == "run_solver" else step for step in steps)


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
        folder = ctx.execution.solver_runs["flow_main"].output_dir
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
    setup = Setup(workspace=SimpleNamespace(solver_scratch_folder=tmp_path / "scratch"))
    ctx = ToyCtx(cfg=cfg, config_path=tmp_path / "calib.toml", raw_toml={}, setup=setup)
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
    monkeypatch.setattr(trial_module, "_PIPELINE", _Provider())
    monkeypatch.setattr("hydromodpy.solver.base.runner.SimulationRunner", _Solver)
    _Solver.solves.clear()
    stores: dict[str, str] = {}
    return _toy_trial_context(tmp_path, stores), stores


def _cost(ctx, *, objective, variable):
    del objective, variable
    return float(ctx.cfg.K), {"cost": float(ctx.cfg.K)}


def test_trial_hands_solve_to_retention(toy) -> None:
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


def test_promotion_reads_kept_solve(toy) -> None:
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
