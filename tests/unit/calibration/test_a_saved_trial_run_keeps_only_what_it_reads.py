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
from hydromodpy.calibration.runners import promotion as promotion_module
from hydromodpy.calibration.runners import trial as trial_module
from hydromodpy.calibration.runners.promotion import promote_iterations
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
    def make_pipeline(self, steps):
        return Pipeline(steps)

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
        kept[ctx.setup.run_id] = ctx.budget_terms
        flags[ctx.setup.run_id] = ctx.cfg.simulation.results.keep_per_cell_budget
        ctx.sim_id = ctx.reserved_sim_id

    monkeypatch.setattr(trial_module, "get_trial_pipeline_provider", _Provider)
    monkeypatch.setattr(trial_module, "_attach_tags_to_simulation", lambda *args: None)
    monkeypatch.setattr(promotion_module, "update_iter_sim_id", lambda *args: None)
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


class _Persistence:
    def __init__(self, count: int) -> None:
        self._rows = [
            {
                "iteration": index,
                "parameters": {"K": float(index)},
                "objective_value": float(index),
                "status": "completed",
            }
            for index in range(1, count + 1)
        ]

    def top_n(self, session_id: str, n: int) -> list[dict[str, Any]]:
        del session_id
        return self._rows[:n]

    def load_iterations(self, session_id: str) -> list[dict[str, Any]]:
        del session_id
        return list(self._rows)


def _promote(trial_ctx, *, cfg: CalibrationConfig, rows: int, best_trial: int):
    return promote_iterations(
        cfg=cfg,
        trial_ctx=trial_ctx,
        catalog=None,
        persistence=_Persistence(rows),
        session_id="c" * 32,
        best=SimpleNamespace(trial_id=best_trial),
        override_paths={"K": "K"},
        run_name="best",
    )


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
    assert kept["best"] == BudgetKeep.everything()
    assert kept["best"].policy == POLICY_ALL
    for name in ("best_trial_0001", "best_trial_0003"):
        assert kept[name].policy == POLICY_CONSUMERS
        assert flags[name] is False
    assert flags["best"] is True


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


def test_rerun_best_alone_keeps_the_default(session) -> None:
    trial_ctx, kept, _ = session

    count, failures, _ = _promote(
        trial_ctx,
        cfg=CalibrationConfig(save_runs="none", rerun_best_with_outputs=True),
        rows=3,
        best_trial=2,
    )

    assert (count, failures) == (1, [])
    assert list(kept) == ["best"]
    assert kept["best"] == BudgetKeep.everything()
