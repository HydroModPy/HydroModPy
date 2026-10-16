"""The runs a calibration saves: the best keeps the budget, the others keep what they read.

Trials write nothing. ``save_runs`` writes the runs it names: the best one keeps
``[simulation.results] keep_per_cell_budget`` as the project file says (the whole
per-cell budget by default), every other saved run takes the ``consumers`` policy.
The pipeline is stubbed down to the step that decides the policy
(``step_configure_results``, the real one) and the step that records it.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from hydromodpy.calibration.config import CalibrationConfig
from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.persistence import CalibrationPersistence
from hydromodpy.calibration.runners import trial as trial_module
from hydromodpy.calibration.runners.promotion import promote_session
from hydromodpy.calibration.runners.trial import TrialContext, promote_prepared_trial
from hydromodpy.core.budget_terms import POLICY_ALL, POLICY_CONSUMERS, BudgetKeep
from hydromodpy.core.state.execution import ExecutionRegistry
from hydromodpy.simulation.planning.results_config import ResultsConfig
from hydromodpy.workflow.internals.state import PipelineState
from hydromodpy.workflow.runner import Pipeline
from hydromodpy.workflow.steps.planning import step_configure_results

pytestmark = pytest.mark.unit


@dataclass
class _Cfg:
    K: float = 1.0
    simulation: Any = field(
        default_factory=lambda: SimpleNamespace(name="toy", results=ResultsConfig())
    )
    display: Any = field(default_factory=lambda: SimpleNamespace(enabled=False, figures=()))

    def model_copy(self, *, deep: bool = False) -> _Cfg:
        return copy.deepcopy(self)


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
    budget_terms: BudgetKeep | None = None


class _Step:
    def __init__(self, name: str, action) -> None:
        self.name = name
        self._action = action

    def run(self, state: PipelineState) -> PipelineState:
        self._action(state)
        return state.advance(step_index=state.step_index + 1, step_name=self.name)


class _Provider:
    def make_pipeline(self, steps, *, run_dir=None):
        return Pipeline(steps, run_dir=run_dir)

    def make_state(self, run_id, data):
        return PipelineState(run_id=run_id, data=dict(data))

    def with_solver_launcher(self, steps, launcher):
        del launcher
        return tuple(steps)

    def apply_structural_updates_from_data(self, ctx) -> None:
        del ctx


@pytest.fixture
def session(tmp_path: Path, monkeypatch):
    """A trial context and the budget each promoted run decided to keep."""
    kept: dict[str, BudgetKeep] = {}
    flags: dict[str, bool] = {}

    def _plan(state: PipelineState) -> None:
        ctx = state.get("ctx")
        ctx.budget_terms = step_configure_results(
            ctx.cfg.simulation.results,
            SimpleNamespace(runs=()),
            ctx.cfg.display,
            display_active=False,
            export_requests=(),
            calibration=None,
            observation=None,
        )

    def _export(state: PipelineState) -> None:
        ctx = state.get("ctx")
        run_dir = state.get("run_dir")
        label = (
            ctx.setup.run_id if run_dir is None or run_dir.parent.name == "runs" else run_dir.name
        )
        kept[label] = ctx.budget_terms
        flags[label] = ctx.cfg.simulation.results.keep_per_cell_budget
        ctx.sim_id = ctx.reserved_sim_id

    monkeypatch.setattr(trial_module, "get_trial_pipeline_provider", _Provider)
    cfg = _Cfg()
    ctx = _Ctx(cfg=cfg, config_path=tmp_path / "calib.toml", raw_toml={})
    trial_ctx = TrialContext(
        base_cfg=cfg,
        ctx=ctx,
        earliest=0,
        downstream_steps=(_Step("prepare_solver", _plan), _Step("export", _export)),
        override_paths={"K": "K"},
        workspace=tmp_path,
        cfg_path=tmp_path / "calib.toml",
        raw_toml={},
    )
    trial_ctx.kept_solves = None
    return trial_ctx, kept, flags


def _persistence(project: Path, rows: int, costs: dict[int, float]) -> CalibrationPersistence:
    """A journaled session of ``rows`` trials, trial ``n`` at parameter ``K = n``."""
    session_dir = project / "sessions" / "best"
    session_dir.mkdir(parents=True)
    persistence = CalibrationPersistence(session_dir)
    persistence.start_session(
        session_id="c" * 32,
        case_id="best",
        site=None,
        project=project.name,
        config_hash="c" * 64,
        hydromodpy_version="2.0.0a5",
        method="grid",
        objective_name="nse",
        search_space={},
        objective_window=None,
    )
    for index in range(1, rows + 1):
        persistence.append_iteration(
            ParamSuggestion(trial_id=index, values={"K": float(index)}),
            EvaluationResult(
                trial_id=index, sim_id=None, objective_value=costs[index], status="completed"
            ),
        )
    return persistence


def _promote(trial_ctx, *, cfg: CalibrationConfig, rows: int, best_trial: int):
    project = trial_ctx.workspace / "project"
    costs = {index: float(index) for index in range(1, rows + 1)}
    costs[best_trial] = 0.0
    outcome = promote_session(
        cfg=cfg,
        trial_ctx=trial_ctx,
        persistence=_persistence(project, rows, costs),
        project_root=project,
        phase="main",
        session_status="completed",
        override_paths={"K": "K"},
        objective_window=None,
    )
    return outcome.count, outcome.failures, outcome.best_sim_id


@pytest.mark.parametrize(
    "declared",
    [
        {"save_runs": "best_n", "save_best_n": 3},
        {"save_runs": "all"},
    ],
)
def test_the_best_run_keeps_everything_and_the_others_keep_what_they_read(
    session, declared
) -> None:
    trial_ctx, kept, flags = session

    count, failures, best_sim_id = _promote(
        trial_ctx, cfg=CalibrationConfig(**declared), rows=3, best_trial=2
    )

    assert (count, failures) == (3, [])
    assert best_sim_id is not None
    # Every promoted run is named after the case; the best one keeps everything,
    # the two kept trials take the consumers policy, in the order they were promoted.
    assert kept["best"] == BudgetKeep.everything()
    assert kept["best"].policy == POLICY_ALL
    assert flags["best"] is True
    assert [policy.policy for policy in kept.values()][1:] == [POLICY_CONSUMERS, POLICY_CONSUMERS]
    assert list(flags.values())[1:] == [False, False]


def test_the_best_run_follows_the_project_file(session) -> None:
    trial_ctx, kept, flags = session
    trial_ctx.base_cfg.simulation.results = ResultsConfig(keep_per_cell_budget=False)

    _promote(
        trial_ctx,
        cfg=CalibrationConfig(save_runs="best_n", save_best_n=2),
        rows=2,
        best_trial=1,
    )

    assert flags["best"] is False
    assert kept["best"].policy == POLICY_CONSUMERS


def test_a_saved_run_never_changes_the_shared_configuration(session) -> None:
    trial_ctx, _, _ = session

    _promote(
        trial_ctx,
        cfg=CalibrationConfig(save_runs="all"),
        rows=3,
        best_trial=1,
    )

    assert trial_ctx.base_cfg.simulation.results.keep_per_cell_budget is True
    assert trial_ctx.ctx.cfg.simulation.results.keep_per_cell_budget is True


def test_the_override_is_set_on_a_copy_of_the_results_section(session) -> None:
    trial_ctx, kept, flags = session
    shared = trial_ctx.base_cfg.simulation.results

    promote_prepared_trial(
        trial_ctx, {"K": 2.0}, name="lean", sim_id="a" * 32, keep_per_cell_budget=False
    )
    promote_prepared_trial(trial_ctx, {"K": 3.0}, name="whole", sim_id="b" * 32)

    assert kept["lean"].policy == POLICY_CONSUMERS and flags["lean"] is False
    assert kept["whole"] == BudgetKeep.everything() and flags["whole"] is True
    assert trial_ctx.base_cfg.simulation.results is shared
    assert shared.keep_per_cell_budget is True


def test_the_default_promotes_the_best_alone_with_the_whole_budget(session) -> None:
    trial_ctx, kept, _ = session

    count, failures, _ = _promote(trial_ctx, cfg=CalibrationConfig(), rows=3, best_trial=2)

    assert (count, failures) == (1, [])
    assert list(kept) == ["best"]
    assert kept["best"] == BudgetKeep.everything()
